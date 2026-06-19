from __future__ import annotations

import base64
import json
import os
import random
import re
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from PIL import Image

from codex_image.auth import AuthState
from codex_image.client import DEFAULT_CODEX_IMAGES_BASE_URL, DEFAULT_IMAGE_MODEL, CodexImagesImageClient
from codex_image.webui.oai4k_db import OAI4KDatabase


OAI4K_MODELS = [
    {
        "id": "gpt-image-2",
        "object": "model",
        "owned_by": "openai-codex-web",
        "type": "image",
        "provider_model": "gpt-image-2",
        "capabilities": {
            "image_generation": True,
            "image_edit": True,
            "image_reference": True,
            "native_size": True,
            "max_size": "3840x2160",
        },
    },
    {
        "id": "oai-4k-gpt-image-2",
        "object": "model",
        "owned_by": "OAI-4K-01",
        "type": "image",
        "provider_model": "gpt-image-2",
        "capabilities": {
            "image_generation": True,
            "image_edit": True,
            "image_reference": True,
            "native_size": True,
            "max_size": "3840x2160",
        },
    },
]

SIZE_PRESETS = {
    "1024x1024",
    "1536x864",
    "864x1536",
    "2048x2048",
    "2048x1152",
    "1152x2048",
    "2880x2880",
    "2560x3200",
    "3200x2560",
    "2448x3264",
    "3264x2448",
    "2336x3504",
    "3504x2336",
    "2160x3840",
    "3840x2160",
    "1632x3808",
    "3808x1632",
}


def register_oai4k_routes(app: FastAPI, *, media_root: Path, db_path: Path | None = None) -> None:
    db = OAI4KDatabase(db_path)
    media_root.mkdir(parents=True, exist_ok=True)

    @app.get("/ping")
    async def ping() -> dict[str, Any]:
        return {"status": "ok", "provider": "OAI-4K-01", "time": int(time.time())}

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {"object": "list", "data": OAI4K_MODELS}

    @app.post("/v1/images/generations")
    async def image_generations(request: Request) -> dict[str, Any]:
        body = await _read_generation_body(request)
        return await _run_image_request(request, db, media_root, body, input_images=[])

    @app.post("/v1/images/edits")
    async def image_edits(
        request: Request,
        prompt: str | None = Form(None),
        model: str | None = Form(None),
        size: str | None = Form(None),
        quality: str | None = Form(None),
        background: str | None = Form(None),
        output_format: str | None = Form(None),
        response_format: str | None = Form(None),
        n: int | None = Form(None),
        image: list[UploadFile] | None = File(None),
        images: list[UploadFile] | None = File(None),
        mask: UploadFile | None = File(None),
    ) -> dict[str, Any]:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            files = list(image or []) + list(images or [])
            if not files:
                raise HTTPException(status_code=400, detail="At least one image file is required")
            body = {
                "prompt": prompt,
                "model": model,
                "size": size,
                "quality": quality,
                "background": background,
                "output_format": output_format,
                "response_format": response_format,
                "n": n,
            }
            input_images = [await _upload_to_data_url(file) for file in files]
            mask_image = await _upload_to_data_url(mask) if mask is not None else None
            return await _run_image_request(request, db, media_root, body, input_images=input_images, mask_image=mask_image)

        body = await _read_generation_body(request)
        input_images = _collect_image_inputs(body)
        if not input_images:
            raise HTTPException(status_code=400, detail="At least one image is required")
        mask_image = _image_url_from_any(body.get("mask"))
        return await _run_image_request(request, db, media_root, body, input_images=input_images, mask_image=mask_image)

    @app.post("/v1/images/compositions")
    async def image_compositions(request: Request) -> dict[str, Any]:
        body = await _read_generation_body(request)
        input_images = _collect_image_inputs(body)
        if not input_images:
            raise HTTPException(status_code=400, detail="At least one image is required")
        return await _run_image_request(request, db, media_root, body, input_images=input_images)

    @app.post("/v1/video/generations")
    @app.post("/v1/videos/generations")
    async def unsupported_video() -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": "OAI-4K-01 only exposes GPT-image-2 image generation and edit APIs.",
                    "code": "video_not_supported",
                }
            },
        )

    @app.get("/dashboard", response_model=None)
    async def dashboard_page() -> HTMLResponse:
        return HTMLResponse(_dashboard_html())

    @app.get("/dashboard/status")
    async def dashboard_status() -> dict[str, Any]:
        return {"setupComplete": db.is_setup_complete()}

    @app.post("/dashboard/setup")
    async def dashboard_setup(request: Request) -> Response:
        if db.is_setup_complete():
            return JSONResponse(status_code=400, content={"error": "Setup has already completed"})
        body = await request.json()
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if not username or len(password) < 6:
            return JSONResponse(status_code=400, content={"error": "Username is required and password must be at least 6 chars"})
        db.create_user(username, password)
        return {"success": True}

    @app.post("/dashboard/login")
    async def dashboard_login(request: Request) -> Response:
        body = await request.json()
        user_id = db.validate_user(str(body.get("username") or ""), str(body.get("password") or ""))
        if not user_id:
            return JSONResponse(status_code=401, content={"error": "Invalid username or password"})
        session_id = db.create_session(user_id)
        return JSONResponse(
            {"success": True},
            headers={"Set-Cookie": f"session={session_id}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400"},
        )

    @app.post("/dashboard/logout")
    async def dashboard_logout(request: Request) -> Response:
        session_id = _session_cookie(request)
        if session_id:
            db.delete_session(session_id)
        return JSONResponse(
            {"success": True},
            headers={"Set-Cookie": "session=; Path=/; HttpOnly; Max-Age=0"},
        )

    @app.get("/dashboard/stats")
    async def dashboard_stats(request: Request) -> dict[str, Any]:
        _require_dashboard_auth(db, request)
        return db.stats()

    @app.get("/dashboard/accounts")
    async def dashboard_accounts(request: Request) -> list[dict[str, Any]]:
        _require_dashboard_auth(db, request)
        return db.list_accounts()

    @app.post("/dashboard/accounts")
    async def dashboard_add_account(request: Request) -> dict[str, Any]:
        _require_dashboard_auth(db, request)
        body = await request.json()
        name = str(body.get("name") or "").strip()
        access_token = str(body.get("access_token") or body.get("token") or "").strip()
        refresh_token = str(body.get("refresh_token") or "").strip()
        account_id = str(body.get("account_id") or "").strip()
        if not name or not access_token:
            raise HTTPException(status_code=400, detail="name and access_token are required")
        account_pk = db.add_account(name, access_token, refresh_token, account_id)
        return {"success": True, "id": account_pk}

    @app.post("/dashboard/accounts/check")
    async def dashboard_check_account(request: Request) -> dict[str, Any]:
        _require_dashboard_auth(db, request)
        body = await request.json()
        account_pk = int(body.get("id") or 0)
        account = db.get_account(account_pk)
        if not account:
            raise HTTPException(status_code=404, detail="account not found")
        try:
            client = _client_from_account(account)
            payload = client.build_payload(
                prompt="health check",
                model=DEFAULT_IMAGE_MODEL,
                size="1024x1024",
                quality="low",
                output_format="png",
                n=1,
            )
            if payload.get("model"):
                db.update_account_status(account_pk, "active")
                return {"success": True, "status": "active", "message": "client payload is buildable"}
        except Exception as exc:
            db.update_account_status(account_pk, "error")
            return {"success": False, "status": "error", "error": str(exc)}
        db.update_account_status(account_pk, "unknown")
        return {"success": False, "status": "unknown"}

    @app.delete("/dashboard/accounts")
    async def dashboard_delete_account(request: Request) -> dict[str, Any]:
        _require_dashboard_auth(db, request)
        account_pk = int(request.query_params.get("id") or 0)
        if not account_pk:
            raise HTTPException(status_code=400, detail="id is required")
        db.delete_account(account_pk)
        return {"success": True}

    @app.get("/dashboard/api-keys")
    async def dashboard_api_keys(request: Request) -> list[dict[str, Any]]:
        _require_dashboard_auth(db, request)
        return db.list_api_keys()

    @app.post("/dashboard/api-keys")
    async def dashboard_add_api_key(request: Request) -> dict[str, Any]:
        _require_dashboard_auth(db, request)
        body = await request.json()
        name = str(body.get("name") or "").strip()
        account_id_raw = body.get("account_id")
        account_id = int(account_id_raw) if account_id_raw not in (None, "", 0, "0") else None
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        api_key = db.generate_api_key(name, account_id)
        return {"success": True, "api_key": api_key}

    @app.post("/dashboard/api-keys/toggle")
    async def dashboard_toggle_api_key(request: Request) -> dict[str, Any]:
        _require_dashboard_auth(db, request)
        body = await request.json()
        db.toggle_api_key(int(body.get("id") or 0), bool(body.get("is_active")))
        return {"success": True}

    @app.delete("/dashboard/api-keys")
    async def dashboard_delete_api_key(request: Request) -> dict[str, Any]:
        _require_dashboard_auth(db, request)
        key_id = int(request.query_params.get("id") or 0)
        if not key_id:
            raise HTTPException(status_code=400, detail="id is required")
        db.delete_api_key(key_id)
        return {"success": True}

    @app.get("/dashboard/media")
    async def dashboard_media(request: Request) -> dict[str, Any]:
        _require_dashboard_auth(db, request)
        return {"items": db.list_media(), "total": len(db.list_media())}

    @app.get("/dashboard/logs")
    async def dashboard_logs(request: Request) -> list[dict[str, Any]]:
        _require_dashboard_auth(db, request)
        return db.list_logs()


async def _read_generation_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return body


async def _run_image_request(
    request: Request,
    db: OAI4KDatabase,
    media_root: Path,
    body: dict[str, Any],
    *,
    input_images: list[str],
    mask_image: str | None = None,
) -> dict[str, Any]:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    token, account = _resolve_generation_token(db, request.headers.get("authorization", ""))
    model = _normalize_model(body.get("model"))
    size = _normalize_size(body.get("size") or body.get("resolution") or "1024x1024")
    n = _normalize_n(body.get("n", 1))
    output_format = _normalize_output_format(body.get("output_format") or "png")
    response_format = str(body.get("response_format") or "url").strip() or "url"
    quality = str(body.get("quality") or "low").strip() or "low"
    background = _optional_str(body.get("background"))
    moderation = _optional_str(body.get("moderation"))
    output_compression = _optional_int(body.get("output_compression"))

    try:
        client = _client_from_token(token, account_id=str(account.get("account_id") or "") if account else "")
        if input_images:
            results = client.edit_images(
                prompt=prompt,
                images=input_images,
                mask_image=mask_image,
                model=model,
                size=size,
                quality=quality,
                background=background,
                output_format=output_format,
                moderation=moderation,
                output_compression=output_compression,
                n=n,
            )
        else:
            results = client.generate_images(
                prompt=prompt,
                model=model,
                size=size,
                quality=quality,
                background=background,
                output_format=output_format,
                moderation=moderation,
                output_compression=output_compression,
                n=n,
            )
    except Exception as exc:
        db.add_log("error", f"image request failed: {exc}")
        if account:
            db.update_account_status(int(account["id"]), "error")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if account:
        db.update_account_status(int(account["id"]), "active")

    created = int(time.time())
    data: list[dict[str, Any]] = []
    for index, result in enumerate(results, start=1):
        _validate_exact_size(result.image_bytes, size)
        media_url = _write_media(request, media_root, result.image_bytes, output_format, index=index)
        db.save_media("image", media_url, model, prompt, token, result.size or size)
        item: dict[str, Any] = {
            "revised_prompt": result.revised_prompt or prompt,
            "size": result.size or size,
        }
        if response_format == "b64_json":
            item["b64_json"] = base64.b64encode(result.image_bytes).decode("ascii")
        else:
            item["url"] = media_url
        data.append(item)

    return {"created": created, "data": data}


def _resolve_generation_token(db: OAI4KDatabase, authorization: str) -> tuple[str, dict[str, Any] | None]:
    values = []
    if authorization.lower().startswith("bearer "):
        values = [item.strip() for item in authorization[7:].split(",") if item.strip()]
    selected = random.choice(values) if values else ""
    if not selected:
        raise HTTPException(status_code=401, detail="Authorization Bearer token is required")

    if selected.startswith("sk-oai4k-") or selected.startswith("sk-"):
        api_key = db.validate_api_key(selected)
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid OAI-4K API key")
        account = db.get_account(int(api_key["account_id"])) if api_key.get("account_id") else db.random_account()
        if not account:
            raise HTTPException(status_code=401, detail="API key is valid but no available Codex account exists")
        return str(account["access_token"]), account

    return selected, None


def _client_from_account(account: dict[str, Any]) -> CodexImagesImageClient:
    return _client_from_token(str(account["access_token"]), account_id=str(account.get("account_id") or ""))


def _client_from_token(token: str, *, account_id: str = "") -> CodexImagesImageClient:
    state = AuthState(
        path=Path("output") / "oai4k-inline-auth.json",
        access_token=token,
        refresh_token="",
        id_token="",
        account_id=account_id,
        last_refresh=None,
        raw={},
    )
    return CodexImagesImageClient(
        state,
        base_url=os.environ.get("OAI4K_CODEX_IMAGES_BASE_URL", DEFAULT_CODEX_IMAGES_BASE_URL),
        image_model=DEFAULT_IMAGE_MODEL,
    )


def _normalize_model(value: Any) -> str:
    raw = str(value or DEFAULT_IMAGE_MODEL).strip()
    aliases = {
        "oai-4k-gpt-image-2": "gpt-image-2",
        "codex-gpt-image-2": "gpt-image-2",
        "pro-codex-gpt-image-2": "gpt-image-2",
    }
    model = aliases.get(raw, raw)
    if model != "gpt-image-2":
        raise HTTPException(status_code=400, detail=f"Unsupported model: {raw}")
    return model


def _normalize_size(value: Any) -> str:
    raw = str(value or "1024x1024").strip().lower()
    if raw == "auto":
        return "1024x1024"
    match = re.fullmatch(r"(\d{2,5})\s*x\s*(\d{2,5})", raw)
    if not match:
        raise HTTPException(status_code=400, detail="size must be WIDTHxHEIGHT")
    width = int(match.group(1))
    height = int(match.group(2))
    normalized = f"{width}x{height}"
    if normalized not in SIZE_PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported native GPT-image-2 size: {normalized}. Use one of: {', '.join(sorted(SIZE_PRESETS))}",
        )
    return normalized


def _normalize_n(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 1
    if n < 1 or n > 4:
        raise HTTPException(status_code=400, detail="n must be between 1 and 4")
    return n


def _normalize_output_format(value: Any) -> str:
    output_format = str(value or "png").strip().lower()
    if output_format not in {"png", "jpeg", "webp"}:
        raise HTTPException(status_code=400, detail="output_format must be png, jpeg, or webp")
    return output_format


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="output_compression must be an integer")


def _collect_image_inputs(body: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def append(value: Any) -> None:
        image_url = _image_url_from_any(value)
        if image_url:
            values.append(image_url)

    for key in ("image", "images", "input_image", "input_images", "reference_images", "file_paths", "filePaths"):
        raw = body.get(key)
        if isinstance(raw, list):
            for item in raw:
                append(item)
        else:
            append(raw)
    return list(dict.fromkeys(values))


def _image_url_from_any(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("url"), str):
            return value["url"]
        image_url = value.get("image_url")
        if isinstance(image_url, str):
            return image_url
        if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
            return image_url["url"]
    return None


async def _upload_to_data_url(upload: UploadFile) -> str:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"empty image upload: {upload.filename}")
    mime_type = upload.content_type or "image/png"
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"unsupported image upload type: {mime_type}")
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


def _validate_exact_size(image_bytes: bytes, requested_size: str) -> None:
    if os.environ.get("OAI4K_STRICT_SIZE", "1") not in {"1", "true", "TRUE", "yes"}:
        return
    width, height = [int(part) for part in requested_size.split("x", 1)]
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            actual = image.size
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Generated image cannot be inspected: {exc}") from exc
    if actual != (width, height):
        raise HTTPException(
            status_code=502,
            detail=f"Generated image size mismatch: requested {requested_size}, got {actual[0]}x{actual[1]}. No crop or resize was applied.",
        )

def _write_media(request: Request, media_root: Path, image_bytes: bytes, output_format: str, *, index: int) -> str:
    extension = "jpg" if output_format == "jpeg" else output_format
    filename = f"{int(time.time())}-{uuid.uuid4().hex}-{index}.{extension}"
    path = media_root / filename
    path.write_bytes(image_bytes)
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/api-media/{filename}"


def _session_cookie(request: Request) -> str:
    return request.cookies.get("session", "")


def _require_dashboard_auth(db: OAI4KDatabase, request: Request) -> int:
    user_id = db.validate_session(_session_cookie(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user_id


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OAI-4K-01 控制台</title>
  <style>
    :root {
      --bg-primary: #0f0f23;
      --bg-secondary: #1a1a2e;
      --bg-card: #16213e;
      --text-primary: #e4e4e7;
      --text-secondary: #a1a1aa;
      --accent: #7c3aed;
      --accent-hover: #8b5cf6;
      --success: #10b981;
      --warning: #f59e0b;
      --error: #ef4444;
      --border: #27272a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg-primary);
      color: var(--text-primary);
      font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
      min-height: 100vh;
    }
    .auth-wrap { min-height: 100vh; display: grid; place-items: center; padding: 24px; }
    .auth-box, .card, .table-container, .api-doc {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: 0 24px 60px rgba(0,0,0,.28);
    }
    .auth-box { width: min(420px, 100%); padding: 34px; }
    h1, .brand-title {
      margin: 0;
      background: linear-gradient(135deg,#7c3aed,#ec4899);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    h1 { font-size: 24px; text-align: center; margin-bottom: 24px; }
    label { display: block; color: var(--text-secondary); font-size: 13px; margin: 14px 0 8px; }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--bg-secondary);
      color: var(--text-primary);
      padding: 12px 14px;
      font: inherit;
      outline: none;
    }
    textarea { min-height: 92px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
    input:focus, textarea:focus, select:focus { border-color: var(--accent-hover); box-shadow: 0 0 0 3px rgba(124,58,237,.18); }
    button {
      border: 0;
      border-radius: 10px;
      background: var(--accent);
      color: #fff;
      padding: 11px 16px;
      font-weight: 700;
      cursor: pointer;
      transition: transform .16s ease, background .16s ease, border-color .16s ease;
    }
    button:hover { background: var(--accent-hover); transform: translateY(-1px); }
    button.ghost { background: var(--bg-secondary); color: var(--text-secondary); border: 1px solid var(--border); }
    button.danger { background: var(--error); }
    .hidden { display: none !important; }
    header {
      height: 70px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 30px;
      border-bottom: 1px solid var(--border);
      background: rgba(15,15,35,.86);
      backdrop-filter: blur(18px);
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .brand-title { font-size: 24px; font-weight: 800; }
    main { padding: 28px 30px 50px; max-width: 1440px; margin: 0 auto; }
    .tabs { display: inline-flex; gap: 4px; background: var(--bg-secondary); padding: 4px; border-radius: 12px; margin-bottom: 24px; }
    .tab { background: transparent; color: var(--text-secondary); }
    .tab.active { background: var(--accent); color: #fff; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 16px; margin-bottom: 24px; }
    .card { padding: 22px; }
    .card .label { color: var(--text-secondary); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
    .card .value { margin-top: 8px; font-size: 30px; font-weight: 800; color: #93c5fd; }
    .panel { display: none; animation: panelIn .22s ease both; }
    .panel.active { display: block; }
    @keyframes panelIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
    .toolbar { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 14px; }
    .table-container { overflow: hidden; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 14px 16px; border-bottom: 1px solid var(--border); text-align: left; font-size: 14px; }
    th { background: var(--bg-secondary); color: var(--text-secondary); font-size: 12px; text-transform: uppercase; }
    tr:hover td { background: rgba(124,58,237,.06); }
    code { background: var(--bg-secondary); color: #93c5fd; border-radius: 6px; padding: 3px 8px; }
    .badge { border-radius: 999px; padding: 3px 10px; font-size: 12px; font-weight: 700; }
    .badge.active { background: rgba(16,185,129,.15); color: var(--success); }
    .badge.error { background: rgba(239,68,68,.15); color: var(--error); }
    .badge.unknown { background: rgba(245,158,11,.15); color: var(--warning); }
    .modal { position: fixed; inset: 0; display: none; place-items: center; background: rgba(0,0,0,.76); z-index: 100; padding: 22px; }
    .modal.active { display: grid; }
    .modal-content { width: min(560px,100%); background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px; padding: 24px; }
    .modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .toast { position: fixed; left: 50%; bottom: 26px; transform: translateX(-50%) translateY(12px); opacity: 0; pointer-events: none; background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 22px; transition: .2s ease; }
    .toast.show { opacity: 1; transform: translateX(-50%); }
    .api-doc { padding: 20px; margin-bottom: 16px; }
    .api-doc pre { white-space: pre-wrap; background: #0b1021; border: 1px solid var(--border); border-radius: 10px; padding: 14px; overflow: auto; }
    .new-key { margin-top: 12px; padding: 12px; border: 1px dashed var(--success); border-radius: 10px; color: var(--success); word-break: break-all; font-family: ui-monospace, Consolas, monospace; }
    @media (max-width: 900px) { .grid { grid-template-columns: repeat(2, minmax(0,1fr)); } header { padding: 0 18px; } main { padding: 22px 18px; } }
    @media (max-width: 560px) { .grid { grid-template-columns: 1fr; } .toolbar { align-items: stretch; flex-direction: column; } }
  </style>
</head>
<body>
  <div id="auth" class="auth-wrap">
    <div class="auth-box">
      <h1>OAI-4K-01</h1>
      <label>用户名</label><input id="username" value="admin" autocomplete="username">
      <label>密码</label><input id="password" type="password" autocomplete="current-password">
      <button id="loginBtn" style="width:100%;margin-top:18px">登录 / 初始化</button>
      <p id="authMsg" style="color:var(--text-secondary);text-align:center"></p>
    </div>
  </div>
  <div id="app" class="hidden">
    <header>
      <div class="brand-title">OAI-4K-01</div>
      <div><button class="ghost" onclick="logout()">退出</button></div>
    </header>
    <main>
      <div class="tabs">
        <button class="tab active" data-tab="overview">概览</button>
        <button class="tab" data-tab="accounts">Codex 账号</button>
        <button class="tab" data-tab="keys">API Key</button>
        <button class="tab" data-tab="docs">接口</button>
      </div>
      <section id="overview" class="panel active">
        <div class="grid">
          <div class="card"><div class="label">账号</div><div id="statAccounts" class="value">0</div></div>
          <div class="card"><div class="label">API Keys</div><div id="statKeys" class="value">0</div></div>
          <div class="card"><div class="label">调用</div><div id="statCalls" class="value">0</div></div>
          <div class="card"><div class="label">图片</div><div id="statMedia" class="value">0</div></div>
        </div>
        <div class="api-doc">
          <b>服务地址</b>
          <pre id="baseUrl"></pre>
        </div>
      </section>
      <section id="accounts" class="panel">
        <div class="toolbar"><h2>Codex 账号池</h2><button onclick="openAccountModal()">新增账号</button></div>
        <div class="table-container"><table><thead><tr><th>名称</th><th>Token</th><th>Account ID</th><th>状态</th><th>操作</th></tr></thead><tbody id="accountRows"></tbody></table></div>
      </section>
      <section id="keys" class="panel">
        <div class="toolbar"><h2>API Key</h2><button onclick="openKeyModal()">新增 Key</button></div>
        <div class="table-container"><table><thead><tr><th>名称</th><th>Key</th><th>绑定账号</th><th>调用</th><th>状态</th><th>操作</th></tr></thead><tbody id="keyRows"></tbody></table></div>
      </section>
      <section id="docs" class="panel">
        <div class="api-doc">
          <b>模型列表</b><pre>GET /v1/models</pre>
          <b>生图</b><pre>POST /v1/images/generations
Authorization: Bearer sk-oai4k-...
Content-Type: application/json

{"model":"gpt-image-2","prompt":"a cinematic cat","size":"3840x2160","quality":"high","response_format":"url"}</pre>
          <b>图生图 / 参考图</b><pre>POST /v1/images/edits
POST /v1/images/compositions</pre>
        </div>
      </section>
    </main>
  </div>
  <div id="accountModal" class="modal">
    <div class="modal-content">
      <div class="modal-head"><h2>新增 Codex 账号</h2><button class="ghost" onclick="closeModals()">关闭</button></div>
      <label>名称</label><input id="accountName" placeholder="Codex Plus / Pro">
      <label>Access Token</label><textarea id="accountToken" placeholder="粘贴 Codex / ChatGPT OAuth access_token"></textarea>
      <label>ChatGPT Account ID（可选）</label><input id="accountId" placeholder="账号头 Chatgpt-Account-Id，可留空">
      <button style="margin-top:16px" onclick="saveAccount()">保存账号</button>
    </div>
  </div>
  <div id="keyModal" class="modal">
    <div class="modal-content">
      <div class="modal-head"><h2>新增 API Key</h2><button class="ghost" onclick="closeModals()">关闭</button></div>
      <label>名称</label><input id="keyName" placeholder="newapi">
      <label>绑定账号</label><select id="keyAccount"><option value="">随机可用账号</option></select>
      <button style="margin-top:16px" onclick="saveKey()">生成 Key</button>
      <div id="newKeyBox" class="new-key hidden"></div>
    </div>
  </div>
  <div id="toast" class="toast"></div>
  <script>
    let setupComplete = false;
    let accounts = [];
    const $ = (id) => document.getElementById(id);
    async function api(path, options = {}) {
      const res = await fetch(path, { credentials: "include", headers: {"Content-Type":"application/json", ...(options.headers||{})}, ...options });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload.detail || payload.error || res.statusText);
      return payload;
    }
    function toast(msg) { const el = $("toast"); el.textContent = msg; el.classList.add("show"); setTimeout(() => el.classList.remove("show"), 2200); }
    async function init() {
      const status = await api("/dashboard/status");
      setupComplete = status.setupComplete;
      $("baseUrl").textContent = location.origin;
    }
    $("loginBtn").onclick = async () => {
      try {
        const username = $("username").value.trim();
        const password = $("password").value;
        if (!setupComplete) await api("/dashboard/setup", { method:"POST", body: JSON.stringify({username, password}) });
        await api("/dashboard/login", { method:"POST", body: JSON.stringify({username, password}) });
        $("auth").classList.add("hidden"); $("app").classList.remove("hidden");
        await refresh();
      } catch (e) { $("authMsg").textContent = e.message; }
    };
    async function logout(){ await api("/dashboard/logout", {method:"POST", body:"{}"}); location.reload(); }
    document.querySelectorAll(".tab").forEach(btn => btn.onclick = () => {
      document.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === btn));
      document.querySelectorAll(".panel").forEach(x => x.classList.toggle("active", x.id === btn.dataset.tab));
    });
    async function refresh() {
      const [stats, accountList, keys] = await Promise.all([api("/dashboard/stats"), api("/dashboard/accounts"), api("/dashboard/api-keys")]);
      accounts = accountList;
      $("statAccounts").textContent = stats.totals.accounts;
      $("statKeys").textContent = stats.totals.api_keys;
      $("statCalls").textContent = stats.totals.calls;
      $("statMedia").textContent = stats.totals.media;
      $("accountRows").innerHTML = accountList.map(a => `<tr><td>${a.name}</td><td><code>${a.token_preview}</code></td><td>${a.account_id || "-"}</td><td><span class="badge ${a.status}">${a.status}</span></td><td><button class="ghost" onclick="checkAccount(${a.id})">检查</button> <button class="danger" onclick="deleteAccount(${a.id})">删除</button></td></tr>`).join("");
      $("keyRows").innerHTML = keys.map(k => `<tr><td>${k.name}</td><td><code>${k.key_preview}</code></td><td>${k.account_name || "随机"}</td><td>${k.call_count}</td><td><span class="badge ${k.is_active ? "active" : "unknown"}">${k.is_active ? "active" : "disabled"}</span></td><td><button class="danger" onclick="deleteKey(${k.id})">删除</button></td></tr>`).join("");
      $("keyAccount").innerHTML = `<option value="">随机可用账号</option>` + accountList.map(a => `<option value="${a.id}">${a.name}</option>`).join("");
    }
    function openAccountModal(){ $("accountModal").classList.add("active"); }
    function openKeyModal(){ $("newKeyBox").classList.add("hidden"); $("keyModal").classList.add("active"); }
    function closeModals(){ document.querySelectorAll(".modal").forEach(m => m.classList.remove("active")); }
    async function saveAccount(){
      await api("/dashboard/accounts", {method:"POST", body: JSON.stringify({name:$("accountName").value, access_token:$("accountToken").value, account_id:$("accountId").value})});
      closeModals(); toast("账号已保存"); await refresh();
    }
    async function checkAccount(id){ const r = await api("/dashboard/accounts/check", {method:"POST", body: JSON.stringify({id})}); toast(r.success ? "账号可用" : "检查失败"); await refresh(); }
    async function deleteAccount(id){ await api(`/dashboard/accounts?id=${id}`, {method:"DELETE"}); toast("账号已删除"); await refresh(); }
    async function saveKey(){
      const r = await api("/dashboard/api-keys", {method:"POST", body: JSON.stringify({name:$("keyName").value, account_id:$("keyAccount").value})});
      $("newKeyBox").textContent = r.api_key; $("newKeyBox").classList.remove("hidden"); await refresh();
    }
    async function deleteKey(id){ await api(`/dashboard/api-keys?id=${id}`, {method:"DELETE"}); toast("Key 已删除"); await refresh(); }
    init().catch(e => $("authMsg").textContent = e.message);
  </script>
</body>
</html>"""

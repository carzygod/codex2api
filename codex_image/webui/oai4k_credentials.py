from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedOAI4KCredential:
    name: str
    access_token: str
    refresh_token: str = ""
    id_token: str = ""
    account_id: str = ""
    source_format: str = "plain"


def parse_oai4k_account_material(
    material: str,
    *,
    fallback_name: str = "",
    fallback_account_id: str = "",
    fallback_refresh_token: str = "",
) -> list[ParsedOAI4KCredential]:
    text = str(material or "").strip()
    if not text:
        raise ValueError("account material is required")

    parsed = _try_json(text)
    if parsed is None:
        return [
            _credential_from_values(
                source_format="plain",
                access_token=text,
                refresh_token=fallback_refresh_token,
                account_id=fallback_account_id,
                name=fallback_name,
            )
        ]

    raw_accounts = _expand_accounts(parsed)
    credentials: list[ParsedOAI4KCredential] = []
    for index, raw in enumerate(raw_accounts, start=1):
        credential = _credential_from_raw(raw, fallback_name=fallback_name, index=index)
        if fallback_account_id and not credential.account_id:
            credential = ParsedOAI4KCredential(
                name=credential.name,
                access_token=credential.access_token,
                refresh_token=credential.refresh_token,
                id_token=credential.id_token,
                account_id=fallback_account_id,
                source_format=credential.source_format,
            )
        if fallback_refresh_token and not credential.refresh_token:
            credential = ParsedOAI4KCredential(
                name=credential.name,
                access_token=credential.access_token,
                refresh_token=fallback_refresh_token,
                id_token=credential.id_token,
                account_id=credential.account_id,
                source_format=credential.source_format,
            )
        credentials.append(credential)

    deduped: list[ParsedOAI4KCredential] = []
    seen: set[tuple[str, str]] = set()
    for credential in credentials:
        key = (credential.access_token, credential.account_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(credential)
    if not deduped:
        raise ValueError("no supported Codex credentials found")
    return deduped


def _try_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _expand_accounts(value: Any) -> list[Any]:
    if isinstance(value, list):
        accounts: list[Any] = []
        for item in value:
            accounts.extend(_expand_accounts(item))
        return accounts
    if _is_obj(value) and isinstance(value.get("accounts"), list):
        return list(value["accounts"])
    if _is_recognized_account(value):
        return [value]
    nested = _collect_nested_accounts(value)
    return nested or [value]


def _collect_nested_accounts(value: Any) -> list[Any]:
    found: list[Any] = []
    visited: set[int] = set()

    def visit(item: Any) -> None:
        if not isinstance(item, (dict, list)):
            return
        item_id = id(item)
        if item_id in visited:
            return
        visited.add(item_id)
        if _is_recognized_account(item):
            found.append(item)
            return
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        for key, child in item.items():
            if key in {"access_token", "accessToken", "session_token", "sessionToken"}:
                continue
            visit(child)

    visit(value)
    return found


def _is_recognized_account(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if not _is_obj(value):
        return False
    if isinstance(value.get("accounts"), list):
        return True
    if _get_nested(value, "credentials", "access_token") or _get_nested(value, "credentials", "accessToken"):
        return True
    if _get_nested(value, "tokens", "access_token") or _get_nested(value, "tokens", "accessToken"):
        return True
    if _first(value.get("access_token"), value.get("accessToken"), value.get("token")):
        return True
    return False


def _credential_from_raw(raw: Any, *, fallback_name: str, index: int) -> ParsedOAI4KCredential:
    if isinstance(raw, str):
        return _credential_from_values(source_format="plain", access_token=raw, name=fallback_name)
    if not _is_obj(raw):
        raise ValueError("unsupported account item")

    source_format = _detect_format(raw)
    if source_format == "sub2api":
        credentials = _as_obj(raw.get("credentials"))
        extra = _as_obj(raw.get("extra"))
        access_token = _first(credentials.get("access_token"), credentials.get("accessToken"))
        refresh_token = _first(credentials.get("refresh_token"), credentials.get("refreshToken"), credentials.get("session_token"))
        id_token = _first(credentials.get("id_token"), credentials.get("idToken"))
        account_id = _first(
            credentials.get("chatgpt_account_id"),
            credentials.get("account_id"),
            _harvest_account_id(access_token),
        )
        name = _first(raw.get("name"), extra.get("name"), credentials.get("email"), extra.get("email"), fallback_name)
        return _credential_from_values(
            source_format=source_format,
            access_token=access_token,
            refresh_token=refresh_token,
            id_token=id_token,
            account_id=account_id,
            name=name,
            index=index,
        )

    tokens = _as_obj(raw.get("tokens"))
    token_obj = _as_obj(raw.get("token"))
    credentials = _as_obj(raw.get("credentials"))
    meta = _as_obj(raw.get("meta"))
    provider_data = _as_obj(raw.get("providerSpecificData"))
    user = _as_obj(raw.get("user"))
    account = _as_obj(raw.get("account"))

    access_token = _first(
        raw.get("access_token"),
        raw.get("accessToken"),
        raw.get("token"),
        tokens.get("access_token"),
        tokens.get("accessToken"),
        token_obj.get("access_token"),
        token_obj.get("accessToken"),
        credentials.get("access_token"),
        credentials.get("accessToken"),
    )
    refresh_token = _first(
        raw.get("refresh_token"),
        raw.get("refreshToken"),
        raw.get("session_token"),
        raw.get("sessionToken"),
        tokens.get("refresh_token"),
        tokens.get("refreshToken"),
        tokens.get("session_token"),
        tokens.get("sessionToken"),
        token_obj.get("refresh_token"),
        token_obj.get("refreshToken"),
        credentials.get("refresh_token"),
        credentials.get("refreshToken"),
        credentials.get("session_token"),
    )
    id_token = _first(
        raw.get("id_token"),
        raw.get("idToken"),
        tokens.get("id_token"),
        tokens.get("idToken"),
        token_obj.get("id_token"),
        token_obj.get("idToken"),
        credentials.get("id_token"),
        credentials.get("idToken"),
    )
    harvested = _harvest_account_id(access_token) or _harvest_account_id(id_token)
    account_id = _first(
        account.get("id"),
        raw.get("account_id"),
        raw.get("chatgpt_account_id"),
        raw.get("chatgptAccountId"),
        tokens.get("account_id"),
        tokens.get("accountId"),
        tokens.get("chatgpt_account_id"),
        tokens.get("chatgptAccountId"),
        meta.get("chatgpt_account_id"),
        meta.get("chatgptAccountId"),
        provider_data.get("chatgpt_account_id"),
        provider_data.get("chatgptAccountId"),
        credentials.get("account_id"),
        credentials.get("chatgpt_account_id"),
        harvested,
        raw.get("id") if raw.get("provider") == "codex" else "",
    )
    name = _first(
        raw.get("name"),
        raw.get("label"),
        raw.get("email"),
        user.get("email"),
        meta.get("label"),
        credentials.get("email"),
        provider_data.get("email"),
        fallback_name,
    )
    return _credential_from_values(
        source_format=source_format,
        access_token=access_token,
        refresh_token=refresh_token,
        id_token=id_token,
        account_id=account_id,
        name=name,
        index=index,
    )


def _credential_from_values(
    *,
    source_format: str,
    access_token: Any,
    refresh_token: Any = "",
    id_token: Any = "",
    account_id: Any = "",
    name: Any = "",
    index: int = 1,
) -> ParsedOAI4KCredential:
    token = str(access_token or "").strip()
    if not token:
        raise ValueError(f"{source_format} material is missing access_token")
    final_account_id = str(account_id or _harvest_account_id(token) or _harvest_account_id(str(id_token or "")) or "").strip()
    final_name = str(name or final_account_id or f"Codex Account {index}").strip()
    return ParsedOAI4KCredential(
        name=final_name,
        access_token=token,
        refresh_token=str(refresh_token or "").strip(),
        id_token=str(id_token or "").strip(),
        account_id=final_account_id,
        source_format=source_format,
    )


def _detect_format(value: dict[str, Any]) -> str:
    if isinstance(value.get("accounts"), list):
        return "sub2api"
    if _is_obj(value.get("credentials")) and _first(_get_nested(value, "credentials", "access_token"), _get_nested(value, "credentials", "accessToken")):
        return "sub2api"
    if value.get("type") == "codex" and isinstance(value.get("access_token"), str) and not _is_obj(value.get("tokens")):
        return "cpa"
    if value.get("auth_mode") == "chatgpt" and _is_obj(value.get("tokens")):
        return "auth.json"
    if _is_obj(value.get("tokens")) and _is_obj(value.get("meta")):
        return "codex-manager"
    if _is_obj(value.get("tokens")) and isinstance(_get_nested(value, "tokens", "access_token"), str):
        return "cockpit"
    if isinstance(value.get("accessToken"), str) and (_is_obj(value.get("providerSpecificData")) or value.get("provider") == "codex"):
        return "9router"
    if isinstance(value.get("accessToken"), str) and (_is_obj(value.get("user")) or _is_obj(value.get("account"))):
        return "chatgpt-session"
    if isinstance(value.get("access_token"), str):
        return "flat-access-token"
    if isinstance(value.get("accessToken"), str):
        return "camel-access-token"
    return "unknown-json"


def _harvest_account_id(token: Any) -> str:
    payload = _decode_jwt_payload(str(token or ""))
    auth = payload.get("https://api.openai.com/auth")
    if isinstance(auth, dict):
        return str(auth.get("chatgpt_account_id") or auth.get("account_id") or "")
    return str(payload.get("chatgpt_account_id") or payload.get("account_id") or "")


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode((payload + padding).encode("ascii"))
        decoded = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _is_obj(value: Any) -> bool:
    return isinstance(value, dict)


def _as_obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _get_nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""

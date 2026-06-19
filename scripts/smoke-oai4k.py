from __future__ import annotations

import tempfile
from io import BytesIO
from pathlib import Path
import sys
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from codex_image.client import ImageResult
from codex_image.webui import oai4k_api
from codex_image.webui.app import create_app


def png_bytes(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(124, 58, 237)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeImageClient:
    def __init__(self, width: int = 1024, height: int = 1024) -> None:
        self.width = width
        self.height = height

    def generate_images(self, **kwargs):
        count = int(kwargs.get("n") or 1)
        return [
            ImageResult(
                image_bytes=png_bytes(self.width, self.height),
                revised_prompt=kwargs.get("prompt", ""),
                output_format=kwargs.get("output_format", "png"),
                size=f"{self.width}x{self.height}",
                background=str(kwargs.get("background") or ""),
                quality=str(kwargs.get("quality") or ""),
                usage={},
            )
            for _ in range(count)
        ]

    def edit_images(self, **kwargs):
        return self.generate_images(**kwargs)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="oai4k-smoke-"))
    app = create_app(
        output_root=root / "outputs",
        input_root=root / "inputs",
        source_data_root=root / "outputs" / "source-data",
        auto_start_queue=False,
    )
    client = TestClient(app)

    assert client.get("/ping").status_code == 200

    models = client.get("/v1/models")
    assert models.status_code == 200
    model_ids = {item["id"] for item in models.json()["data"]}
    assert "gpt-image-2" in model_ids
    assert "oai-4k-gpt-image-2" in model_ids

    status = client.get("/dashboard/status")
    assert status.status_code == 200
    assert status.json()["setupComplete"] is False

    setup = client.post("/dashboard/setup", json={"username": "admin", "password": "secret1"})
    assert setup.status_code == 200

    login = client.post("/dashboard/login", json={"username": "admin", "password": "secret1"})
    assert login.status_code == 200
    cookies = login.cookies

    account = client.post(
        "/dashboard/accounts",
        cookies=cookies,
        json={"name": "test", "access_token": "test-access-token", "account_id": "acc-test"},
    )
    assert account.status_code == 200

    key = client.post("/dashboard/api-keys", cookies=cookies, json={"name": "newapi"})
    assert key.status_code == 200
    assert key.json()["api_key"].startswith("sk-oai4k-")
    api_key = key.json()["api_key"]

    invalid_size = client.post(
        "/v1/images/generations",
        headers={"Authorization": "Bearer test-access-token"},
        json={"model": "gpt-image-2", "prompt": "x", "size": "123x456"},
    )
    assert invalid_size.status_code == 400

    original_client_factory = oai4k_api._client_from_token
    try:
        oai4k_api._client_from_token = lambda token, account_id="": FakeImageClient()
        generated = client.post(
            "/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-image-2",
                "prompt": "a purple square",
                "size": "1024x1024",
                "response_format": "url",
            },
        )
        assert generated.status_code == 200, generated.text
        image_url = generated.json()["data"][0]["url"]
        assert image_url.startswith("http://testserver/api-media/")
        media_path = urlparse(image_url).path
        media = client.get(media_path)
        assert media.status_code == 200
        assert media.content.startswith(b"\x89PNG")

        mismatch = client.post(
            "/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-image-2",
                "prompt": "a purple square",
                "size": "2048x2048",
                "response_format": "url",
            },
        )
        assert mismatch.status_code == 502
        assert "size mismatch" in mismatch.text
    finally:
        oai4k_api._client_from_token = original_client_factory

    print("OAI-4K-01 smoke test passed")


if __name__ == "__main__":
    main()

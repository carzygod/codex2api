from __future__ import annotations

import tempfile
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from codex_image.webui.app import create_app


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

    invalid_size = client.post(
        "/v1/images/generations",
        headers={"Authorization": "Bearer test-access-token"},
        json={"model": "gpt-image-2", "prompt": "x", "size": "123x456"},
    )
    assert invalid_size.status_code == 400

    print("OAI-4K-01 smoke test passed")


if __name__ == "__main__":
    main()

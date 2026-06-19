# codex2api / OAI-4K-01

`codex2api` is a GPT-image-2 Web reverse proxy and management service based on `kadevin/ilab-gpt-conjure`.

It keeps the original local image WebUI and adds a managed OpenAI-compatible API layer:

- Use Codex / ChatGPT OAuth `access_token` values as upstream account credentials.
- Manage upstream accounts and local API keys from `/dashboard`.
- Import upstream accounts from raw `access_token`, CPA, Sub2API, Codex `auth.json`, and other common formats.
- Expose `/v1/models`, `/v1/images/generations`, and `/v1/images/edits`.
- Support `gpt-image-2` text-to-image, image-to-image, and reference image editing.
- Support native large image sizes, including `3840x2160` and `2160x3840`.
- Validate generated image size by default without manual crop, resize, padding, or post-processing.

> This project is not the official OpenAI API and is not an official production integration path. It depends on ChatGPT / Codex Web OAuth state and internal image endpoints, which may change or become unavailable.

## Capabilities

| Feature | Status | Notes |
| --- | --- | --- |
| WebUI workbench | Supported | Original generation, gallery, history, and queue features are preserved |
| Admin dashboard | Supported | `/dashboard` manages users, upstream accounts, API keys, media records, and logs |
| OpenAI-compatible model list | Supported | `GET /v1/models` |
| Text-to-image | Supported | `POST /v1/images/generations` |
| Image edit / image-to-image | Supported | `POST /v1/images/edits` |
| Reference composition | Supported | `POST /v1/images/compositions` |
| Multiple API keys | Supported | Keys can be created, disabled, and deleted in the dashboard |
| Upstream account pool | Supported | Keys can bind to one account; unbound keys use a random available account |
| Multi-format account import | Supported | Raw token, CPA, Sub2API, auth.json, Codex-Manager, Cockpit, 9router, ChatGPT session |
| Video generation | Not supported | `/v1/video/generations` returns `video_not_supported` |
| Redis | Not required | Management data is stored in SQLite |

## Authentication

Strictly counted as Codex login methods, this project supports **one** Codex login method:

| Scope | Count | Description |
| --- | ---: | --- |
| Codex login method | 1 | Reuse a Codex / ChatGPT OAuth `access_token` |
| Codex backend modes | 2 | The original WebUI can use `images` or `responses`; these are not separate logins |
| Public API authentication | 1 | Local `sk-oai4k-...` API keys |

The upstream project reads the local `~/.codex/auth.json` by default. This fork adds a dashboard account pool so you can paste compatible OAuth `access_token` values and expose them through local API keys.

This project does not support QR login, ChatGPT username/password login, browser cookie import, OAuth URL generation, or official OpenAI API keys as upstream account material.

## Models

`GET /v1/models` currently returns:

| Model ID | Upstream model | Type | Notes |
| --- | --- | --- | --- |
| `gpt-image-2-4k` | `gpt-image-2` | image | Recommended public 4K model |
| `oai-4k-gpt-image-2-4k` | `gpt-image-2` | image | Project alias |

The API also accepts these aliases and normalizes them to `gpt-image-2`:

- `oai-4k-gpt-image-2-4k`
- `gpt-image-2-4k`
- `oai-4k-gpt-image-2`
- `codex-gpt-image-2-4k`
- `codex-gpt-image-2`
- `pro-codex-gpt-image-2-4k`
- `pro-codex-gpt-image-2`

## Supported Sizes

Only known native GPT-image-2 sizes are accepted. Strict size validation is enabled by default. If the upstream response does not match the requested size, this service returns an error and does not crop, resize, or pad the image.

```text
1024x1024
1536x864
864x1536
2048x2048
2048x1152
1152x2048
2880x2880
2560x3200
3200x2560
2448x3264
3264x2448
2336x3504
3504x2336
2160x3840
3840x2160
1632x3808
3808x1632
```

Disable strict validation if needed:

```bash
export OAI4K_STRICT_SIZE=0
```

This only disables inspection; it still does not perform manual image edits.

## Quick Start

```bash
git clone git@github.com:carzygod/codex2api.git
cd codex2api

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-webui.txt
```

Start the service:

```bash
OAI4K_OUTPUT_ROOT=output/webui-outputs \
OAI4K_SOURCE_DATA_ROOT=output/webui-outputs/source-data \
python -m uvicorn codex_image.webui.app:app --host 0.0.0.0 --port 18788 --no-access-log
```

Open:

```text
http://127.0.0.1:18788/dashboard
```

Create the admin account on first visit. Then add upstream Codex / ChatGPT OAuth `access_token` values and create local API keys.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `OAI4K_OUTPUT_ROOT` | `output/webui-outputs` | WebUI output, generated media, and task files |
| `OAI4K_SOURCE_DATA_ROOT` | `output/webui-outputs/source-data` | WebUI source-data directory |
| `OAI4K_CODEX_IMAGES_BASE_URL` | `https://chatgpt.com/backend-api/codex` | Codex images backend URL |
| `OAI4K_INLINE_AUTH_PATH` | `output/oai4k-inline-auth.json` | Temporary AuthState path used to build the client |
| `OAI4K_STRICT_SIZE` | `1` | Whether to validate returned image dimensions |
| `CODEX_IMAGE_REQUEST_TIMEOUT_SECONDS` | `600` | Upstream request timeout |
| `ILAB_CONJURE_DATA_DIR` | empty | Portable WebUI compatibility setting |
| `ILAB_CONJURE_BUNDLE_DIR` | empty | Portable WebUI compatibility setting |

SQLite management data is stored in:

```text
output/oai4k.db
```

## API Examples

Health check:

```bash
curl http://127.0.0.1:18788/ping
```

Models:

```bash
curl http://127.0.0.1:18788/v1/models \
  -H "Authorization: Bearer sk-oai4k-your-key"
```

Text-to-image:

```bash
curl http://127.0.0.1:18788/v1/images/generations \
  -H "Authorization: Bearer sk-oai4k-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2-4k",
    "prompt": "A cute cat sitting on a glass desk, cinematic studio light",
    "size": "1024x1024",
    "quality": "low",
    "output_format": "png",
    "response_format": "url",
    "n": 1
  }'
```

Image edit:

```bash
curl http://127.0.0.1:18788/v1/images/edits \
  -H "Authorization: Bearer sk-oai4k-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2-4k",
    "prompt": "Keep the character, change the background to a neon street",
    "size": "1536x864",
    "images": ["https://example.com/input.png"]
  }'
```

Multipart image edit:

```bash
curl http://127.0.0.1:18788/v1/images/edits \
  -H "Authorization: Bearer sk-oai4k-your-key" \
  -F "model=gpt-image-2-4k" \
  -F "prompt=Make it look like a premium poster" \
  -F "size=1536x864" \
  -F "image=@input.png"
```

## new-api Integration

Add it as an OpenAI-compatible channel:

| Field | Value |
| --- | --- |
| Base URL | `http://your-server-ip:18788/v1` |
| API Key | A dashboard-created `sk-oai4k-...` key |
| Models | `gpt-image-2-4k`, `oai-4k-gpt-image-2-4k` |
| Type | Image model / OpenAI-compatible |

Notes:

- No video models are exposed.
- Only image APIs are supported.
- To use 4K sizes, the intermediary must pass through `size`.
- The intermediary must accept either `url` or `b64_json` image responses.

## Dashboard Flow

1. Open `/dashboard`.
2. Initialize the admin user.
3. Import Codex / ChatGPT OAuth account material.
4. Optionally fill `account_id` as a fallback when the material does not include one; it is sent as `Chatgpt-Account-Id`.
5. Create an API key.
6. Use the `sk-oai4k-...` key with `/v1/images/generations` or new-api.

The account check currently validates that request material can be built. A real image generation call remains the final availability test.

## Original WebUI

The original workbench is still available:

```text
http://127.0.0.1:18788/
http://127.0.0.1:18788/history
```

## Development

```bash
python -m compileall codex_image
npm run check:webui
python -m unittest discover -s tests -v
```

When changing frontend TypeScript or CSS, commit generated assets under:

```text
codex_image/webui/static/
```

## Security

- This is a Web reverse proxy, not an official API.
- Upstream OAuth state can fail due to risk control, quota, region, or account changes.
- Use a strong dashboard password and issue API keys only to trusted clients.
- Do not publicly expose `/dashboard` without additional access control.
- Treat `output/oai4k.db` as a secret file.

## License

This project inherits the GNU AGPLv3 license from `kadevin/ilab-gpt-conjure`. See [LICENSE](LICENSE).

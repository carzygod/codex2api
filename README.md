# codex2api / OAI-4K-01

`codex2api` 是基于 `kadevin/ilab-gpt-conjure` 改造的 GPT-image-2 Web 反代与管理服务。

它保留了原仓库的本地图片生成 WebUI，并新增了一层可管理的 OpenAI-compatible API：

- 使用 Codex / ChatGPT OAuth `access_token` 作为上游账号材料。
- 在 `/dashboard` 管理上游账号池和本服务 API Key。
- 上游账号导入支持裸 `access_token`、CPA、Sub2API、Codex `auth.json` 等多种材料格式。
- 对外暴露 `/v1/models`、`/v1/images/generations`、`/v1/images/edits`。
- 支持 `gpt-image-2` 的文生图、图生图、参考图编辑。
- 支持原生大尺寸请求，包括 `3840x2160` 和 `2160x3840`。
- 默认强校验返回图片尺寸，不做手动裁剪、缩放或补边。

> 本项目不是 OpenAI 官方 API，也不是官方推荐的生产集成方式。它依赖 ChatGPT / Codex Web OAuth 登录态和内部图片接口，接口、风控和额度策略都可能变化。

## 当前能力

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| WebUI 工作台 | 支持 | 原仓库的图片生成、图库、历史、队列等功能仍保留 |
| 管理后台 | 支持 | `/dashboard`，管理平台用户、上游账号、API Key、调用记录 |
| OpenAI-compatible 模型列表 | 支持 | `GET /v1/models` |
| 文生图 | 支持 | `POST /v1/images/generations` |
| 图生图 / 图片编辑 | 支持 | `POST /v1/images/edits` |
| 参考图组合 | 支持 | `POST /v1/images/compositions` |
| 多 API Key | 支持 | 可在 dashboard 创建、停用、删除 |
| 上游账号池 | 支持 | API Key 可绑定指定账号；未绑定时随机选择可用账号 |
| 多格式账号导入 | 支持 | 裸 token、CPA、Sub2API、auth.json、Codex-Manager、Cockpit、9router、ChatGPT session |
| 视频生成 | 不支持 | `/v1/video/generations` 会返回 `video_not_supported` |
| Redis | 不需要 | 本项目使用 SQLite 保存管理数据 |

## 登录与认证方式

严格按 Codex 登录方式计算，项目只支持 **1 种 Codex 登录方式**：

| 类型 | 数量 | 说明 |
| --- | ---: | --- |
| Codex 登录方式 | 1 | 复用 Codex / ChatGPT OAuth 登录态中的 `access_token` |
| Codex 调用模式 | 2 | 原 WebUI 可选 `images` / `responses`，不是两种登录 |
| 对外 API 认证 | 1 | 本服务生成的 `sk-oai4k-...` API Key |

原仓库默认读取本机 `~/.codex/auth.json`。本 fork 的 `/dashboard` 额外提供账号池管理，你可以把同类 OAuth `access_token` 填入后台，由本服务对外转换成 API Key。

本项目不支持：

- 二维码登录。
- 账号密码登录 ChatGPT。
- 浏览器 Cookie 导入。
- 自动生成 Codex OAuth 登录 URL。
- 官方 OpenAI API Key 作为上游账号材料。

## 支持模型

`GET /v1/models` 当前返回：

| 模型 ID | 实际上游模型 | 类型 | 说明 |
| --- | --- | --- | --- |
| `gpt-image-2-4k` | `gpt-image-2` | image | 推荐对外使用 |
| `oai-4k-gpt-image-2-4k` | `gpt-image-2` | image | 本项目别名 |

请求中也接受以下别名，并会归一化为 `gpt-image-2`：

- `oai-4k-gpt-image-2-4k`
- `gpt-image-2-4k`
- `oai-4k-gpt-image-2`
- `codex-gpt-image-2-4k`
- `codex-gpt-image-2`
- `pro-codex-gpt-image-2-4k`
- `pro-codex-gpt-image-2`

## 支持尺寸

接口只接受已知的 GPT-image-2 原生尺寸。默认开启严格尺寸校验：如果上游返回尺寸与请求尺寸不一致，本服务会返回错误，不会做任何手动裁剪或缩放。

支持尺寸：

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

如需关闭严格校验，可设置：

```bash
export OAI4K_STRICT_SIZE=0
```

关闭后服务不会检查实际图片尺寸，但仍不会裁剪、缩放或补边。

## 快速启动

### 1. 安装依赖

```bash
git clone git@github.com:carzygod/codex2api.git
cd codex2api

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-webui.txt
```

项目代码已兼容 Python 3.10+。生产环境建议使用 Python 3.10 或更新版本。

### 2. 启动服务

```bash
OAI4K_OUTPUT_ROOT=output/webui-outputs \
OAI4K_SOURCE_DATA_ROOT=output/webui-outputs/source-data \
python -m uvicorn codex_image.webui.app:app --host 0.0.0.0 --port 18788 --no-access-log
```

启动后访问：

```text
http://127.0.0.1:18788/dashboard
```

首次访问 dashboard 时创建管理员账号。之后在后台添加上游 Codex / ChatGPT OAuth `access_token`，再创建对外使用的 API Key。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OAI4K_OUTPUT_ROOT` | `output/webui-outputs` | WebUI 输出、生成媒体、任务文件目录 |
| `OAI4K_SOURCE_DATA_ROOT` | `output/webui-outputs/source-data` | WebUI 源数据目录 |
| `OAI4K_CODEX_IMAGES_BASE_URL` | `https://chatgpt.com/backend-api/codex` | Codex images 后端地址 |
| `OAI4K_INLINE_AUTH_PATH` | `output/oai4k-inline-auth.json` | 临时 AuthState 路径，仅用于构造客户端对象 |
| `OAI4K_STRICT_SIZE` | `1` | 是否强校验实际返回尺寸 |
| `CODEX_IMAGE_REQUEST_TIMEOUT_SECONDS` | `600` | 上游请求超时时间 |
| `ILAB_CONJURE_DATA_DIR` | 空 | 上游 WebUI portable 数据目录兼容项 |
| `ILAB_CONJURE_BUNDLE_DIR` | 空 | 上游 WebUI portable 包目录兼容项 |

SQLite 管理库默认位于：

```text
output/oai4k.db
```

其中保存 dashboard 用户、上游账号、API Key、媒体记录和日志。

## API 使用

### 健康检查

```bash
curl http://127.0.0.1:18788/ping
```

### 模型列表

```bash
curl http://127.0.0.1:18788/v1/models \
  -H "Authorization: Bearer sk-oai4k-your-key"
```

### 文生图

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

返回结构：

```json
{
  "created": 1780000000,
  "data": [
    {
      "url": "http://127.0.0.1:18788/api-media/example.png",
      "revised_prompt": "...",
      "size": "1024x1024"
    }
  ]
}
```

### 返回 base64

```bash
curl http://127.0.0.1:18788/v1/images/generations \
  -H "Authorization: Bearer sk-oai4k-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2-4k",
    "prompt": "A clean 4K product render of a white cube",
    "size": "3840x2160",
    "response_format": "b64_json"
  }'
```

### 图生图 / 图片编辑

JSON 方式：

```bash
curl http://127.0.0.1:18788/v1/images/edits \
  -H "Authorization: Bearer sk-oai4k-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2-4k",
    "prompt": "Keep the character, change the background to a neon street",
    "size": "1536x864",
    "images": [
      "https://example.com/input.png"
    ]
  }'
```

Multipart 方式：

```bash
curl http://127.0.0.1:18788/v1/images/edits \
  -H "Authorization: Bearer sk-oai4k-your-key" \
  -F "model=gpt-image-2-4k" \
  -F "prompt=Make it look like a premium poster" \
  -F "size=1536x864" \
  -F "image=@input.png"
```

### 图文参考生图

图文参考生图必须走编辑/组合接口，不走纯文生图接口：

```text
POST /v1/images/edits
POST /v1/images/compositions
```

`POST /v1/images/generations` 只用于纯文生图，不读取参考图字段。

JSON 请求支持以下参考图字段，字段值可以是图片 URL、`data:image/...;base64,...`，或 OpenAI 风格对象 `{"url":"..."}` / `{"image_url":{"url":"..."}}`：

```text
image
images
input_image
input_images
reference_images
file_paths
filePaths
```

Multipart 请求支持 OpenAI 风格的 `image` / `images` 文件字段，`mask` 可选：

```bash
curl http://127.0.0.1:18788/v1/images/edits \
  -H "Authorization: Bearer sk-oai4k-your-key" \
  -F "model=gpt-image-2-4k" \
  -F "prompt=参考这张图生成一张 4K 电影海报，保持主体一致" \
  -F "size=3840x2160" \
  -F "image=@reference.png"
```

## new-api 接入建议

在 new-api 中作为 OpenAI-compatible 渠道添加：

| 字段 | 填写 |
| --- | --- |
| Base URL | `http://你的服务器IP:18788/v1` |
| API Key | dashboard 中创建的 `sk-oai4k-...` |
| 模型 | `gpt-image-2-4k`、`oai-4k-gpt-image-2-4k` |
| 类型 | 图片模型 / OpenAI-compatible |

注意：

- 本项目不提供视频模型。
- 只支持图片相关接口。
- 如果 new-api 的图片接口不透传 `size`，则无法利用 4K 尺寸能力。
- 如果 new-api 对图片响应结构有额外假设，需要确保它兼容 `url` 或 `b64_json` 两种返回格式。

## Dashboard 操作流

1. 打开 `/dashboard`。
2. 首次初始化管理员账号。
3. 在“上游账号”中导入 Codex / ChatGPT OAuth 账号材料。
4. 可选填写 `account_id`，用于材料缺少账号 ID 时作为兜底，并最终传递 `Chatgpt-Account-Id` 请求头。
5. 点击账号检查，确认账号材料格式可构造请求。
6. 在“API Keys”中创建对外 API Key。
7. 用 `sk-oai4k-...` 调用 `/v1/images/generations` 或接入 new-api。

账号检查当前主要验证客户端请求材料是否可构造；最终可用性仍以真实生图请求成功为准。

## 导入上游账号材料

本服务最终需要的是 Codex / ChatGPT OAuth `access_token`。Dashboard 的“导入 Codex 账号”支持直接粘贴多种常见材料格式，并会归一化保存为 `access_token / refresh_token / account_id`：

| 格式 | 是否支持 | 说明 |
| --- | --- | --- |
| 裸 `access_token` | 支持 | 直接粘贴 token 字符串 |
| Codex `auth.json` | 支持 | `tokens.access_token`、`tokens.refresh_token`、`tokens.account_id` |
| CPA | 支持 | `type=codex` 平铺结构，读取 `access_token`、`refresh_token`、`account_id` |
| Sub2API | 支持 | 读取 `accounts[].credentials.access_token`，可一次导入多账号 |
| Codex-Manager | 支持 | 读取 `tokens + meta` 双块结构 |
| Cockpit | 支持 | 读取 `tokens.access_token` 和外层账号信息 |
| 9router | 支持 | 读取 `accessToken + providerSpecificData` |
| ChatGPT session JSON | 支持 | 读取 `accessToken`、`user`、`account` |

Codex `auth.json` 的常见来源是本机 Codex 登录态：

```text
~/.codex/auth.json
```

该文件中通常包含：

```json
{
  "tokens": {
    "access_token": "...",
    "refresh_token": "...",
    "id_token": "..."
  }
}
```

CPA 示例：

```json
{
  "type": "codex",
  "name": "Codex Plus",
  "access_token": "eyJ...",
  "refresh_token": "",
  "account_id": "acc_..."
}
```

Sub2API 示例：

```json
{
  "accounts": [
    {
      "name": "Codex Plus",
      "credentials": {
        "access_token": "eyJ...",
        "refresh_token": "",
        "chatgpt_account_id": "acc_..."
      }
    }
  ]
}
```

如果材料里没有账号 ID，但你知道对应的 ChatGPT account id，可以在 dashboard 的 `ChatGPT Account ID` 兜底字段里填写。

不要把 `auth.json`、`access_token`、API Key、SQLite 数据库或生成结果提交到 Git。

## 原 WebUI

除新增的 `/dashboard` 和 `/v1` API 外，原始图片工作台仍可访问：

```text
http://127.0.0.1:18788/
http://127.0.0.1:18788/history
```

原 WebUI 支持：

- 文生图、参考图生成、图片编辑。
- 本地图库、最近上传、公用图片库。
- 提示词片段、颜色 chip、模板库。
- 队列、历史、归档、重试、下载。
- `API` / `Codex` 两类认证来源切换。

## 开发与验证

```bash
python -m compileall codex_image
npm run check:webui
python -m unittest discover -s tests -v
```

修改前端 TypeScript 或 CSS 后，需要提交生成后的静态资源：

```text
codex_image/webui/static/
```

## 安全边界

- 这是 Web 反代方案，不是官方 API。
- 上游 Codex / ChatGPT OAuth 可能因风控、额度、地区、账号状态失效。
- 对外暴露服务时必须设置强 dashboard 密码，并只向可信调用方发放 API Key。
- 不建议把 `/dashboard` 直接暴露到公网；如必须暴露，请至少叠加防火墙、反向代理访问控制或 VPN。
- SQLite 数据库中包含敏感账号材料，备份和迁移时必须按密钥文件处理。

## License

本项目继承上游 `kadevin/ilab-gpt-conjure` 的 GNU AGPLv3 协议。详见 [LICENSE](LICENSE)。

如果你修改本软件并通过网络向用户提供服务，需要按 AGPLv3 要求开放对应源代码。

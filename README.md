# Text Selection Translation — Python edition

A native macOS menu bar application written in Python, with a local FastAPI backend. It uses its own configuration, notes, and Keychain namespace, separate from the original Swift edition.

New to Python or FastAPI? Read the [complete beginner's guide](docs/BEGINNERS_GUIDE.md): start in an empty folder, build two small working APIs, assemble the real app module by module, and package it for macOS. The accompanying `tutorial/` examples include a mock-provider server that needs no API key.

## Local development checkout

The local Python checkout has moved from the Swift repository's `python-app/` folder to the sibling directory `~/github/mac-text-selection-translation-python`. Continue Python development from this independent repository; its existing Git history is preserved.

```sh
cd "$HOME/github/mac-text-selection-translation-python"
make setup
make check
make test
make run
```

## Run

Requirements: macOS 14+, Python 3.12, and [uv](https://docs.astral.sh/uv/). The checked-in `uv.lock` pins development and runtime dependencies.

Clone this repository, then run from its root:

```sh
git clone https://github.com/jinyu-cai/mac-text-selection-translation-python.git
cd mac-text-selection-translation-python
make setup
make run
```

The menu bar uses a compact monochrome **Aa** icon (with **T** as a fallback). Open **Settings… → Translation & Speech**, add a translation provider, enter its endpoint, model, and optional API key, then save. **Save & Test Connection** saves that configuration and sends a test request; speech providers show **Save & Preview Voice**. Only fields relevant to the selected provider type are shown. A local OpenAI-compatible provider can have an empty key.

### Google AI Studio / Gemini

1. Create an API key in [Google AI Studio](https://aistudio.google.com/api-keys).
2. Open **Settings… → Translation & Speech → Add Google AI Studio**. This adds a separate provider with the official `https://generativelanguage.googleapis.com/v1beta/openai` endpoint and `gemini-3.8-flash` preset. The model field remains editable to match models available to your account.
3. Paste the key with **⌘V** or the **Paste** button next to API Key, then click **Save & Test Connection**.

The integration uses Google's documented [OpenAI-compatible Gemini API](https://ai.google.dev/gemini-api/docs/openai), including streaming translation. Leave **Reasoning** at **auto** to use the model default; support for other levels varies by model. This preset is for text translation, not Gemini audio generation. Availability and quota depend on your Google API project.

All text fields support standard macOS editing shortcuts. API keys remain masked and are saved in Keychain; the paste button trims surrounding whitespace. Leaving a saved key blank keeps it; **Clear Key** explicitly removes it.

The desktop starts FastAPI automatically on an ephemeral loopback port. There is no separate server command, fixed port, browser interface, or account setup.

The interface, menus, and app-generated errors are in English. The app icon uses a Latin **T**, and menu-bar/floating controls use **Aa**. Interface language does not change saved translation targets, provider names, or notes.

### OpenAI reasoning models

GPT-6 Luna and Sol omit sampling parameters when reasoning is Auto or enabled. With reasoning Off, they send `reasoning_effort: "none"` and may use a custom temperature. This avoids OpenAI HTTP 400 errors for unsupported temperature settings. Connection testing and streaming share this policy; rejected parameters are reported without exposing upstream messages or credentials.

## Features and controls

- **Selected text:** press `⌥D`, or select text and click the floating **Aa** button. Capture uses Accessibility first, then simulated Copy with conditional clipboard restoration.
- **Screenshot OCR:** press `⌥⇧O` or choose **Screenshot Translation…**. Drag a rectangle on a display; Esc cancels. ScreenCaptureKit captures the region and Vision recognizes its text locally.
- **Translation:** enabled translation providers run concurrently. Results stream into the popup in provider order. The popup matches the original Swift layout: a 360-point rounded panel, source text with its own speech button, and separate result cards with speech/copy controls. Drag the header to move it; Esc, Close, or clicking outside dismisses it and cancels requests. It grows with streaming content up to 460 points, then scrolls. Drag the bottom-right handle to resize; the chosen size is remembered. Text is selectable; Markdown tables use native grid cells.
- **Prompts:** the existing three-function translation/dictionary template and model-specific request policies are retained. A custom prompt replaces the output policy while retaining the source-text safety boundary.
- **Speech:** click the speech icon beside the source or the desired result card. Native speech uses a speaker icon; configured cloud TTS uses a waveform and shows a spinner during preparation. With no enabled TTS provider, macOS speech is used. One TTS provider is called directly; multiple providers open a menu that also offers macOS speech. OpenAI-compatible and DashScope backends support voice, audio format, and style settings.
- **Notes:** enable **Enable local notes** in General settings. The note icon in the popup header saves the first usable completed translation in configured provider order. Notes support reading, copying, deletion, and annotations that save after 500 ms and flush when switching, closing, or quitting.
- **Settings:** translation and OCR hotkeys are independently configurable. Click their buttons to record; Esc cancels recording. Provider **Up / Down** controls persist ordering. API-key fields are masked; leave a saved key blank to keep it, or check **Clear Key** to remove it.
- **Launch at login:** available through ServiceManagement in the packaged app. macOS may require approval in Login Items settings.
- **Experimental dictionary:** `make beta-run` enables Microsoft dictionary configuration. Normal launches reject enabled dictionary settings and do not send dictionary requests, even if an experimental launch previously saved them. The experimental command uses the Python edition's data store.

Accessibility and Screen Recording permissions are granted to this Python application separately from the Swift app. Run the packaged app for stable permission identity, and restart it after granting permissions. If the Swift app is running with the same shortcuts, quit one app or assign different shortcuts.

## Package

```sh
make app
make sign
open "dist/Text Selection Translation Python.app"
```

The app icon is generated from native vector drawing in `packaging/generate_icon.py`; run it to regenerate `packaging/Translator.icns`.

The bundle includes Python and its dependencies; end users do not need Python or uv. Copy it to Applications for everyday use and launch-at-login support. Build output is architecture-specific: build on Apple Silicon for arm64 and on an Intel Mac for x86_64. The current local build was verified on arm64.

`make sign` defaults to ad-hoc signing when no identity is supplied. Use a stable signing certificate to retain permission identity across rebuilds. Distribution signing/notarization is separate from this local development build.

py2app 0.28.10 assumes zlib is a separate extension. uv's standalone Python includes zlib in libpython. `packaging/setup.py` supplies a small subclass that skips only the nonexistent extension copy; the Python shared library is still bundled normally. Packaging runs from its own directory to avoid py2app interpreting project dependencies as obsolete `install_requires`.

## Architecture

```text
AppKit main thread                 Background asyncio thread
menu, popup, settings, notes  ─HTTP─► FastAPI / Uvicorn
Carbon hotkeys                      provider clients (HTTPX)
Accessibility / clipboard          parallel translation + SSE
ScreenCaptureKit + Vision          cloud TTS / dictionary
speech playback / login items      SQLite + macOS Keychain
```

The desktop HTTP client shares the worker loop but always talks through the API. AppKit work is marshalled to the main thread. OCR recognition runs in a worker thread. A bounded streaming queue provides backpressure, and disconnects cancel all associated upstream provider tasks. New translations have new IDs; late UI events cannot update a newer popup.

Data paths:

- SQLite: `~/Library/Application Support/Text Selection Translation Python/translator.sqlite3`
- App bundle identifier: `com.example.mactranslator.python`
- Keychain service: `com.example.mactranslator.python.credentials.v1`

The API requires a random in-memory bearer token created each launch. It listens only on `127.0.0.1`; browser-origin requests are rejected, CORS is not enabled, and public API documentation endpoints are disabled. Keys are write-only and excluded from settings serialization. Request validation and provider error messages do not echo request input, credentials, URLs, or upstream response bodies. Keychain reads are noninteractive; inaccessible keys produce a re-entry message rather than login-time password dialogs.

### API contract

All paths are prefixed with `/api/v1`. Contracts are defined in `src/mactranslator/contracts.py`.

| Method and path | Request / response |
|---|---|
| `GET /health` | Readiness and experimental dictionary flag |
| `GET /settings` | Preferences and ordered provider metadata; no keys |
| `PUT /settings` | Full settings replacement; optional provider `api_key` writes or clears a key |
| `POST /translate` | `{text, request_id?}` → SSE |
| `POST /providers/{id}/test` | Translation/dictionary connection check |
| `POST /speech` | `{provider_id, text, language?}` → audio bytes |
| `GET /notes` | Notes, newest first |
| `POST /notes` | `{source_text, translated_text?, backend_name?, user_note?}` → created note |
| `GET /notes/{id}` | A single note |
| `PATCH /notes/{id}` | `{user_note}` → updated note |
| `DELETE /notes/{id}` | Delete a note, returning 204 |

Provider kinds: `translation`, `openai_tts`, `dashscope_tts`, and experimental `dictionary`. Provider UUIDs remain stable across edits and reorder operations.

SSE frames contain JSON with `type`, `request_id`, and, where applicable, `provider_id`. The sequence starts with `start` (ordered provider metadata), interleaves `delta` and `dictionary` events, records each provider's `provider_done` or `provider_error`, and finishes with `done`. Idle streams send comment heartbeats. A provider failure does not terminate other providers. Closing the response cancels work; streams are not resumable. Eligible network failures retry once only before any translated content has been emitted.

## Validation

```sh
make check
make test

# Native and packaged smoke checks: synthetic content and temporary database.
.venv/bin/python -m mactranslator.desktop.app --smoke-test /tmp/translator-native-check
"dist/Text Selection Translation Python.app/Contents/MacOS/Text Selection Translation Python" \
  --smoke-test /tmp/translator-bundle-check
```

The smoke check verifies per-card speech/copy routing, long-output scrolling, automatic height limits, manual sizing, AI speech state, and notices; it constructs all native windows, renders sample content, verifies ⌘A/⌘V in ordinary and secure fields plus the API-key paste button, recognizes a generated image with Vision, registers/releases a temporary test hotkey, and starts/stops the authenticated loopback service. Paste checks temporarily use synthetic clipboard text and restore the original contents unless a newer copy has occurred. It does not use real provider credentials, capture the screen, or alter login registration. Output contains `report.json` and diagnostic view renders. Modern layer-backed controls may be absent from the offscreen renders; use the live application for final visual QA.

Verified during implementation:

- 55 automated tests: policy parity, fragmented Unicode SSE, concurrency, independent failures, cancellation, retry limits, credential redaction, unavailable credentials, settings/notes persistence, dictionary gating, TTS payloads, PCM playback wrapping, loopback lifecycle, stale popup events, note autosave races, and mocked Google AI Studio connection/streaming requests.
- Native and standalone-bundle smoke checks passed, including generated-image OCR and hotkey registration.
- Ruff, bytecode compilation, and bundle signature verification passed.

Manual acceptance still required with your macOS permissions and provider configuration:

1. Grant Accessibility and Screen Recording to the packaged Python app; restart it.
2. Verify selection and floating-button focus in a browser, a PDF reader, and an editor. Check Copy fallback and that a later user copy is preserved.
3. Verify hotkey recording, multi-display popup placement, dragging, dismissal, and cancellation during a slow translation.
4. Verify screenshot selection and OCR on Retina and external displays, including permission denial and cancellation.
5. Use configured providers to verify live translation, both cloud TTS protocols, native speech, and experimental dictionary lookup.
6. Edit notes rapidly, switch notes, close the window, and quit/relaunch to verify persistence.
7. Enable/disable launch at login in the packaged app and verify a real login cycle.

The computer-use verification step timed out during implementation, so these interactive checks are not claimed as completed.

### Gemini CLI（旧版接入）

若出现 `This client is no longer supported`，请使用下方 Antigravity CLI 接入。

设置 → **Translation & Speech** → **Add Gemini CLI** 可添加独立的 CLI 翻译服务。
它通过本机 `gemini` 的非交互流式输出翻译，不需要在本应用填写 API Key。

1. 按 [Gemini CLI 安装说明](https://geminicli.com/docs/get-started/installation/)安装最新版（需要 Node.js）：
   ```bash
   npm install -g @google/gemini-cli
   gemini
   ```
2. 在终端选择 **Sign in with Google**，登录享有学生优惠 / Google AI Pro 权益的账号，完成一次正常对话。
3. 添加 Gemini CLI 服务；**Model** 默认为 `auto`（使用 CLI 默认模型），也可填该账号在 CLI 中可用的模型 ID。
4. **CLI Path** 默认为 `gemini`。如果从 Finder 打开应用后找不到命令，在终端运行 `command -v gemini`，将完整路径填入此处。使用 nvm 等 Node 版本管理器时也建议填写完整路径。
5. 点击 **Save & Test Connection**，成功后即可划词或截图翻译；可以与现有 API 服务并行显示。

Google AI Pro / Ultra 用户应登录绑定订阅的 Google 账号；headless 模式可复用已缓存的登录。
学生优惠实际包含的模型、地区限制、有效期和额度由 Google 决定，并非无限调用，也不等同于 AI Studio API 额度。
参见 [官方认证说明](https://geminicli.com/docs/get-started/authentication/)与
[额度说明](https://geminicli.com/docs/resources/quota-and-pricing/)。连接测试也会消耗一次请求额度。

本接入显式选择 Google OAuth，不使用本应用保存的 API Key；关闭自动使用额外 AI credits。
CLI 在临时工作目录中运行，使用仅对该进程生效的设置关闭工具、MCP、扩展和 hooks，不改写用户的 CLI 设置。
原文通过标准输入发送，结果按流式事件展示；取消翻译会停止 CLI 进程，单次请求超时为 150 秒。
CLI 自身可能在 `~/.gemini` 下保存会话记录，请按其隐私与历史记录设置管理。
如果提示失败，请先在终端检查 Google 登录、模型权限和额度，并更新 CLI；本应用不会展示可能含原文或凭据的原始 CLI 错误输出。


### Antigravity CLI（Google 账号登录，推荐）

Gemini CLI 的个人登录入口已出现要求迁移 Antigravity 的服务端提示。
本应用新增 `antigravity_cli` 服务，通过官方 `agy` 的 headless / stream-json 协议翻译。

1. 设置 → Translation & Speech → **Add Antigravity** → **Account & Models…**。
2. 若未安装 CLI，点击 **Install Antigravity**，应用从官方发布源下载并校验 SHA-512，安装到应用专用目录，不需要 Terminal。
3. 点击 **Sign in / Refresh Models**。已有登录自动复用；首次登录由官方 CLI 发起，应用打开 Google 授权页。如浏览器给出授权码，在面板中粘贴并点击 **Submit Code**。超时后可重新登录。
4. 选择账号可用模型，点击 **Use Selected Model**，自动保存服务的模型和 CLI 路径。
5. **Save & Test Connection** 成功后即可划词或截图翻译。旧 Gemini CLI 服务可禁用或删除。

Google 密码仅在 Google 页面输入；授权码仅转交官方 CLI，不保存到应用配置。登录凭据由官方 CLI 管理。
关闭账号面板会取消待完成的登录进程，不会退出已登录账号。该面板目前共用一个登录会话。
托管 CLI 位于 `~/Library/Application Support/Text Selection Translation Python/bin/agy`；默认 `agy` 优先使用此路径，其次查找用户安装的 CLI。
高级用户仍可填写 CLI 绝对路径，或使用 Model `auto`。该实现仍通过官方 CLI 调用模型，每次翻译启动独立进程。

应用保留旧 Gemini CLI 配置，不会自动更换账号或修改已有服务。
Antigravity 在临时工作目录中以专用主 agent 运行，声明空工具列表；验证所选 agent，检测到实际工具调用时中止。CLI 的初始化工具列表是全局注册表，不能用来判断 agent 的工具限制。
原文通过标准输入发送，按增量事件展示回复，取消与超时会结束进程。
应用不传入 API Key，也不会开启跳过权限检查的模式。CLI 本身的全局设置、历史记录、账号额度及 AI credits 策略仍由 Antigravity 管理，请在 CLI 中检查。
会员权益取决于 Google 账号实际订阅与额度，不保证无限调用。参见
[官方 headless 文档](https://antigravity.google/docs/cli/headless/)和[订阅页面](https://antigravity.google/pricing)。

已验证 CLI 1.2.12 的安装、参数与登录后的真实翻译调用。


### Codex / ChatGPT 账号翻译（Python 实验版）

在 Settings → Translation & Speech 点击 **Add Codex**，再点击 **Account & Models…**：

1. 已安装 Codex 可直接点击 **Sign in / Refresh Models**。没有安装时，先点 **Install Codex**；应用会下载官方 macOS 二进制并校验 SHA-256。
2. 复用已有 Codex ChatGPT 登录，或在浏览器完成官方登录后自动更新账号状态。无需在 Terminal 运行命令，也无需填写 API key。
3. 从账号返回的模型列表选择模型，点击 **Use Selected Model** 保存。使用 **Save & Test Connection** 验证翻译。
4. Codex 服务旁的 **Reasoning** 可设置推理强度；**Account & Models** 中的推理菜单按所选模型列出支持的级别。`auto` 不覆盖 Codex 默认配置，显式级别会通过 `turn/start.effort` 发送，不支持的组合会提示重新选择。

应用按需启动独立 Codex App Server，通过标准输入输出通信，并在完成、超时或取消后清理进程。翻译使用临时会话，关闭常见工具功能、环境访问和 MCP 服务，使用只读沙箱；遇到工具请求中止。为避免将模型的工作说明显示为译文，收到成功的最终回复后才显示结果。账号凭据由官方 Codex 管理，应用不复制 token，不退出其他 Codex 客户端的账号。模型可用性和额度取决于 ChatGPT 账号；不代表无限使用或 Gemini 会员权益。

自动安装只更新本应用支持目录中的 Codex，不覆盖 Terminal 的安装。本功能已接入 Python 原生桌面版，尚未同步到独立 Swift 项目。

协议依据：[Codex App Server](https://developers.openai.com/codex/app-server)、[Codex CLI](https://developers.openai.com/codex/cli)。App Server 接口仍可能随官方版本变化。

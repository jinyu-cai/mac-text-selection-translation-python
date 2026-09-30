# Text Selection Translation — Python Edition

A native macOS menu bar translator built with Python, AppKit, and a local FastAPI backend. Translate selected text, clipboard content, or screenshots with multiple providers, including account-based Codex and Antigravity integrations.

This is an independent Python application with its own settings, notes, and Keychain namespace. Features in this repository do not automatically apply to the separate Swift edition.

> The Codex and Antigravity integrations are currently on the `codex/gemini-cli-provider` experimental branch. Check out that branch to use the features described below.

## Features

- Translate selected text with **⌥D** or the floating **Aa** button.
- Capture a screen region for local OCR and translation with **⌥⇧O**.
- Run enabled translation providers concurrently and compare their results in separate cards.
- Connect Codex with a ChatGPT account or Antigravity with a Google account through the app's account window.
- Choose a Codex model and reasoning effort, including model-specific supported levels.
- Use Google AI Studio or another OpenAI-compatible translation endpoint with an API key.
- Read source text or translations aloud with macOS speech, OpenAI-compatible TTS, or DashScope TTS.
- Save translations and annotations in local notes.
- Customize shortcuts, translation language, prompts, provider order, and launch-at-login behavior.

The desktop starts and stops its local backend automatically. CLI translation processes also start on demand; you do not need to keep Terminal or a separately started backend running.

## Getting started

Development requirements: **macOS 14 or later**, **Python 3.12**, and [uv](https://docs.astral.sh/uv/). Dependencies are pinned in `uv.lock`.

```sh
git clone --branch codex/gemini-cli-provider https://github.com/jinyu-cai/mac-text-selection-translation-python.git
cd mac-text-selection-translation-python
make setup
make run
```

For an existing clone:

```sh
git fetch origin
git switch codex/gemini-cli-provider
make setup
make run
```

Open the **Aa** menu bar item, then **Settings… → Translation & Speech** to add a service. Enable the services you want to use and save your changes. **Save & Test Connection** saves the configuration and sends a real test request, which may count toward your provider's usage limits.

For a step-by-step introduction to Python, FastAPI, and this application's structure, see the [beginner's guide](docs/BEGINNERS_GUIDE.md). The [`tutorial/`](tutorial/) examples include a mock provider that needs no API key.

## Translation services

| Service | Setup entry | Authentication | Result display |
|---|---|---|---|
| Codex | **Add Codex** | ChatGPT sign-in through the account window | Final answer after successful completion |
| Antigravity | **Add Antigravity** | Google sign-in through the account window | Incremental output |
| Google AI Studio | **Add Google AI Studio** | API key | Streaming output |
| OpenAI-compatible API | **Add Other → AI Translation** | Provider API key, if required | Streaming output |
| Gemini CLI, legacy | **Add Other → Gemini CLI (legacy)** | Existing CLI Google login | Incremental output |

### Codex: ChatGPT account

1. Click **Add Codex**, then **Account & Models…**.
2. If Codex is not installed, click **Install Codex**. The app downloads the official macOS CLI release and verifies its SHA-256 digest before installing it in the application's support directory.
3. Click **Sign in / Refresh Models**. An existing Codex ChatGPT login is reused. Otherwise, complete the official sign-in flow in your browser; the account window updates automatically.
4. Select a model and its **Reasoning effort**, then click **Use Selected Model** to save.
5. Click **Save & Test Connection** to verify translation.

You can also change **Reasoning** directly in the main service settings. The account window filters effort choices using the selected model's reported capabilities. Unsupported combinations are rejected with an actionable message. `auto` leaves Codex's configured default unchanged; explicit choices are sent as `turn/start.effort`.

The adapter uses an independent Codex App Server process and a temporary thread for each translation. It configures a read-only sandbox, disables environment access, configured MCP servers, and several tool features, rejects interactive tool requests, and stops translation if an unexpected tool item appears. Only a successfully completed final answer is shown as the translation.

Codex manages login credentials and token refresh. This application does not copy tokens into its settings or log you out of other Codex clients. Closing the account window cancels a pending login without signing out an existing account. Model availability and usage limits depend on the connected ChatGPT account.

Implementation references: [Codex App Server](https://developers.openai.com/codex/app-server) and [Codex CLI](https://developers.openai.com/codex/cli). CLI protocol changes may require an application update.

### Antigravity: Google account

1. Click **Add Antigravity**, then **Account & Models…**.
2. If needed, click **Install Antigravity**. The app downloads the official native CLI, verifies the manifest's SHA-512 checksum, and installs it in the application's support directory.
3. Click **Sign in / Refresh Models**. Existing login credentials are reused. For a new login, complete Google sign-in in your browser. If an authorization code is provided, paste it into the account window and click **Submit Code**.
4. Choose a model returned by your account and click **Use Selected Model**.
5. Click **Save & Test Connection**.

Enter your Google password only on the Google sign-in page. An authorization code is passed to the official CLI and is not saved in the application's configuration. The CLI manages persistent login credentials. Closing the account window cancels a pending login without signing out the account.

Each translation runs `agy` in a temporary directory with a dedicated agent declaring an empty tool list. The adapter checks the selected agent and stops if an actual tool or subagent action appears. Source text is sent through standard input, and responses are displayed incrementally. Cancellation and timeouts stop the process.

The CLI's global settings, history, subscription limits, and credit policies remain under Antigravity's control. A student offer or paid subscription does not guarantee that every model is available or that usage is unlimited. Choose a complete model ID from the account window, or use `auto` for the CLI default.

References: [Antigravity headless documentation](https://antigravity.google/docs/cli/headless/) and [Antigravity plans](https://antigravity.google/pricing).

### Google AI Studio and OpenAI-compatible APIs

For Google AI Studio, click **Add Google AI Studio**. The preset uses `https://generativelanguage.googleapis.com/v1beta/openai`; replace the preset model if needed with one available to your API project. Obtain a key from [Google AI Studio](https://aistudio.google.com/api-keys), paste it into **API Key**, and test the connection.

For another provider, click **Add Other**, select **AI Translation**, and enter its endpoint, model, and API key. A local endpoint can use an empty key if its server allows it. Leave **Reasoning** at `auto` unless the selected model supports an explicit level.

API keys are masked and stored in macOS Keychain. Leaving a saved key blank preserves it; **Clear Key** removes it. Text fields support standard macOS editing shortcuts, including **⌘V**, and the API-key field also has a **Paste** button.

API-based services use their provider's API access and billing. A login used by Codex or Antigravity is not an API key for these services.

### Gemini CLI: legacy compatibility

The legacy adapter remains available under **Add Other → Gemini CLI (legacy)** for existing configurations. Install and authenticate the CLI separately, following the [Gemini CLI documentation](https://geminicli.com/docs/get-started/installation/). Set **CLI Path** to `gemini` or the executable's absolute path, and use `auto` or a model available to that CLI account.

If your CLI reports `This client is no longer supported` and requests migration to Antigravity, use **Add Antigravity** instead. The application does not automatically migrate or remove existing Gemini services.

### CLI installation and paths

App-managed binaries are stored at:

```text
~/Library/Application Support/Text Selection Translation Python/bin/codex
~/Library/Application Support/Text Selection Translation Python/bin/agy
```

For the default commands `codex` and `agy`, the application prefers its managed binary, then searches for a user installation. You can enter an absolute executable path in **CLI Path** to select another installation. App-managed installation does not replace your Terminal installation.

Translation requests have a 150-second timeout. If a CLI service fails, refresh its login and models, check account limits and connectivity, and verify the executable path. Raw CLI diagnostics are not shown in translation errors because they may contain source text or credentials. Consult the CLI's own history and privacy settings for any data it retains.

## Controls and permissions

- **Selection translation:** press **⌥D**, use the floating **Aa** button, or choose **Translate Selection**. Capture tries Accessibility first, then a Copy fallback with conditional clipboard restoration.
- **Clipboard translation:** choose **Translate Clipboard** from the menu bar.
- **Screenshot translation:** press **⌥⇧O** or choose **Screenshot Translation…**, then drag a region. Press **Esc** to cancel. ScreenCaptureKit captures the image and Vision recognizes text locally; recognized text is then sent to enabled translation providers.
- **Popup:** drag the header to move it or the bottom-right handle to resize it. Source and result cards have speech controls; results also have copy controls. Closing or dismissing the popup cancels pending translation work.
- **Speech:** with no enabled TTS service, the app uses macOS speech. Multiple TTS services produce a selection menu. Speech services have a **Save & Preview Voice** button in settings.
- **Notes:** enable **Enable local notes** in General settings, then use the popup's note button. Annotations save after a short delay and flush when switching notes, closing, or quitting.
- **Shortcuts:** record custom selection and OCR shortcuts in General settings. Avoid conflicts with another running translator, including the Swift edition.
- **Launch at login:** configure it in the packaged app; macOS may require approval in Login Items settings.

Grant **Accessibility** for selection capture and **Screen Recording** for screenshots, then restart the app. Permissions are separate from the Swift edition. A packaged application with a consistent signing identity is preferable for everyday use.

To enable the experimental Microsoft dictionary integration during development:

```sh
make beta-run
```

Normal launches do not run enabled experimental dictionary services. Experimental mode uses the same Python application's data store.

## Build a macOS application

```sh
make app
make sign
open "dist/Text Selection Translation Python.app"
```

`make app` replaces the local `build/` and `dist/` directories. Move any artifacts you want to keep before rebuilding.

The bundle includes Python and its dependencies, so end users do not need Python or uv. CLI services still need their respective CLI installations, which can be managed from the account windows. Copy the app to `/Applications` for everyday use.

Builds are architecture-specific. The packaged application has been tested on Apple Silicon; an Intel build requires separate validation. `make sign` uses ad-hoc signing by default. A distribution certificate and notarization are separate steps; these build commands do not produce a notarized release.

The app icon is generated by [`packaging/generate_icon.py`](packaging/generate_icon.py). Packaging includes a compatibility adjustment for py2app's handling of zlib in uv's standalone Python.

## Architecture and local data

```text
AppKit main thread                 Background asyncio thread
Menus, popup, settings, notes ─HTTP─► FastAPI / Uvicorn
Carbon hotkeys                      HTTP provider clients
Accessibility / clipboard           Codex / Antigravity / Gemini processes
ScreenCaptureKit + Vision           Concurrent translation + SSE
Speech playback / login items       SQLite + macOS Keychain
```

The backend listens on an ephemeral `127.0.0.1` port and requires a random in-memory bearer token generated at launch. Browser-origin requests are rejected, CORS is not enabled, and public API documentation routes are disabled. AppKit work stays on the main thread; the backend and desktop HTTP client share a background event loop.

| Data | Location or identifier |
|---|---|
| Settings and notes database | `~/Library/Application Support/Text Selection Translation Python/translator.sqlite3` |
| Managed CLI binaries | `~/Library/Application Support/Text Selection Translation Python/bin/` |
| Bundle identifier | `com.example.mactranslator.python` |
| API-key Keychain service | `com.example.mactranslator.python.credentials.v1` |
| CLI login credentials | Managed by each official CLI |

API keys are excluded from serialized settings responses. Provider errors and validation responses are sanitized. Selected text and OCR results are sent to the enabled providers to perform translation; local OCR does not make the subsequent model request offline.

### Backend API

All paths below use the `/api/v1` prefix and require the local bearer token. Request models are defined in [`contracts.py`](src/mactranslator/contracts.py).

| Method and path | Purpose |
|---|---|
| `GET /health` | Readiness and experimental dictionary flag |
| `GET /settings`, `PUT /settings` | Read or replace preferences and provider settings |
| `POST /translate` | Translate `{text, request_id?}` with SSE output |
| `POST /providers/{id}/test` | Test a translation or dictionary service |
| `POST /speech` | Generate speech from `{provider_id, text, language?}` |
| `GET /notes`, `POST /notes` | List or create notes |
| `GET /notes/{id}`, `PATCH /notes/{id}`, `DELETE /notes/{id}` | Read, annotate, or delete a note |
| `POST /codex/install`, `POST /antigravity/install` | Install the corresponding app-managed CLI |
| `POST /codex/login`, `POST /antigravity/login` | Start login or load models using `{cli_path}` |
| `GET /codex/login`, `GET /antigravity/login` | Read login status and available models |
| `DELETE /codex/login`, `DELETE /antigravity/login` | Cancel the corresponding account session; does not log out |
| `POST /antigravity/login/code` | Submit an authorization code to the pending CLI login |

Provider kinds are `translation`, `codex_cli`, `antigravity_cli`, `gemini_cli`, `openai_tts`, `dashscope_tts`, and experimental `dictionary`. Provider IDs remain stable across edits and reordering.

Translation SSE starts with `start`, interleaves provider `delta` or `dictionary` events, records `provider_done` or `provider_error`, and ends with `done`. Codex delivers its final answer as a delta after successful completion. Idle streams send heartbeats. One provider's failure does not stop the others, and closing a stream cancels its associated work.

## Development and verification

```sh
make check
make test

# Native smoke check with synthetic content and temporary data
.venv/bin/python -m mactranslator.desktop.app --smoke-test /tmp/translator-native-check

# Packaged application smoke check
"dist/Text Selection Translation Python.app/Contents/MacOS/Text Selection Translation Python" \
  --smoke-test /tmp/translator-bundle-check
```

The latest implementation verification passed **106 automated tests**, packaged native smoke checks, and bundle signature verification. Tests cover provider behavior, settings and notes, credential redaction, cancellation, CLI authentication protocols, Codex effort parameters, model capabilities, and installer integrity checks. Live checks also verified account model discovery and short translations through installed Codex and Antigravity clients.

First-time browser sign-in flows are covered by simulated protocol tests; they have not been fully verified with fresh real accounts. Native smoke checks use synthetic content and temporarily exercise clipboard shortcuts. Their offscreen images may omit layer-backed controls, so they are not a substitute for interactive visual testing.

Before distributing a build, verify selection capture in browsers, PDF readers, and editors; multi-display OCR and popup placement; permission prompts; configured speech providers; notes persistence; and an actual launch-at-login cycle on the target Mac.

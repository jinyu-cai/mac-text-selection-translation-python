# Text Selection Translation — Python edition

A native macOS menu bar application written in Python, with a local FastAPI backend. It uses its own configuration, notes, and Keychain namespace, separate from the original Swift edition.

New to Python or FastAPI? Read the [complete beginner's guide](docs/BEGINNERS_GUIDE.md): start in an empty folder, build two small working APIs, assemble the real app module by module, and package it for macOS. The accompanying `tutorial/` examples include a mock-provider server that needs no API key.

## Run

Requirements: macOS 14+, Python 3.12, and [uv](https://docs.astral.sh/uv/). The checked-in `uv.lock` pins development and runtime dependencies.

Clone this repository, then run from its root:

```sh
git clone https://github.com/jinyu-cai/mac-text-selection-translation-python.git
cd mac-text-selection-translation-python
make setup
make run
```

The menu bar item is **译 Py**. Open **设置…**, add a translation provider, enter its endpoint, model, and optional API key, then save. **保存并测试连接 / 朗读** saves that configuration and sends a test request. A local OpenAI-compatible provider can have an empty key.

The desktop starts FastAPI automatically on an ephemeral loopback port. There is no separate server command, fixed port, browser interface, or account setup.

## Features and controls

- **Selected text:** press `⌥D`, or select text and click the floating **译** button. Capture uses Accessibility first, then simulated Copy with conditional clipboard restoration.
- **Screenshot OCR:** press `⌥⇧O` or choose **截图 OCR 翻译…**. Drag a rectangle on a display; Esc cancels. ScreenCaptureKit captures the region and Vision recognizes its text locally.
- **Translation:** enabled translation providers run concurrently. Results stream into the popup in provider order. Drag the title bar to move it; Esc, Close, or clicking outside dismisses it and cancels requests. Text is selectable; Markdown and tables are rendered natively.
- **Prompts:** the existing three-function translation/dictionary template and model-specific request policies are retained. A custom prompt replaces the output policy while retaining the source-text safety boundary.
- **Speech:** select the source or a result in the popup dropdown, then click **朗读**. With no enabled TTS provider, macOS speech is used. One TTS provider is called directly; multiple providers open a menu that also offers macOS speech. OpenAI-compatible and DashScope backends support voice, audio format, and style settings.
- **Notes:** enable **本地笔记** in General settings. The popup saves the first usable completed translation in configured provider order. Notes support reading, copying, deletion, and annotations that save after 500 ms and flush when switching, closing, or quitting.
- **Settings:** translation and OCR hotkeys are independently configurable. Click their buttons to record; Esc cancels recording. Provider **上移 / 下移** controls persist ordering. API-key fields are masked; leave a saved key blank to keep it, or check **清除 Key** to remove it.
- **Launch at login:** available through ServiceManagement in the packaged app. macOS may require approval in Login Items settings.
- **Experimental dictionary:** `make beta-run` enables Microsoft dictionary configuration. Normal launches reject enabled dictionary settings and do not send dictionary requests, even if an experimental launch previously saved them. The experimental command uses the Python edition's data store.

Accessibility and Screen Recording permissions are granted to this Python application separately from the Swift app. Run the packaged app for stable permission identity, and restart it after granting permissions. If the Swift app is running with the same shortcuts, quit one app or assign different shortcuts.

## Package

```sh
make app
make sign
open "dist/Text Selection Translation Python.app"
```

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

The smoke check constructs all native windows, renders sample content, recognizes a generated image with Vision, registers/releases a temporary test hotkey, and starts/stops the authenticated loopback service. It does not use real provider credentials, capture the screen, or alter login registration. Output contains `report.json` and diagnostic view renders. Modern layer-backed controls may be absent from the offscreen renders; use the live application for final visual QA.

Verified during implementation:

- 41 automated tests: policy parity, fragmented Unicode SSE, concurrency, independent failures, cancellation, retry limits, credential redaction, unavailable credentials, settings/notes persistence, dictionary gating, TTS payloads, PCM playback wrapping, loopback lifecycle, stale popup events, and note autosave races.
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

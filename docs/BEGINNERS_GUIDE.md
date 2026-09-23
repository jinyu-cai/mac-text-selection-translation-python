# Build a native macOS translator with Python and FastAPI — from zero

This guide starts with an empty folder and ends with the Python edition of **Text Selection Translation**: a menu bar app that captures selected text, streams translations from multiple providers, recognizes screenshots, reads text aloud, and saves notes.

You do not need previous FastAPI experience. You will first build two small APIs yourself. Then you will assemble the real application in dependency order, with explanations of the code, commands to run, and checkpoints that show whether each stage works.

The source files linked throughout this guide are the complete implementations. The assembly commands copy them one module at a time from your reference checkout into your learning project. You can instead type their contents while following the explanation. This is a guided reconstruction of the actual app, not a claim that a short example replaces its macOS integration code.

Written against this repository's Python implementation on **September 22, 2026**. The guide's runnable lessons use simulated translation, so you can learn without a provider account or API key. Real translation requires a configured model service later.

## Contents

1. [What you are building](#1-what-you-are-building)
2. [Install the tools and understand Terminal](#2-install-the-tools-and-understand-terminal)
3. [Create an empty learning project](#3-create-an-empty-learning-project)
4. [The Python concepts you need](#4-the-python-concepts-you-need)
5. [Build your first working API](#5-build-your-first-working-api)
6. [Make responses stream from two providers](#6-make-responses-stream-from-two-providers)
7. [Turn the exercise into the application package](#7-turn-the-exercise-into-the-application-package)
8. [Define the data contracts](#8-define-the-data-contracts)
9. [Write translation policies and provider clients](#9-write-translation-policies-and-provider-clients)
10. [Persist settings and notes with SQLite](#10-persist-settings-and-notes-with-sqlite)
11. [Keep API keys in Keychain](#11-keep-api-keys-in-keychain)
12. [Assemble and exercise the real FastAPI backend](#12-assemble-and-exercise-the-real-fastapi-backend)
13. [Build the native desktop foundation](#13-build-the-native-desktop-foundation)
14. [Connect AppKit to the backend](#14-connect-appkit-to-the-backend)
15. [Implement selected-text capture and global shortcuts](#15-implement-selected-text-capture-and-global-shortcuts)
16. [Build the floating icon and translation popup](#16-build-the-floating-icon-and-translation-popup)
17. [Add screenshot OCR](#17-add-screenshot-ocr)
18. [Add speech and the experimental dictionary](#18-add-speech-and-the-experimental-dictionary)
19. [Complete settings, notes, startup, and shutdown](#19-complete-settings-notes-startup-and-shutdown)
20. [Run the full desktop app](#20-run-the-full-desktop-app)
21. [Test and debug it](#21-test-and-debug-it)
22. [Build a standalone macOS application](#22-build-a-standalone-macos-application)
23. [Troubleshooting](#23-troubleshooting)
24. [Exercises and a completion checklist](#24-exercises-and-a-completion-checklist)

## 1. What you are building

There are two meanings of “backend” in this project:

- **The application backend** is your local FastAPI service. It manages translation requests, provider configuration, notes, and speech synthesis requests.
- **A translation provider** is an external or locally hosted model service. It receives an AI request and generates the translated text. The UI sometimes calls these providers “后端.”

FastAPI does not itself translate language. It also does not create a macOS menu bar item or read another application's text selection. Your Python code connects those capabilities.

The complete system looks like this:

```text
You select text in another application
                  |
                  v
Native desktop: PyObjC + macOS frameworks
  capture selection -> open popup -> send HTTP request
                  |
                  | authenticated HTTP on 127.0.0.1
                  v
Local service: FastAPI running inside Uvicorn
  load settings -> build prompts -> call enabled providers
                  |
                  | HTTPX requests to the configured model services
                  v
Translation providers return streaming text
                  |
                  v
FastAPI sends events -> desktop updates the popup
```

The finished app runs as **one desktop process** with an AppKit main thread and an asyncio worker thread. The local HTTP boundary keeps service code independent of the UI even though both live inside one process.

### Which tool does what?

| Tool | Its job in this application |
|---|---|
| Python 3.12 | Runs your application code |
| uv | Installs Python/dependencies and maintains the environment and lockfile |
| FastAPI | Routes HTTP requests and validates API inputs/outputs |
| Uvicorn | Accepts HTTP connections and runs the FastAPI ASGI application |
| Pydantic | Defines validated Python objects such as Settings and TranslationRequest |
| HTTPX | Sends requests to providers and to the local API |
| asyncio | Coordinates concurrent network requests and streaming |
| SQLite | Stores non-secret settings and notes in a local database file |
| PyObjC | Lets Python call macOS Objective-C frameworks |
| AppKit | Creates native windows, buttons, text views, and menu bar controls |
| ScreenCaptureKit / Vision | Capture a selected screen area and recognize its text |
| AVFoundation | Plays audio and provides native text-to-speech |
| Security / Keychain | Stores provider API keys |
| py2app | Bundles your code, Python, and dependencies into a `.app` |

No React, HTML frontend, Docker, cloud database, or Swift compiler is needed for this Python edition. The UI uses macOS controls directly.

## 2. Install the tools and understand Terminal

Use a Mac running **macOS 14 or later**. The backend lessons can illustrate general Python concepts elsewhere, but the finished desktop application requires macOS.

### 2.1 Install Apple's command-line tools

Open Terminal and check:

```sh
xcode-select -p
```

If this reports that the tools are missing, run:

```sh
xcode-select --install
```

Complete the installer. These tools provide commands used during development and packaging. You do not need to open a Swift project in Xcode.

### 2.2 Install uv

If you already use Homebrew:

```sh
brew install uv
```

Otherwise, uv's official standalone installer is:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Use one installation method, then open a new Terminal window and check:

```sh
uv --version
```

These commands are documented in the [official uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

### 2.3 Install the required Python version

```sh
uv python install 3.12
```

This project intentionally requires Python 3.12. Do not assume that the `python3` command on your Mac points to that version. Inside the project, use `uv run python` or `.venv/bin/python`.

Use uv's normal installation location. Do not put the interpreter you intend to keep using in `/tmp` or `/private/tmp`: macOS may clean up that directory, leaving your virtual environment's Python symlink broken.

### 2.4 Terminal conventions used below

- A **directory** is a folder. `pwd` prints your current folder; `ls` lists its contents.
- `cd folder` changes the current folder. Most “module not found” mistakes in this tutorial are either a wrong folder or a wrong Python environment.
- `$HOME` expands to your home folder, such as `/Users/jinyu`.
- Quotes keep a path containing spaces together as one argument.
- A backslash at the end of a shell line continues the same command on the next line.
- `Ctrl+C` stops a server running in the current terminal.
- Code blocks labelled `python` belong in a `.py` file unless the guide explicitly says to use an interactive prompt. Do not paste Python statements directly into the shell.
- Server commands keep running. Use a **second terminal** for `curl` requests, rather than typing into the occupied server terminal.

## 3. Create an empty learning project

Use a new directory, separate from the existing Swift/Python repository:

```sh
mkdir -p "$HOME/Developer/translator-learning"
cd "$HOME/Developer/translator-learning"
mkdir -p tutorial
touch tutorial/__init__.py
```

Open this folder in your editor. Create a file named `pyproject.toml` at its top level with the following complete contents:

```toml
[project]
name = "translator-learning"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "fastapi>=0.115,<1",
    "uvicorn>=0.30,<1",
    "httpx>=0.27,<1",
    "pydantic>=2.9,<3",
]
```

Install the dependencies:

```sh
uv sync
uv run python --version
uv run python -c "import fastapi, httpx; print('Imports work')"
```

Expected: Python `3.12.x`, followed by `Imports work`.

The first `uv sync` creates two important things:

- `.venv/`: the isolated environment that contains this project's packages.
- `uv.lock`: the resolved dependency versions. The ranges in `pyproject.toml` describe allowed versions; the lockfile records a particular resolution.

`uv run` runs a command using the project environment. You do not have to run `source .venv/bin/activate`. When the lockfile already matches the project, `uv sync --locked` verifies that it does not need to be changed. For the initial empty project, use `uv sync` because no lockfile exists yet. See [uv's project workflow](https://docs.astral.sh/uv/guides/projects/).

Your folder now looks approximately like this:

```text
translator-learning/
  pyproject.toml
  uv.lock
  .venv/
  tutorial/
    __init__.py
```

**Checkpoint:** both import commands above succeed. Do not continue until they do.

## 4. The Python concepts you need

You can learn these as you encounter the actual code. You do not need to memorize every Python feature first.

### Functions, arguments, and returned values

```python
def greeting(name: str) -> str:
    return f"Hello, {name}"

message = greeting("Ada")
assert message == "Hello, Ada"
```

`def` defines a function. `name` is an argument. The annotations `: str` and `-> str` describe the expected types. Ordinary Python annotations do not automatically validate runtime values; FastAPI/Pydantic use them to construct validation at the API boundary.

Indentation groups statements. Use four spaces inside a function. A colon usually introduces an indented block.

### Dictionaries, lists, and JSON

```python
provider = {"name": "Example", "enabled": True}
providers = [provider]
assert providers[0]["name"] == "Example"
```

A dictionary has named keys. A list has ordered positions beginning at zero. JSON is a text format used to send similar structures over HTTP. Python writes `True` and `None`; JSON writes `true` and `null`. Let a JSON encoder perform the conversion.

### Classes and instances

```python
class Counter:
    def __init__(self):
        self.value = 0

    def increment(self):
        self.value += 1

counter = Counter()
counter.increment()
assert counter.value == 1
```

A class groups data and behavior. `self` refers to one instance. In the app, a `TranslationPopup` instance owns its window and current results; a `Store` instance owns a database connection.

### Imports and packages

`from mactranslator.contracts import Settings` means “find the `contracts` module inside the `mactranslator` package and import its Settings class.” A `.py` file is a module. The `__init__.py` files identify the packages used here.

Running a package module with `python -m ...` gives Python its package context. This matters because the application uses relative imports such as `from .storage import Store`.

### async, await, and tasks

An `async def` function produces a coroutine when called. `await` allows an asynchronous operation to finish while the event loop can do other work. This suits a translation app that spends much of its time waiting for network responses.

`asyncio.create_task(...)` schedules a coroutine so it can progress alongside other tasks. Merely writing two consecutive `await` expressions does not make the two operations run concurrently.

An async function can still block its thread if it calls blocking code. The application therefore keeps AppKit on the main thread and runs Vision recognition through `asyncio.to_thread(...)`.

### yield and finally

A generator uses `yield` to produce one value at a time. The streaming lessons yield one SSE frame at a time. A `finally` block performs cleanup even when an operation fails or is cancelled; the translation generator uses it to cancel provider tasks.

## 5. Build your first working API

Create `tutorial/lesson_01_api.py` with this complete code. The same file is supplied in [the tutorial directory](../tutorial/lesson_01_api.py).

```python
"""First API: explicit demonstration output, no external service."""
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Translator learning API")


class TranslationInput(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    target_language: str = "中文"


@app.get("/health")
async def health():
    return {"ready": True}


@app.post("/translate")
async def translate(body: TranslationInput):
    return {
        "source": body.text,
        "target_language": body.target_language,
        "output": f"DEMO ONLY: {body.text}",
    }
```

### 5.1 Read the program

`app = FastAPI(...)` creates the web application. The decorator `@app.get("/health")` registers a route: HTTP GET requests to that path execute `health()`. Returning a Python dictionary produces a JSON response. A route is the combination of a method and a path; GET and POST can have different meanings at the same path. [FastAPI first steps](https://fastapi.tiangolo.com/tutorial/first-steps/)

`TranslationInput` describes the JSON request body. FastAPI builds that Pydantic model before calling `translate()`, so the handler receives a validated object instead of an unstructured dictionary. `Field(min_length=1)` rejects an empty string, and the default language is used when the client omits it. [FastAPI request bodies](https://fastapi.tiangolo.com/tutorial/body/)

The returned output is deliberately marked `DEMO ONLY`. There is no language model in this first lesson.

### 5.2 Start it

In Terminal A, from your learning project:

```sh
uv run python -m uvicorn tutorial.lesson_01_api:app --host 127.0.0.1 --port 8765 --reload
```

Read `tutorial.lesson_01_api:app` as “import that module and use the variable named `app`.” Uvicorn supplies the HTTP server. `--reload` restarts this teaching server after source edits; it is not used inside the final desktop app.

`127.0.0.1` means this computer. `8765` is the chosen port for the lesson. If it is occupied, stop the other lesson server before starting this one.

### 5.3 Call it

In Terminal B:

```sh
curl -s http://127.0.0.1:8765/health
```

Expected JSON:

```json
{"ready": true}
```

Send text as a JSON body:

```sh
curl -s http://127.0.0.1:8765/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello","target_language":"中文"}'
```

Expected content, ignoring whitespace and JSON escaping:

```json
{"source":"Hello","target_language":"中文","output":"DEMO ONLY: Hello"}
```

`-d` makes curl send a POST body. `-H` adds an HTTP header. The server uses the content-type header to interpret the body as JSON.

Now try an empty string:

```sh
curl -i http://127.0.0.1:8765/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":""}'
```

Expected: HTTP **422**, meaning validation rejected the input. The small lesson permits whitespace-only text; the real application's contract adds a validator to reject it.

You can also open [the lesson's interactive API page](http://127.0.0.1:8765/docs) while the server is running. The lesson enables FastAPI's default documentation. The final application's `/docs` is intentionally disabled, so the same page will not exist there.

**Checkpoint:** you can explain why one request returns 200 and the empty-text request returns 422. Stop Terminal A with `Ctrl+C` before the next lesson.

## 6. Make responses stream from two providers

A normal JSON response arrives as one complete value. A translation may take several seconds, so the app sends smaller events as results arrive.

It uses **Server-Sent Events**, or SSE. Here is a frame:

```text
data: {"type":"delta","provider_id":"fast","text":"Hello"}

```

The frame ends with a blank line. In Python that ending is `"\n\n"`. A delta is a piece of new text to append, not the entire result.

Create `tutorial/lesson_02_stream.py` with this complete code, also available [as a runnable file](../tutorial/lesson_02_stream.py):

```python
"""Two simulated providers; learn SSE, concurrency, and cleanup without credentials."""
import asyncio
import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Streaming lesson")


class TranslationInput(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


@app.post("/translate")
async def translate(body: TranslationInput):
    request_id = str(uuid4())

    async def events():
        queue = asyncio.Queue(maxsize=16)

        async def provider(name, delay):
            # Echoing is intentional: this lesson does not perform translation.
            for piece in ["DEMO ONLY: ", body.text, " ✓"]:
                await asyncio.sleep(delay)
                await queue.put({"type": "delta", "provider_id": name, "text": piece})
            await queue.put({"type": "provider_done", "provider_id": name})

        tasks = [asyncio.create_task(provider("fast", 0.05)),
                 asyncio.create_task(provider("slow", 0.15))]
        remaining = len(tasks)
        try:
            while remaining:
                item = await queue.get()
                if item["type"] == "provider_done":
                    remaining -= 1
                item["request_id"] = request_id
                yield "data: " + json.dumps(item, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({"type": "done", "request_id": request_id}) + "\n\n"
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    return StreamingResponse(events(), media_type="text/event-stream")
```

Run it in Terminal A:

```sh
uv run python -m uvicorn tutorial.lesson_02_stream:app --host 127.0.0.1 --port 8765
```

Call it from Terminal B:

```sh
curl -N http://127.0.0.1:8765/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello"}'
```

`-N` turns off curl's output buffering. You should see deltas from `fast` and `slow`, a `provider_done` for each, and one final `done`. Exact interleaving can vary with scheduling.

### 6.1 Why the queue exists

Each provider task produces events independently. The response generator needs one place to collect them. `asyncio.Queue` supplies that place: producers `put` events into it, and the generator `get`s them.

The queue has a maximum size. If the consumer is slower than the producers, `await queue.put(...)` waits instead of allowing an unlimited backlog. This is called **backpressure**.

The delay in the fake providers stands in for network waiting. Both tasks are created before events are consumed, so the slow provider does not prevent the fast one from making progress.

### 6.2 What StreamingResponse does

`StreamingResponse` consumes the generator and sends its yielded chunks as the HTTP response body. Setting `media_type="text/event-stream"` identifies the protocol used by those chunks. FastAPI supports responses supplied this way. [Custom and streaming responses](https://fastapi.tiangolo.com/advanced/custom-response/)

This application streams a **POST** request because it sends the selected text in a JSON body. The desktop reads the stream using HTTPX. A browser's basic `EventSource` interface is not what the native app uses.

### 6.3 What this lesson intentionally leaves out

The two fake producers do not fail. The production implementation must also handle exceptions, cancelled clients, empty model responses, provider metadata, and credentials. An unexpected producer failure in a simplistic queue design can leave the consumer waiting forever; the real API converts failures into terminal `provider_error` events.

The `finally` block is already present in the lesson because cancellation belongs in the design from the beginning. If the stream closes, its tasks should not continue running unnecessarily.

**Checkpoint:** both providers stream through one HTTP response, and you understand the difference between `provider_done` and `done`. Stop this server with `Ctrl+C`.

## 7. Turn the exercise into the application package

The small lessons teach the mechanisms. You will now build the actual application from its complete source modules.

Keep your current folder as the **learning project**. Clone the complete Python edition into a separate reference folder if you have not already:

```sh
mkdir -p "$HOME/github"
git clone https://github.com/jinyu-cai/mac-text-selection-translation-python.git \
  "$HOME/github/mac-text-selection-translation-python"
```

Then point the assembly commands at that reference checkout:

```sh
export TRANSLATOR_REFERENCE="$HOME/github/mac-text-selection-translation-python"
export TRANSLATOR_LAB="$HOME/Developer/translator-learning"
test -f "$TRANSLATOR_REFERENCE/src/mactranslator/contracts.py"
cd "$TRANSLATOR_LAB"
```

Change `TRANSLATOR_REFERENCE` if your checkout is elsewhere. If you are working in the original Swift repository, its `python-app/` directory can also serve as the reference. `test -f` should exit successfully; `echo $?` immediately afterwards prints `0` on success. Use a checkout containing the Python edition and this guide.

Keep these exports in your main tutorial terminal. If you reopen Terminal, set them again before using the copy commands. The variables are conveniences, not application configuration.

### 7.1 Create the package directories

```sh
mkdir -p src/mactranslator/backend src/mactranslator/desktop tests packaging
cp "$TRANSLATOR_REFERENCE/src/mactranslator/__init__.py" src/mactranslator/
cp "$TRANSLATOR_REFERENCE/src/mactranslator/backend/__init__.py" src/mactranslator/backend/
cp "$TRANSLATOR_REFERENCE/src/mactranslator/desktop/__init__.py" src/mactranslator/desktop/
```

The top-level initializer defines `APP_NAME`, `BUNDLE_ID`, and `VERSION`. These values determine the Python edition's identity and data namespace. [Complete initializer](../src/mactranslator/__init__.py)

### 7.2 Install the full application's dependencies

Replace the small exercise manifest with the full project manifest and its lockfile:

```sh
cp "$TRANSLATOR_REFERENCE/pyproject.toml" .
cp "$TRANSLATOR_REFERENCE/uv.lock" .
cp "$TRANSLATOR_REFERENCE/.gitignore" .
uv sync --locked --extra dev
uv run python -c "import mactranslator; print(mactranslator.APP_NAME)"
```

Expected: `Text Selection Translation Python`.

The full [pyproject.toml](../pyproject.toml) adds the native framework wrappers, Markdown renderer, and development tools. Its `src` package discovery tells setuptools where the importable code lives. Installing the project makes `import mactranslator` work even though the source is under `src/`.

The `package-data` entry includes `translation_prompt.txt`. That text file must travel with the package, including in the eventual app bundle. The `project.scripts` entry defines the installed `mac-translator-python` command; it will work after the desktop module is added.

Do not rename `mactranslator` midway through this guide: imports and packaging refer to it. A separately named fork can be made after the complete build works.

### 7.3 How the rest of the assembly works

Each subsequent chapter introduces a subsystem, identifies its complete source, and gives exact commands that add it to your learning project. These commands do not modify the reference checkout. The final app still uses the Python edition's normal name and storage location; close any other copy of that edition before launching your reconstructed copy.

If you prefer to author rather than copy, create the destination files with the linked source contents and follow the same checkpoints. The guide explains the decisions that make the modules work together; the linked files supply all implementation lines without hiding callback or macOS details behind ellipses.

## 8. Define the data contracts

Add [contracts.py](../src/mactranslator/contracts.py):

```sh
cp "$TRANSLATOR_REFERENCE/src/mactranslator/contracts.py" src/mactranslator/
```

A contract specifies what an input or output means. The same `Settings` model is used by the service and desktop, preventing the two sides from inventing incompatible field names.

| Model | Why it exists |
|---|---|
| `Provider` | One translation, TTS, or dictionary configuration |
| `Hotkey` | A physical key code and modifier bits |
| `Settings` | Ordered providers, language, prompt, and desktop preferences |
| `TranslationRequest` | Source text plus an ID for one translation session |
| `StreamEvent` | One event sent from the service to the popup |
| `SpeechRequest` | Which speech provider to use and what to read |
| `NoteCreate` / `NoteUpdate` / `Note` | New note input, annotation edits, and persisted notes |

### 8.1 Stable provider IDs and changing request IDs

A provider's UUID stays the same when its name changes or it moves in the list. It identifies that configuration and its Keychain account.

A translation's request UUID changes for each new selection. An event carries both IDs, allowing the desktop to answer two questions: “Which result card?” and “Does this still belong to the current translation?”

Without a request ID, a late chunk from an old request could append to a newer result for the same provider.

### 8.2 Validation and defaults

The shared base model rejects unknown fields using `extra="forbid"`. A typo such as `target_langauge` should fail rather than silently create an unused option.

`Field(default_factory=uuid4)` calls `uuid4` for each new instance. `Field(default_factory=list)` makes a fresh list. Read this as “create this value when the model is constructed.”

`TranslationRequest` rejects missing, empty, or whitespace-only source text and limits its length to 200,000 characters. `Settings` rejects duplicate provider IDs and identical active translation/OCR shortcuts. `Provider` requires an HTTP(S) endpoint without embedded username/password credentials.

Run this small check from the learning project:

```sh
uv run python - <<'PY'
from mactranslator.contracts import Provider, Settings, TranslationRequest

provider = Provider(name="My provider", api_key="example-secret-not-a-real-key")
settings = Settings(providers=[provider])
assert "example-secret-not-a-real-key" not in settings.model_dump_json()
assert "api_key" not in provider.model_dump()
assert TranslationRequest(text="Hello").text == "Hello"
print("Contracts and secret exclusion work")
PY
```

### 8.3 Why SecretStr alone is insufficient

`SecretStr` masks a secret in common representations. This app also uses `Field(exclude=True)` so the field is absent from serialized configuration. The plaintext is deliberately extracted only when writing a supplied key into Keychain.

Use `model_dump()` for Python data, `model_dump(mode="json")` for JSON-compatible data such as string UUIDs, and `model_dump_json()` for a JSON string. Field exclusion is enforced during serialization. [Pydantic serialization](https://docs.pydantic.dev/latest/concepts/serialization/)

The settings editor therefore preserves explicitly entered keys separately when building a write request. Blindly serializing a `Provider` object for that request would remove its `api_key` field. This distinction is essential when you later implement the settings UI.

**Checkpoint:** the contract check prints its success message. No network connection or macOS permission is needed yet.

## 9. Write translation policies and provider clients

Add these files:

```sh
cp "$TRANSLATOR_REFERENCE/src/mactranslator/translation_prompt.txt" src/mactranslator/
cp "$TRANSLATOR_REFERENCE/src/mactranslator/policies.py" src/mactranslator/
cp "$TRANSLATOR_REFERENCE/src/mactranslator/backend/credentials.py" src/mactranslator/backend/
cp "$TRANSLATOR_REFERENCE/src/mactranslator/backend/providers.py" src/mactranslator/backend/
```

The credentials module is added here because provider error handling imports its `CredentialError` type. Its Keychain behavior is explained in Chapter 11. Importing the module does not read any keys.

### 9.1 Keep policy separate from transport

[policies.py](../src/mactranslator/policies.py) contains functions that mostly transform values into other values. For example:

```python
from mactranslator.policies import endpoint, messages, parameters

assert endpoint("https://example.com/v1/", "translation") == "https://example.com/v1/chat/completions"
assert messages("generic-model", "Translate the source.", "Hello")[0]["role"] == "system"
assert parameters("generic-model", "auto") == {"temperature": 0.2}
```

No request is sent by this example. Separating these decisions makes them testable without contacting a model.

The real prompt builder takes the user's target language and optional custom prompt. If the custom prompt is blank, it uses the bundled template. If provided, the custom prompt supplies the output policy. In both cases, an additional boundary tells the model to treat the source text as translation material rather than executable instructions. This is a request-design measure, not a guarantee about every model's behavior.

The bundled template asks the model to choose between Chinese-to-English variants, a compact word/phrase dictionary entry, and translation of other non-Chinese text. The application does not run its own character-count heuristic to select those translation branches.

### 9.2 Preserve compatibility deliberately

The current code includes these compatibility rules inherited from the Swift version:

- General models use instruction and user messages.
- Recognized GPT-5/o-series names use a `developer` instruction message.
- Hy-MT/Hunyuan-MT translation models, excluding Chimera names, get one combined user message.
- Reasoning modes map to the existing `reasoning_effort` policy; some model families omit temperature.
- OpenCode Go endpoints receive one shared session header for a translation and its retries.

These are the repository's current rules, not a promise that every future provider or model accepts them. Learn how `normalized_model`, `inline_model`, `messages`, and `parameters` encode the rules before changing them. Add regression cases when introducing a new compatibility rule.

### 9.3 Build the provider request

Read [ProviderClient.translate](../src/mactranslator/backend/providers.py). Its body contains:

```text
model        -> the configured model name
stream       -> true
messages     -> the policy-specific instruction/source messages
extra fields -> the model-compatible sampling/reasoning parameters
```

It sends that body with HTTPX to the normalized endpoint. If a provider key is present, it adds a Bearer authorization header. The source text is transmitted to the provider the user configured; “local backend” does not mean the model necessarily runs locally.

The client uses an asynchronous streaming context so the upstream HTTP response remains open while chunks arrive and is closed when the operation exits. One shared `AsyncClient` is reused for connections rather than constructing a new client for every token. [HTTPX async support](https://www.python-httpx.org/async/)

### 9.4 Parse upstream events before forwarding them

Upstream providers send OpenAI-compatible SSE, for example:

```json
{"choices":[{"delta":{"content":"你好"}}]}
```

Your local API sends its own richer event format containing request/provider IDs. The provider client extracts content; the API layer wraps it into your application's `StreamEvent`.

The `sse_data()` helper handles blank-line frame boundaries, comments, multiple `data:` lines, and an unfinished final frame at end-of-file. HTTPX's line iterator handles network chunks that split lines or Unicode characters. Do not assume each received network packet is one complete JSON event.

### 9.5 Retry only when safe for the displayed output

The client allows two total attempts for eligible transport failures. It waits 400 ms before the retry. Once any content has been emitted, it does not restart the request: restarting could repeat already displayed text or mix two different answers.

HTTP failures such as 401 or 429 are not classified as transport retries here. An empty successful stream becomes a visible “no translation result” error. `public_error()` returns useful error categories without copying arbitrary provider response bodies or URLs into the UI.

**Checkpoint:** run the three pure assertions in §9.1. You should now be able to trace a request from a provider configuration to a URL, headers, JSON body, and extracted text.

## 10. Persist settings and notes with SQLite

Add [storage.py](../src/mactranslator/backend/storage.py):

```sh
cp "$TRANSLATOR_REFERENCE/src/mactranslator/backend/storage.py" src/mactranslator/backend/
```

SQLite stores a database in a file. There is no database daemon to start and no separate password to configure. Python includes the `sqlite3` module.

### 10.1 Understand the actual schema

The application creates two tables:

```sql
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK(id=1),
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL
);
```

The settings table has one row. Its `data` column contains serialized non-secret settings. Each note has its own row and a JSON body; `created_at` is also stored separately for ordering. This is a small application design, not an ORM model with one SQL column per preference.

`CREATE TABLE IF NOT EXISTS` permits subsequent launches to open the same database. `PRAGMA user_version=1` marks the current schema version; a future schema change would need an actual migration strategy rather than merely changing this number.

The store enables write-ahead logging and uses transactions for writes. `with self.db:` commits a successful write block or rolls it back on an exception. SQL parameters are passed separately from SQL strings, such as `WHERE id=?`, rather than interpolating user text into SQL syntax.

### 10.2 Try storage without the desktop

This example uses a temporary directory and leaves the real notes untouched:

```sh
uv run python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from mactranslator.backend.storage import Store
from mactranslator.contracts import NoteCreate

with TemporaryDirectory() as directory:
    database = Path(directory) / "learning.sqlite3"
    store = Store(database)
    note = store.add_note(NoteCreate(source_text="Hello", translated_text="你好"))
    store.update_note(note.id, "My first saved note")
    store.close()

    reopened = Store(database)
    assert reopened.notes()[0].user_note == "My first saved note"
    reopened.close()
    print("The note survived closing and reopening the database")
PY
```

### 10.3 Know the ownership rule

Normal API handlers execute on the backend event loop and access this one store. `check_same_thread=False` disables SQLite's default Python thread check for the way this application/test harness opens the connection; it does not make arbitrary simultaneous use from many threads a good design.

The AppKit desktop does not directly update the database. It sends API requests. That gives one place to validate changes and preserve storage behavior.

The finished application's default database is:

```text
~/Library/Application Support/Text Selection Translation Python/translator.sqlite3
```

This is separate from the Swift app's notes. The tutorial demo in Chapter 12 uses yet another database, under `tutorial/.demo-data/`.

## 11. Keep API keys in Keychain

You already added [credentials.py](../src/mactranslator/backend/credentials.py). Read it now alongside `Store.save_with_credentials()`.

### 11.1 A small interface makes the code replaceable

The `Credentials` protocol describes two methods:

```python
def get(self, account: str) -> str: ...
def set(self, account: str, value: str) -> None: ...
```

This is an interface excerpt, not an implementation to run. The real adapter uses macOS Security APIs. Tests and the tutorial implement the same interface using a Python dictionary. The backend is given whichever adapter it should use.

This technique is **dependency injection**: supply the object that performs a job rather than hard-coding it everywhere. It is why you can test the backend without reading your actual Keychain.

### 11.2 Understand the real Keychain adapter

The production service name is `com.example.mactranslator.python.credentials.v1`. Each provider's UUID is its account name within that namespace.

- `SecItemCopyMatching` reads an existing generic-password item.
- `SecItemUpdate` updates an item.
- If the item does not exist, `SecItemAdd` creates it.
- `SecItemDelete` removes a key when the user explicitly clears it.

Keychain APIs return status codes. The adapter maps missing entries to an empty key and inaccessible entries to `CredentialError`. Queries use the fail-without-authentication-UI option; this avoids repeatedly opening password dialogs while the app starts at login. The settings UI can ask the user to re-enter an unavailable key.

### 11.3 Trace saving settings

When the API receives settings:

1. Validate the complete request as `Settings`.
2. For each explicitly supplied key, write or clear its Keychain entry.
3. Maintain `has_api_key`, which reveals presence rather than the secret.
4. Serialize non-secret settings into SQLite.
5. Attempt cleanup of keys belonging to removed providers.
6. Return sanitized settings to the desktop.

Omitting `api_key` means preserve the saved key. Sending `"api_key": ""` means clear it. Those operations must remain distinct in your UI.

SQLite and Keychain are different storage systems. This implementation does not offer one atomic transaction spanning them: an error after an earlier key update can leave that key updated even if later operations fail. Understand that limit if you later add bulk configuration import or transactional requirements.

**Checkpoint:** explain why the Keychain interface is injectable, why an API response never returns the key, and why a blank field in the settings editor must not accidentally erase a saved key.

## 12. Assemble and exercise the real FastAPI backend

Add [api.py](../src/mactranslator/backend/api.py):

```sh
cp "$TRANSLATOR_REFERENCE/src/mactranslator/backend/api.py" src/mactranslator/backend/
uv run python -c "from mactranslator.backend.api import create_app; print('Backend imports work')"
```

### 12.1 Why this module has a factory

The real service is constructed with `create_app(token, database, credentials, transport, experimental)`. A factory is a function that constructs and returns an application. It accepts per-run configuration and replaceable components.

Unlike Lesson 1, `api.py` does not define a module-level variable called `app`. Therefore, `uvicorn mactranslator.backend.api:app` is the wrong command. The full desktop supplies the factory arguments and starts Uvicorn itself. The tutorial wrapper below supplies its own arguments.

### 12.2 Startup and shutdown with lifespan

Inside the factory, `lifespan()` opens a `Store` and an HTTPX client. It stores references on `app.state`, makes the service available at `yield`, and closes resources as the lifespan context exits.

In an async context manager, code before `yield` prepares resources and code after it handles shutdown. This is FastAPI's lifespan pattern. [Lifespan events](https://fastapi.tiangolo.com/advanced/events/)

The app intentionally has no public documentation endpoints. A dependency authenticates every registered API operation, and exception handlers sanitize validation errors and Keychain failures.

### 12.3 The local token is different from a provider key

The finished desktop creates a random token for its own local API each time it starts. It sends:

```text
Authorization: Bearer <the-local-runtime-token>
```

This token authorizes the desktop to use FastAPI. Provider keys authorize FastAPI to call external model services. They are separate credentials with separate purposes.

The service binds to loopback, rejects requests containing browser-origin/fetch headers, and does not enable CORS. It is intended for the native client, not a public web deployment. These controls are not a substitute for OS process isolation against arbitrary malware running as the same user.

### 12.4 Install the isolated demo wrapper

Copy the two companion files:

```sh
cp "$TRANSLATOR_REFERENCE/tutorial/demo_backend.py" tutorial/
cp "$TRANSLATOR_REFERENCE/tutorial/demo_client.py" tutorial/
```

[demo_backend.py](../tutorial/demo_backend.py) constructs the **real** backend using a mock HTTP transport and an in-memory credential adapter. It seeds two fake translation providers and uses `tutorial/.demo-data/translator.sqlite3`. It never calls a real model or Keychain.

The demo uses the fixed, non-secret token `tutorial-local-only` solely so that you can type the examples. Do not replace the finished desktop's random-token mechanism with it. Changing an endpoint in this demo does not enable real network calls: all provider traffic still goes through `MockTransport`.

From your learning folder in Terminal A:

```sh
uv run python -m uvicorn tutorial.demo_backend:create_demo_app \
  --factory --host 127.0.0.1 --port 8765
```

`--factory` tells Uvicorn to call the named function to obtain the app.

### 12.5 Check authentication, configuration, and streaming

In Terminal B:

```sh
curl -i http://127.0.0.1:8765/api/v1/health
```

Expected: **401**. The same request with the demo token succeeds:

```sh
curl -s http://127.0.0.1:8765/api/v1/health \
  -H 'Authorization: Bearer tutorial-local-only'
```

Expected:

```json
{"ready":true,"experimental_dictionary":false}
```

Read the seeded settings:

```sh
curl -s http://127.0.0.1:8765/api/v1/settings \
  -H 'Authorization: Bearer tutorial-local-only'
```

The response contains `Demo fast` and `Demo slow`, in that order, with no `api_key` fields. Start a translation:

```sh
curl -N http://127.0.0.1:8765/api/v1/translate \
  -H 'Authorization: Bearer tutorial-local-only' \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello"}'
```

Both providers return `这是演示输出，并非真实翻译。` in pieces. This means “This is demonstration output, not a real translation.” It deliberately does not depend on the submitted text.

To consume the same stream using Python, run in Terminal B:

```sh
cd "$HOME/Developer/translator-learning"
uv run python -m tutorial.demo_client
```

The [client source](../tutorial/demo_client.py) calls health, opens a streaming POST response, parses events, and prints their type/provider/text. This is a small version of the desktop's HTTP client.

### 12.6 Exercise note persistence

```sh
curl -s http://127.0.0.1:8765/api/v1/notes \
  -H 'Authorization: Bearer tutorial-local-only' \
  -H 'Content-Type: application/json' \
  -d '{"source_text":"Hello","translated_text":"你好","user_note":"A tutorial note"}'

curl -s http://127.0.0.1:8765/api/v1/notes \
  -H 'Authorization: Bearer tutorial-local-only'
```

The first command creates a note and returns an ID. The second lists it. Stop and restart the demo server; list notes again to see that the file preserves them. Repeating the create command intentionally creates another note.

For an annotation edit, replace `NOTE_UUID_FROM_RESPONSE` with that returned ID:

```sh
curl -s -X PATCH http://127.0.0.1:8765/api/v1/notes/NOTE_UUID_FROM_RESPONSE \
  -H 'Authorization: Bearer tutorial-local-only' \
  -H 'Content-Type: application/json' \
  -d '{"user_note":"I edited this annotation"}'
```

Read that note, then delete the tutorial note when you are finished:

```sh
curl -s http://127.0.0.1:8765/api/v1/notes/NOTE_UUID_FROM_RESPONSE \
  -H 'Authorization: Bearer tutorial-local-only'

curl -i -X DELETE http://127.0.0.1:8765/api/v1/notes/NOTE_UUID_FROM_RESPONSE \
  -H 'Authorization: Bearer tutorial-local-only'
```

Replace the same placeholder in both commands. Deletion returns **204 No Content**; requesting that ID afterwards returns **404**.

### 12.7 Read the production stream generator

It extends Lesson 2 in several ways:

| Event | Meaning |
|---|---|
| `start` | Ordered metadata for participating providers |
| `delta` | Append text to one provider's result |
| `dictionary` | Structured dictionary lookup result |
| `provider_done` | One provider completed successfully |
| `provider_error` | One provider failed; others can continue |
| `done` | All participating providers reached a terminal state |

Every event carries the request ID. Provider-specific events also carry the provider ID. The queue is bounded at 128 events; a ten-second idle interval produces an SSE comment heartbeat. In `finally`, every producer is cancelled and awaited so an abandoned request does not leave detached provider work.

An error before the stream starts can use a normal HTTP error status. After the stream has started, a provider failure is represented by an event within that stream. The client must interpret both kinds of failure.

The complete route list and request bodies are in the [README API table](../README.md#api-contract). `PUT /settings` replaces the configuration rather than applying an arbitrary partial patch. `PATCH /notes/{id}` updates only the annotation field. A 204 deletion response has no JSON body.

**Checkpoint:** you have exercised the real backend with no API key, tested a 401 response, observed two provider streams, and saved a note across a server restart. Stop the demo server before continuing.

## 13. Build the native desktop foundation

You now have a usable HTTP service. The remaining chapters add the native client that makes it a macOS selection translator.

Add the UI helpers and native adapters:

```sh
cp "$TRANSLATOR_REFERENCE/src/mactranslator/desktop/widgets.py" src/mactranslator/desktop/
cp "$TRANSLATOR_REFERENCE/src/mactranslator/desktop/keycodes.py" src/mactranslator/desktop/
cp "$TRANSLATOR_REFERENCE/src/mactranslator/desktop/native.py" src/mactranslator/desktop/
uv run python -c "import AppKit; from mactranslator.desktop import native, widgets; print('Native imports work')"
```

These modules do not automatically grant permissions or start capturing text.

### 13.1 Understand PyObjC syntax

Native Objective-C APIs have selectors such as `setTitle:`. PyObjC commonly exposes the colon as an underscore, producing `setTitle_(...)` in Python. Multiple argument positions produce multiple underscores, such as `initWithFrame_pullsDown_(frame, False)`.

`SomeClass.alloc().init()` follows Objective-C allocation/initialization conventions. Do not replace it with an ordinary Python constructor unless that API explicitly supports it. Some APIs with output parameters return tuples such as `(success, error)` or `(status, value)`; the existing wrappers show the exact expected usage.

### 13.2 Build reusable controls

[widgets.py](../src/mactranslator/desktop/widgets.py) creates labels, text fields, buttons, checkboxes, dropdowns, text areas, and windows. These functions centralize repetitive AppKit setup so the settings and notes controllers can focus on behavior.

AppKit rectangles use an origin and a size. A window's content view is the area inside its title bar. Text views sit inside scroll views so long translations remain usable without a constantly expanding window.

The Markdown renderer parses text into tokens and converts them into native attributed strings: font, emphasis, links, code, and table text. It disables HTML parsing. It is not loading model output as a web page. Table text accounts for wide CJK characters when calculating padding.

### 13.3 Keep callbacks alive

The `Action` class in [native.py](../src/mactranslator/desktop/native.py) is an `NSObject` target with an `invoke_` method. `bind()` attaches it to a control and retains it in a controller's `targets` list.

That retained reference matters because Python manages object lifetimes. The button still needs its callback target after the helper function has returned.

The later `main()` function keeps the application delegate in a live local variable for the duration of the event loop; controllers retain their own callback/delegate objects too. Avoid creating delegates as throwaway locals whose lifetime ends before their callbacks are needed.

**Checkpoint:** the native import check works on your Mac. You are not starting the complete UI yet because its controllers and coordinator have not been added.

## 14. Connect AppKit to the backend

Add [runtime.py](../src/mactranslator/desktop/runtime.py):

```sh
cp "$TRANSLATOR_REFERENCE/src/mactranslator/desktop/runtime.py" src/mactranslator/desktop/
```

### 14.1 Two event loops with different responsibilities

AppKit's main loop handles mouse events, drawing, and native callbacks. The asyncio loop handles Uvicorn and HTTPX. Blocking the AppKit main thread while waiting for a provider would make the app feel frozen.

`BackendRuntime.start()` creates a worker thread. That thread calls `asyncio.run(self._serve())`. `_serve()`:

1. Creates a socket bound to `127.0.0.1` with port `0`.
2. Reads back the free port assigned by the OS.
3. Constructs FastAPI with a fresh random token.
4. Starts Uvicorn on the already-bound socket.
5. Creates the desktop's authenticated HTTPX client.
6. Waits for service startup and a successful health check.
7. Completes the startup future so the UI can enable translation.

Port `0` avoids hard-coding a port that another application may occupy. The normal desktop app consequently does **not** listen at the tutorial's fixed port 8765.

### 14.2 Send work to the asyncio thread

The runtime's `submit(coroutine)` uses `asyncio.run_coroutine_threadsafe`. It returns a `concurrent.futures.Future`, which represents a result that may arrive later.

The coordinator later attaches a completion callback to that future. It does not call `.result()` and wait on the main thread during normal UI operations. Calling `.result()` inside a completion callback is different: at that point the future is already done.

### 14.3 Send results back to AppKit

The coordinator uses `AppHelper.callAfter(...)` for UI updates. PyObjC documents it as scheduling a function on the main thread and returning immediately. [AppHelper documentation](https://pyobjc.readthedocs.io/en/latest/api/module-PyObjCTools.AppHelper.html)

For a worker coroutine that needs a result from a native operation, `native.on_main(function)` bridges both directions: schedule the operation on AppKit, then resolve an asyncio future on its own loop. It checks whether the future has already been cancelled before setting its result.

A reliable mental model is:

```text
main thread: user action
    -> runtime.submit(coroutine)
worker thread: await HTTP / receive streaming events
    -> AppHelper.callAfter(update_window)
main thread: redraw and remain responsive
```

### 14.4 Avoid a shutdown deadlock

If the main thread waits for the worker while the worker is awaiting `on_main(...)`, neither can finish. The coordinator defers termination, waits asynchronously for note saves, and replies to AppKit once it can quit. The runtime then closes its client, server, and database during shutdown.

Do not put `asyncio.run(...)` inside each button handler or start another Uvicorn instance for each translation. One runtime owns the service for the lifetime of the desktop process.

## 15. Implement selected-text capture and global shortcuts

The implementation is already in the `native.py` you added. Read its capture functions, `Hotkeys`, and `SelectionWatcher` together with the pure helpers in `policies.py`.

### 15.1 Prefer reading the selection directly

`selected_text()` creates an Accessibility system-wide element, asks for the focused UI element, then asks that element for `kAXSelectedTextAttribute`.

Some applications expose this text; some do not. Permission is necessary but does not guarantee that every document or application supports the attribute. That is why a second capture method exists.

### 15.2 Fall back to simulated Copy

The fallback records the existing clipboard items, sends Command+C, and waits for a new clipboard generation and its text. It preserves every available item type when making a snapshot, rather than assuming the old clipboard contains only a string.

`NSPasteboard.changeCount()` identifies the clipboard generation. The algorithm polls because some applications declare clipboard types before supplying their actual data. A generation change alone does not guarantee that readable text has arrived.

The implementation allows two copy attempts, but only retries if the pasteboard has not changed. Each attempt polls up to 100 times at 15 ms intervals. Before capture, it waits briefly for mouse release and selection settling.

### 15.3 Restore only the clipboard generation you observed

Imagine this sequence:

```text
clipboard generation 10: the user's previous clipboard
clipboard generation 11: the synthetic Copy result
clipboard generation 12: the user manually copies something else
```

You must not restore the saved contents over generation 12. `should_restore(observed, current)` only allows restoration when the observed copy generation still equals the current one.

Cancellation also needs this discipline. An interrupted selection operation may still have modified the clipboard, so the capture helper preserves enough information for safe restoration where possible. There is no unconditional delayed restore after a timeout.

### 15.4 Register global shortcuts

`Hotkeys` wraps Carbon's hotkey registration functions with `ctypes`. The wrapper defines the C structures, argument/result types, and callback signature. The code retains the C callback object and unregisters references when settings change or the app exits.

Do not guess these C signatures: a wrong pointer size or callback declaration can crash the process. Use the complete wrapper, then study its signature table separately.

The settings contract persists NSEvent modifier bits. The registration method maps them to Carbon flags. Default key codes correspond to D and O, with Option and Option+Shift modifiers. [keycodes.py](../src/mactranslator/desktop/keycodes.py) provides readable labels for recorded physical key codes.

### 15.5 Detect likely selections

`SelectionWatcher` observes global mouse events. It treats a real drag of at least two points or a double/triple click as a likely selection, then delays briefly before offering the floating icon.

This is a heuristic. Seeing an icon does not prove the application can read the selected text. The actual capture happens when the user activates translation. The watcher also helps dismiss existing UI on outside clicks.

**Checkpoint:** you can explain why this feature needs native APIs, why it has two capture paths, and why restoring the clipboard unconditionally would be incorrect. The live permission-dependent test comes after the full app is assembled.

## 16. Build the floating icon and translation popup

Add [popup.py](../src/mactranslator/desktop/popup.py):

```sh
cp "$TRANSLATOR_REFERENCE/src/mactranslator/desktop/popup.py" src/mactranslator/desktop/
```

### 16.1 Preserve the selection while clicking the icon

The little **译** button lives inside `FloatingPanel`, a nonactivating `NSPanel`. Its `canBecomeKeyWindow` and `canBecomeMainWindow` methods return `False`. Clicking it must not first activate your app and destroy the source application's selection.

The callback hides the icon, retains its screen location, and starts capture. Only after capture does the larger translation popup become the key window. The icon disappears after five seconds; a generation counter prevents an old timer from hiding a newly shown icon.

### 16.2 Position once, then stream into the window

`screen_at()` identifies the display containing the pointer. `fit_frame()` constrains the window to that display's visible frame, accounting for the menu bar and Dock. Displays may have negative coordinates; do not assume the desktop starts at `(0, 0)` on every monitor.

The popup has a fixed initial size and a scrolling text area. Placement happens in `show()`. Streaming calls `render()`, which updates text and preserves the scroll origin without repositioning the window. This is why a dragged popup stays where the user put it while more text arrives.

### 16.3 Keep display order independent of arrival order

The `start` event creates result entries in configured provider order. A `delta` looks up the entry by provider ID and appends to its output. It does not append a new card each time a provider responds.

Before accepting any event, the popup checks its request ID. A callback from a cancelled older translation cannot modify the current translation. Rendering is coalesced over approximately 40 ms, avoiding a complete attributed-text rebuild for every tiny chunk.

`widgets.attributed_markdown()` converts Markdown tokens into native attributed strings, including table content. The text view remains selectable. The dropdown selects which source/result the **复制** and **朗读** buttons operate on; those buttons use that complete entry, independently of a manually highlighted substring.

### 16.4 Save a usable result, in configured order

The **保存笔记** button appears when local notes are enabled. Saving is a user action; merely finishing translation does not create a note automatically.

`can_save()` waits until the first usable result in configured order is settled: an earlier loading provider blocks saving, but later providers may still be running once an earlier usable result is complete. `first_usable()` chooses the first nonempty, error-free translation in that order. A fast second provider does not displace a usable first provider. If all providers finish without a usable translation, the existing policy can still save the source alone.

**Checkpoint:** trace `show → event → render → save` in the file. Identify the request-ID guard and confirm that `render()` does not set the window's frame.

## 17. Add screenshot OCR

Add [ocr.py](../src/mactranslator/desktop/ocr.py):

```sh
cp "$TRANSLATOR_REFERENCE/src/mactranslator/desktop/ocr.py" src/mactranslator/desktop/
```

OCR means *optical character recognition*: turning text visible in an image into a string. It stays in the desktop layer because the image comes from macOS and Vision performs recognition locally.

The capture path is:

1. Create a selection overlay on each display, on the main thread.
2. Let the user drag a rectangle; Escape cancels.
3. Record the selected display and rectangle, then close the overlays.
4. Ask ScreenCaptureKit for the display's image region, excluding this application's windows.
5. Run Vision recognition in a worker using `asyncio.to_thread()`.
6. Send the recognized text through the same translation flow as an ordinary selection.

### 17.1 Distinguish points, pixels, and coordinate origins

AppKit positions are measured in points. A Retina display can have more than one pixel per point. Screen-capture coordinates also need the correct vertical origin. `ocr_rect()` handles the conversion; the ScreenCaptureKit configuration receives a source rectangle and pixel width/height separately.

Multiplying every coordinate by two is incorrect for mixed-density displays. Use the selected display and content filter's actual scale. Test this conversion as a pure function before checking it on multiple displays.

### 17.2 Bridge callbacks into asyncio

ScreenCaptureKit's methods call completion handlers. `callback_result()` creates an asyncio future, starts the native operation, and returns by awaiting that future. The native callback uses `loop.call_soon_threadsafe()` to deliver the result or exception on the correct loop. It checks whether the future is already complete, because cancellation can arrive first.

Vision is synchronous. The code configures accurate recognition, filters preferred languages against those supported by the framework, and groups recognized observations into rows. It raises a readable error when no text is found.

The actual PyObjC call uses `NSDictionary.dictionary()` for the Vision handler's options. Keep that bridge detail when reproducing the implementation; superficially equivalent Python values are not always accepted by every native API signature.

Screen Recording permission is granted by macOS, not by FastAPI. Generated-image OCR tests verify recognition but cannot prove that a user has granted screen capture permission. We test that separately in Chapter 21.

## 18. Add speech and the experimental dictionary

The service implementations are already in [providers.py](../src/mactranslator/backend/providers.py). The playback code is in the coordinator you will add next.

### 18.1 Separate synthesis from playback

**Synthesis** produces audio bytes. **Playback** sends those bytes to the speakers.

For cloud speech, the desktop calls `POST /api/v1/speech` with a provider UUID, text, and optional language. FastAPI loads that provider and its credential, requests audio, and returns audio bytes. The desktop constructs an `AVAudioPlayer` and retains it while it plays.

The two cloud protocols have different request shapes:

| Provider kind | Request style in this implementation |
|---|---|
| `openai_tts` | OpenAI-compatible audio speech endpoint, with model, input, voice, response format, and optional instructions |
| `dashscope_tts` | DashScope speech endpoint with nested input/parameters; downloads returned audio when the response provides an audio URL |

The DashScope download does not forward the provider authorization header to the returned audio host. Raw PCM needs a container for playback: the existing policy wraps its assumed 24 kHz, mono, 16-bit samples into WAV. If you add a provider with another PCM layout, update that policy and its tests together.

A provider's accepted models, voices, formats, and instruction fields vary. Use values documented by your selected service; a value in an editable default is not proof that your account supports it.

### 18.2 Keep native speech available

With no enabled cloud TTS provider, **朗读** uses macOS speech through `AVSpeechSynthesizer`. With one cloud provider, it calls that provider. With multiple cloud providers, a menu offers them in configured order plus native speech.

The app detects the text's dominant language for native voice selection. Its text policy normalizes Unicode, decodes HTML entities, and trims whitespace; it does not fully remove Markdown syntax. Stop cancels the pending cloud request and stops current playback; a generation counter prevents a late audio response from playing after Stop.

Cloud failures are shown as errors; this implementation does not automatically retry every cloud failure using a local voice. The native path is the fallback when no cloud provider is enabled and is also available from the multiple-provider menu.

### 18.3 Gate experimental dictionary requests in the service

Microsoft dictionary support uses provider kind `dictionary`, with its own region and source/target language configuration. The desktop exposes it only in experimental mode, and the backend independently gates it.

Normal launches do not send dictionary requests, including when a previous experimental launch saved a dictionary provider. The experimental switch is:

```sh
make beta-run
```

This uses the same Python-edition database as a normal Python launch. It is not a separate beta app identity. Keep this feature disabled while learning the ordinary translation flow; the tutorial mock server simulates translation only.

## 19. Complete settings, notes, startup, and shutdown

Add the remaining desktop modules and entry points:

```sh
cp "$TRANSLATOR_REFERENCE/src/mactranslator/desktop/settings.py" src/mactranslator/desktop/
cp "$TRANSLATOR_REFERENCE/src/mactranslator/desktop/notes.py" src/mactranslator/desktop/
cp "$TRANSLATOR_REFERENCE/src/mactranslator/desktop/app.py" src/mactranslator/desktop/
cp "$TRANSLATOR_REFERENCE/src/mactranslator/desktop/smoke.py" src/mactranslator/desktop/
cp "$TRANSLATOR_REFERENCE/launcher.py" .
cp "$TRANSLATOR_REFERENCE/Makefile" .
```

### 19.1 Edit configuration without reading secrets back

[settings.py](../src/mactranslator/desktop/settings.py) owns General and provider controls. It loads `GET /settings`, populates controls, and submits a full replacement using `PUT /settings`.

Provider edits preserve IDs. Moving a provider changes the list order. Switching the selected provider first collects the current controls so unsaved form edits are not silently discarded.

A masked key input starts blank even for an existing credential. Blank means “keep the saved key”; **清除 Key** explicitly requests deletion. The editor keeps entered keys separately and inserts them into the outbound dictionary because model serialization excludes `api_key`.

Shortcut recording temporarily captures key events. Escape cancels; a valid key plus modifiers updates the contract. Applying settings unregisters old hotkeys and registers the new enabled ones. Translation, OCR, and floating-icon triggers each have their own enable switch.

Connection testing first saves the edited settings, then tests the saved provider ID. TTS testing uses the speech route for an audible preview rather than the translation test route.

### 19.2 Save note edits without races

[notes.py](../src/mactranslator/desktop/notes.py) lists persisted notes and displays source, translation, and an editable annotation. Text edits wait 500 ms before saving, so normal typing does not send a request for each keystroke.

A timer alone is insufficient. Consider typing A, starting its save, then typing B while A is in flight. A's response must not overwrite B in the editor. This implementation tracks edit generations, serializes writes for the same note, and preserves newer local edits when an older response arrives.

Switching notes, closing the window, and quitting flush pending changes. A failed quit-time flush leaves the application open and shows a message so the user can retry. Deletion is an explicit API request; hiding a window does not delete its notes.

### 19.3 Follow the coordinator's startup sequence

[app.py](../src/mactranslator/desktop/app.py) is the composition root: the place where the pieces are connected.

```text
main()
  -> acquire the Python edition's single-instance lock
  -> create NSApplication and its delegate
  -> construct TranslatorApp and run the AppKit event loop
  -> start BackendRuntime on its worker thread
  -> wait for authenticated backend health
  -> fetch settings and configure native triggers
  -> enable translation actions
```

The app uses accessory activation policy and a menu bar status item, so a missing Dock icon is expected. A backend startup error produces a visible failure state and retry action. Actions that need the backend remain unavailable until readiness succeeds.

The status menu includes selected-text translation, clipboard translation, OCR, settings, notes, permission guidance, and Quit. Clipboard translation is useful for checking the service before troubleshooting Accessibility capture.

### 19.4 Trace one complete translation

When a selection is captured, `translate()` cancels the previous translation, makes a fresh request UUID, opens the popup, and submits `runtime.stream(...)`. The runtime sends HTTP and parses SSE; the coordinator's supplied callback schedules each UI event on AppKit's main thread.

Closing the popup or starting another request cancels that streaming operation. Closing the HTTP response causes service-side cleanup to cancel upstream provider tasks. The request-ID guard is still needed because a main-thread callback could already be queued when cancellation occurs.

### 19.5 Close resources deliberately

Quit stops event monitors and hotkeys, dismisses the popup, cancels capture/OCR/speech, and flushes notes. The AppKit delegate defers termination while saves finish. After the event loop exits, `runtime.stop()` joins the service shutdown from a point that no longer blocks a pending main-thread UI callback.

FastAPI's lifespan closes the shared HTTPX client and SQLite store. The worker releases the listening socket. A normal quit should not leave another server process running; the service was a thread inside the application process.

**Checkpoint:** every production module is now present. From the learning directory, run:

```sh
uv run python -m compileall -q src
uv run python -c 'import mactranslator.desktop.app; print("Desktop imports work")'
```

Importing verifies module availability. It does not launch the event loop or test macOS permissions.

## 20. Run the full desktop app

Stop any tutorial Uvicorn process with Control+C in its own Terminal. It is separate from the automatically managed desktop service.

From the learning project:

```sh
cd "$TRANSLATOR_LAB"
make run
```

Look for **译 Py** in the menu bar. Open **设置…**. A fresh installation has no translation providers; you must add one before real translation can work.

### First provider configuration

1. Open the provider settings and add a provider of kind `translation`.
2. Give it a name you will recognize in the result list.
3. Enter your provider's actual OpenAI-compatible base endpoint, for example an address ending in `/v1`.
4. Enter a model identifier available on that service and your account.
5. Enter its API key if required. A local service may not require one.
6. Enable the provider and choose **保存并测试连接 / 朗读**.
7. Set the target language and save your general preferences.

`https://example.com/v1` and the tutorial's `.invalid` URL are examples, not working model services. Do not copy them into the real configuration expecting a translation. The mock tutorial server cannot make the desktop's real provider calls work automatically; it is a separate learning exercise.

First try the menu's clipboard translation after copying a short sentence. Then select text in an editor and press **Option+D**. On the first permission-dependent attempt, follow the application's Accessibility guidance. For OCR, use **Option+Shift+O**, grant Screen Recording if requested, restart as directed by macOS, and drag over visible text.

The old Swift application can compete for the same shortcuts. Quit it while testing these defaults, or assign different shortcuts. The Python learning copy and the Python reference copy also share one application identity and single-instance lock; run only one at a time.

### Useful interface labels

| Label | Meaning |
|---|---|
| 设置 | Settings |
| 后端 | Provider/backend configuration |
| 原文 | Source text |
| 复制 | Copy the chosen source/result |
| 朗读 / 停止 | Speak / stop speech |
| 保存笔记 | Save a note |
| 本地笔记 | Enable local notes |
| 上移 / 下移 | Move a provider up/down |
| 辅助功能授权 | Accessibility permission guidance |

Enable **本地笔记** to show the popup's save action. Finish a translation, save it, open the notes window, and add an annotation. Quit using the menu and relaunch to check persistence.

The real app stores data here:

```text
~/Library/Application Support/Text Selection Translation Python/translator.sqlite3
```

Credentials are stored separately in the `com.example.mactranslator.python.credentials.v1` Keychain service. Neither location is the tutorial's `.demo-data` directory. Removing or rebuilding the learning source directory does not reset the real application's data.

## 21. Test and debug it

Copy the production tests:

```sh
cp "$TRANSLATOR_REFERENCE"/tests/*.py tests/
make check
make test
```

`make check` runs Ruff over `src` and `tests`, then compiles Python source. `make test` runs pytest. The reference suite at the time of this guide contains 41 tests. Read the reported pass/skip counts; a skipped native test is not evidence that a native feature passed on your machine.

### 21.1 Understand the test layers

| Layer | Examples | Needs live credentials? |
|---|---|---|
| Pure policy tests | Endpoint rules, message layouts, clipboard generations, geometry, note ordering | No |
| Mock-provider tests | Fragmented SSE, concurrent streams, one failed provider, cancellation, empty output, retries, TTS formats | No |
| API/storage tests | Authentication, browser rejection, secret exclusion, inaccessible credentials, SQLite persistence, dictionary gating | No |
| Runtime/desktop-state tests | Loopback lifecycle, stale popup events, note autosave races | No; some require macOS frameworks |
| Native smoke check | Window construction, generated-image OCR, hotkey registration | No |
| Manual acceptance | Selection across applications, real screenshots, audio, login startup | Some do |

`httpx.MockTransport` supplies fake provider responses while exercising the real request builder. FastAPI's `TestClient` runs requests in-process. Enter it with `with TestClient(app) as client:` so startup/shutdown lifespan runs; merely constructing it is insufficient for this application's initialized store/client.

A test of fragmented SSE intentionally splits data at inconvenient boundaries. A concurrency test must prove one slow provider does not block another. A note-race test must exercise an older save response arriving after a newer edit. These are behavior tests, not assertions that a private function was called once.

### 21.2 Write your first API test

Create `tutorial/test_lesson_01.py`:

```python
from fastapi.testclient import TestClient
from tutorial.lesson_01_api import app


def test_translation_input_and_response():
    with TestClient(app) as client:
        response = client.post("/translate", json={"text": "Hello"})
        assert response.status_code == 200
        assert response.json()["output"] == "DEMO ONLY: Hello"
        assert client.post("/translate", json={"text": ""}).status_code == 422
```

Run that particular file explicitly:

```sh
uv run pytest -q tutorial/test_lesson_01.py
```

The production project's default pytest configuration targets `tests/`, so the explicit path matters for this lesson. This tiny test uses the first lesson's `/translate`, not the authenticated production `/api/v1/translate`.

### 21.3 Run the native smoke check

Quit the regular app first, then run:

```sh
.venv/bin/python -m mactranslator.desktop.app --smoke-test /tmp/translator-learning-native-check
cat /tmp/translator-learning-native-check/report.json
```

The check constructs native windows, renders sample content, recognizes a generated image with Vision, registers/releases a temporary test hotkey, and starts/stops a backend with temporary storage. It does not capture the user's screen, use provider keys, or change login-item registration.

Its diagnostic images are not a substitute for viewing the app: some modern layer-backed controls may be missing from offscreen renders.

### 21.4 Perform the permission-dependent checks yourself

Use the packaged application from the next chapter for stable permission identity. Check:

- Selection in an editor, browser, and PDF reader, including an application that needs Copy fallback.
- A new manual copy during capture: its clipboard content must survive restoration.
- Floating-button focus, popup dragging, edge placement, and external displays.
- Escape/outside-click dismissal and starting a second translation while the first streams.
- OCR cancellation, permission denial, Retina/external-display regions, and mixed-language text.
- Native speech, your configured cloud speech protocols, and stopping pending speech.
- Rapid annotation edits followed by switching, closing, quitting, and relaunching.
- Enabling/disabling launch at login, then an actual logout/login cycle.

These depend on your device, permissions, and services. Automated tests cannot certify them by themselves. The reference implementation's earlier native and packaged smoke checks passed; its complete interactive acceptance checklist remains a manual task.

### 21.5 Read a traceback from the bottom up

When a command fails, keep the Terminal output. The final exception states what failed; the preceding frames show how it was reached. Find the lowest frame belonging to `mactranslator` or `tutorial`, inspect that line, and check its inputs.

Useful distinctions: an import error is environment/package setup, an HTTP 422 is input validation, a provider HTTP 401 usually concerns that provider's credential, and a local API HTTP 401 concerns the per-launch bearer token. Avoid printing whole settings request bodies while debugging: they can contain newly entered keys.

## 22. Build a standalone macOS application

Add the packaging definition:

```sh
cp "$TRANSLATOR_REFERENCE/packaging/setup.py" packaging/
make app
```

Run this from the learning directory. The target removes that directory's generated `build/` and `dist/` outputs before rebuilding. It does not remove the Swift build or the application's stored notes.

py2app bundles the launcher, application package, Python runtime, and required dependencies into a macOS app bundle. End users then launch the bundle without installing uv or Python. [py2app tutorial](https://py2app.readthedocs.io/en/latest/tutorial.html)

The result is:

```text
translator-learning/
└── dist/
    └── Text Selection Translation Python.app/
        └── Contents/
            ├── Info.plist
            ├── MacOS/
            ├── Frameworks/
            └── Resources/
```

### 22.1 Understand the packaging settings

[packaging/setup.py](../packaging/setup.py) declares `launcher.py` as the application entry point, includes modules that dynamic imports might otherwise miss, and excludes development tools. The plist supplies the distinct Python bundle identifier, macOS 14 minimum, display name, and menu-bar-only `LSUIElement` setting.

The translation prompt is package data declared in `pyproject.toml`; it must be bundled too. A program working from its source tree can still fail as a bundle if it opens source-relative resources incorrectly or omits dynamically imported dependencies.

This repository includes a narrow workaround for py2app 0.28.10 and uv's Python: py2app expects zlib to be a separate extension, while that Python build incorporates it into the shared library. The subclass skips copying only the nonexistent zlib extension; it still bundles Python's shared library. Do not generalize this workaround into suppressing arbitrary missing-module errors.

The build runs from `packaging/` so py2app does not reinterpret the main project's dependency metadata as legacy setup arguments.

### 22.2 Sign and launch locally

For local ad-hoc signing:

```sh
make sign
open "dist/Text Selection Translation Python.app"
```

`make sign` also verifies the signature. Ad-hoc signing does not establish a Developer ID identity or complete notarization. For a stable certificate already present in your Keychain, supply its exact identity name:

```sh
security find-identity -v -p codesigning
make sign SIGN_ID="YOUR EXISTING CODE SIGNING IDENTITY"
```

Replace the placeholder with an identity actually listed on your machine. The command does not create a certificate. This chapter produces a local application bundle; shipping to other users with Developer ID signing, notarization, and distribution packaging requires a separate release workflow.

The existing build is architecture-specific. The reference app was checked on Apple Silicon/arm64; an Intel build must be built and tested with compatible x86_64 Python and dependencies. A macOS 14 deployment target alone does not make an arm64 binary run on Intel.

### 22.3 Test the bundled runtime

Quit other Python translator instances, then run the bundle's executable directly:

```sh
"dist/Text Selection Translation Python.app/Contents/MacOS/Text Selection Translation Python" \
  --smoke-test /tmp/translator-learning-bundle-check
cat /tmp/translator-learning-bundle-check/report.json
```

This tests the bundled Python, not `.venv/bin/python`. Keep source and bundle smoke results separate. Successful source tests alone do not prove that packaging included everything.

For everyday use, copy the finished app into Applications using Finder. Grant Accessibility and Screen Recording to this Python app and restart it as needed. Configure launch at login from its settings; macOS may require approval in Login Items. Use the packaged app for this integration, not a transient interpreter in a learning folder.

## 23. Troubleshooting

| Symptom | Likely cause and next action |
|---|---|
| `uv: command not found` | Finish uv installation and reopen Terminal so its executable is on PATH. |
| `No module named fastapi` | You used a different Python. Run through `uv run` or the project's `.venv/bin/python`. |
| `No module named mactranslator` | Check that you are in the learning project, copied the full manifest, created `src/mactranslator/__init__.py`, and ran `uv sync --locked --extra dev`. |
| `No module named AppKit` | Install the project's macOS dependencies using the full manifest. The two introductory API lessons do not install PyObjC. |
| `.venv/bin/python` points to a missing file | The Python installation backing the environment moved or was deleted. Install Python in a persistent location and recreate the disposable virtual environment. |
| Tutorial says address already in use | Another server is using port 8765. Stop your earlier tutorial server in its own Terminal; do not kill unrelated processes. |
| Browser cannot use the production API | Expected: it requires a token and rejects browser-origin requests. Use the tutorial HTTP client or desktop. Interactive `/docs` is disabled there. |
| Tutorial API returns 401 | Use `Authorization: Bearer tutorial-local-only` for the mock production backend. This fixed tutorial token is not the desktop token. |
| PUT settings unexpectedly removes options | PUT is full replacement. Fetch current settings, edit that object, and send all preferences/providers you intend to retain. |
| Settings response does not contain the saved key | Expected: keys are write-only. `has_api_key` reports presence. Blank in the native key editor preserves it. |
| Keychain reports an inaccessible credential | Re-enter the provider key through settings after checking app identity/Keychain access. Do not place it in SQLite to bypass the error. |
| Popup has no translation result | Enable at least one translation provider; verify endpoint, exact model ID, key, and connection test. A TTS provider is not a translation provider. |
| Selected text is empty | Grant Accessibility, finish the selection gesture, then retry. Test clipboard translation to isolate service behavior from capture behavior. |
| Shortcut does nothing | Check trigger enabled state, recorded modifiers, permission, and conflicts with the Swift app or other software. |
| OCR fails but generated-image smoke passes | Screen capture permission or display-region capture can fail independently of recognition. Test the packaged app and its screen permission. |
| App says Python translator already running | Quit the other reference/learning/bundled instance. Deleting a lock file is not a substitute for ending the process holding its lock. |
| Changes do not appear in the packaged app | Rebuild and re-sign. Running source does not update an already generated bundle. |
| No Dock icon | Expected for a menu bar application. Find **译 Py** in the menu bar. |
| Notes vanish in the mock exercise | Check which database you opened. Tutorial storage and real desktop storage are intentionally separate; in-memory tutorial keys reset on server restart. |

To recreate a broken virtual environment, first stop processes that use it. From the learning directory, rename `.venv` to an unused backup name, then run:

```sh
uv python install 3.12
uv sync --locked --extra dev --python 3.12
```

The environment is reproducible dependency state, not your source or application database. Do not delete Application Support or Keychain entries as a routine environment-repair step. Avoid installing the Python used by a long-lived virtual environment under `/tmp`, which may be cleaned automatically.

## 24. Exercises and a completion checklist

### Practice changes in increasing difficulty

1. **Change a response:** add a `character_count` field to the first lesson's response and assert its value in your test.
2. **Observe concurrency:** make the mock second provider much slower. Confirm the first provider completes while the second is still streaming, without changing display order.
3. **Exercise failure:** modify the mock transport to return HTTP 503 for one model. Confirm a `provider_error` appears while the other provider still reaches `provider_done`.
4. **Add a policy:** support a new endpoint suffix or model message layout. Write pure input/output cases before modifying the network client.
5. **Follow a preference end to end:** trace `enable_notes` through its contract, SQLite serialization, settings control, API update, and popup visibility.
6. **Study cancellation:** start a long translation, then replace it. Confirm old events cannot alter the new popup and the old HTTP response closes.

For the failure experiment, use `tutorial/demo_backend.py` and the isolated tutorial database. Restore your mock change when finished so the guide's expected successful output applies again.

### The file map you should now recognize

| Files | Responsibility |
|---|---|
| `pyproject.toml`, `uv.lock` | Package metadata, dependencies, locked environment |
| `contracts.py` | Shared typed request/response/settings models |
| `policies.py`, `translation_prompt.txt` | Compatibility rules, pure behavior, translation instructions |
| `backend/api.py` | Authentication, lifecycle, routes, concurrent SSE orchestration |
| `backend/providers.py` | Translation, TTS, dictionary HTTP clients and SSE parsing |
| `backend/storage.py`, `credentials.py` | SQLite and Keychain |
| `desktop/runtime.py` | Background server and authenticated desktop HTTP client |
| `desktop/native.py`, `keycodes.py` | Selection, clipboard, hotkeys, native helpers |
| `desktop/widgets.py`, `popup.py` | Native controls, Markdown rendering, translation UI |
| `desktop/ocr.py` | Region selection, screen capture, local recognition |
| `desktop/settings.py`, `notes.py` | Settings and notes windows |
| `desktop/app.py`, `smoke.py` | Application coordination and explicit smoke checks |
| `launcher.py`, `packaging/setup.py`, `Makefile` | Launch, development, packaging, signing commands |
| `tests/` | Production regression tests |
| `tutorial/` | Learning-only API lessons and mock server/client |

You have completed the tutorial when you can:

- Start the first API and explain a successful response and a 422 response.
- Read SSE frames and explain why two providers can interleave.
- Run the mock production API, authenticate, and create/edit/delete a note.
- Explain the difference between a local bearer token and a provider API key.
- Launch the native app and configure a working translation provider.
- Explain which thread owns a window, a socket, and the SQLite connection.
- Capture selected text, perform OCR, speak text, and save a note on your machine.
- Run the automated tests and identify the remaining manual checks.
- Build and launch a `.app` that includes its own Python runtime.

For a compact operational reference after learning the architecture, use the [Python edition README](../README.md). For implementation details, follow the source links in each chapter; they are the actual modules assembled by the commands above.

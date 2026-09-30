"""Translate with an installed Gemini CLI and its cached Google OAuth login."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import tempfile

from .providers import ProviderError

TIMEOUT_SECONDS = 150
FAILURE = ("Gemini CLI failed. Run gemini in Terminal and sign in with Google; "
           "check your model, quota, and CLI version.")


def executable(command):
    # Finder-launched apps often do not inherit Homebrew/npm's PATH.
    search = os.pathsep.join(filter(None, [os.environ.get("PATH", ""),
                                         str(Path.home() / ".local/bin"),
                                         "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]))
    command = os.path.expanduser(command.strip() or "gemini")
    resolved = shutil.which(command, path=search)
    if not resolved:
        raise ProviderError("Gemini CLI was not found. Install it, or enter its absolute path in CLI Path.")
    resolved = os.path.abspath(resolved)
    return resolved, os.path.dirname(resolved) + os.pathsep + search


async def stop(process):
    if process.returncode is None:
        # Node launchers may have child processes; terminate the whole isolated group.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 2)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


async def translate(provider, prompt, text):
    command, search = executable(provider.cli_path)
    env = os.environ.copy()
    env["PATH"] = search
    # Explicit OAuth selection below avoids accidentally using paid API credentials.
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI",
                "GEMINI_SYSTEM_MD", "GEMINI_CLI_SYSTEM_DEFAULTS_PATH"):
        env.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="translator-gemini-") as directory:
        root = Path(directory)
        settings = {
            "security": {"auth": {"selectedType": "oauth-personal", "enforcedType": "oauth-personal"}},
            # A nonmatching allowlist also works in CLI versions treating [] as unset.
            "tools": {"core": ["__translator_no_tools__"]},
            "admin": {"mcp": {"enabled": False}, "extensions": {"enabled": False},
                      "skills": {"enabled": False}},
            "hooksConfig": {"enabled": False},
            "context": {"fileName": "TRANSLATOR_NO_MEMORY.md", "includeDirectories": [],
                        "includeDirectoryTree": False},
            "billing": {"overageStrategy": "never"},
            "telemetry": {"enabled": False, "logPrompts": False},
        }
        settings_path = root / "settings.json"
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
        env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"] = str(settings_path)
        args = [command, "--output-format", "stream-json", "--extensions", "none",
                "--approval-mode", "default", "--prompt",
                "Translate the source supplied on stdin according to its translation policy. "
                "Return only the requested translation. Do not use tools."]
        if provider.model.strip() and provider.model.strip() != "auto":
            args.append("--model=" + provider.model.strip())
        # Source goes through stdin, never shell interpolation or the process argument list.
        payload = json.dumps({"translation_policy": prompt, "source_text": text}, ensure_ascii=False).encode()
        process = None
        writer = None
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                process = await asyncio.create_subprocess_exec(
                    *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, cwd=directory, env=env,
                    start_new_session=True, limit=2 * 1024 * 1024)

                async def write_input():
                    try:
                        process.stdin.write(payload)
                        await process.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    finally:
                        process.stdin.close()

                writer = asyncio.create_task(write_input())
                received = success = False
                while line := await process.stdout.readline():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeError):
                        raise ProviderError("Invalid Gemini CLI output. Update Gemini CLI and retry.") from None
                    if not isinstance(event, dict):
                        raise ProviderError("Invalid Gemini CLI event.")
                    kind = event.get("type")
                    if kind == "message" and event.get("role") == "assistant":
                        content = event.get("content")
                        if isinstance(content, str) and content:
                            received = True
                            yield content
                    elif kind == "result":
                        if event.get("status") != "success":
                            raise ProviderError(FAILURE)
                        success = True
                    elif kind == "error" and event.get("severity") != "warning":
                        raise ProviderError(FAILURE)
                    elif kind in ("tool_use", "tool_result"):
                        raise ProviderError("Gemini CLI attempted a tool call. Translation requires text-only output.")
                await writer
                code = await process.wait()
                if code != 0 or not success:
                    raise ProviderError(FAILURE)
                if not received:
                    raise ProviderError("No translation was received from Gemini CLI.")
        except TimeoutError:
            raise ProviderError("Gemini CLI timed out. Check login and quota in Terminal, then retry.") from None
        except OSError:
            raise ProviderError("Could not start Gemini CLI. Check CLI Path and the Node.js installation.") from None
        finally:
            if writer is not None:
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
            if process is not None:
                await stop(process)

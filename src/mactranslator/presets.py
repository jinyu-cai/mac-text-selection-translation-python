"""Presets for API and local CLI translation services."""
from mactranslator.contracts import Provider


def google_ai_studio_provider():
    return Provider(
        name="Google AI Studio",
        endpoint="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-3.8-flash",
    )


def gemini_cli_provider():
    return Provider(name="Gemini CLI (Google login)", kind="gemini_cli", model="auto")


def antigravity_cli_provider():
    return Provider(name="Antigravity CLI", kind="antigravity_cli", model="auto", cli_path="agy")


def codex_cli_provider():
    return Provider(name="Codex (ChatGPT)", kind="codex_cli", model="auto", cli_path="codex")

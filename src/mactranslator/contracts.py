from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provider(Model):
    id: UUID = Field(default_factory=uuid4)
    name: str = "New Service"
    kind: Literal["translation", "gemini_cli", "antigravity_cli", "codex_cli", "openai_tts", "dashscope_tts", "dictionary"] = "translation"
    endpoint: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    cli_path: str = "gemini"
    enabled: bool = True
    reasoning: Literal["auto", "off", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"] = "auto"
    voice: str = "alloy"
    response_format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = "mp3"
    instructions: str = ""
    region: str = ""
    from_language: str = "en"
    to_language: str = "zh-Hans"
    # Excluded from all serialization, including saved settings and API responses.
    api_key: SecretStr | None = Field(default=None, exclude=True)
    has_api_key: bool = False

    @field_validator("endpoint")
    @classmethod
    def valid_endpoint(cls, value):
        from urllib.parse import urlsplit
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Enter an HTTP(S) endpoint without a username or password")
        if parsed.fragment:
            raise ValueError("The endpoint must not contain a fragment")
        return value


class Hotkey(Model):
    key_code: int = Field(default=2, ge=0, le=127)
    # Native NSEvent modifier bits, persisted independently of Carbon.
    modifiers: int = 1 << 19

    @field_validator("modifiers")
    @classmethod
    def valid_modifiers(cls, value):
        value &= (1 << 17) | (1 << 18) | (1 << 19) | (1 << 20)
        if not value:
            raise ValueError("A shortcut must include at least one modifier key")
        return value


class Settings(Model):
    providers: list[Provider] = Field(default_factory=list)
    target_language: str = "Chinese (Simplified)"
    custom_prompt: str = ""
    enable_hotkey: bool = True
    enable_ocr_hotkey: bool = True
    enable_floating_icon: bool = True
    restore_clipboard: bool = True
    enable_notes: bool = False
    hotkey: Hotkey = Field(default_factory=Hotkey)
    ocr_hotkey: Hotkey = Field(default_factory=lambda: Hotkey(key_code=31, modifiers=(1 << 19) | (1 << 17)))

    @model_validator(mode="after")
    def unique_ids_and_hotkeys(self):
        ids = [p.id for p in self.providers]
        if len(ids) != len(set(ids)):
            raise ValueError("Service IDs must be unique")
        if self.enable_hotkey and self.enable_ocr_hotkey and self.hotkey == self.ocr_hotkey:
            raise ValueError("Translation and screenshot shortcuts must be different")
        return self


class TranslationRequest(Model):
    request_id: UUID = Field(default_factory=uuid4)
    text: str = Field(min_length=1, max_length=200_000)

    @field_validator("text")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Source text cannot be empty")
        return value


class StreamEvent(Model):
    type: Literal["start", "delta", "provider_done", "provider_error", "dictionary", "done"]
    request_id: UUID
    provider_id: UUID | None = None
    text: str | None = None
    providers: list[Provider] | None = None
    data: dict | None = None


class SpeechRequest(Model):
    provider_id: UUID
    text: str = Field(min_length=1, max_length=50_000)
    language: str | None = None


class NoteCreate(Model):
    source_text: str = Field(min_length=1)
    translated_text: str | None = None
    backend_name: str | None = None
    user_note: str = ""


class NoteUpdate(Model):
    user_note: str


class Note(NoteCreate):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AntigravityLogin(Model):
    cli_path: str = "agy"


class AntigravityCode(Model):
    code: SecretStr


class CodexLogin(Model):
    cli_path: str = "codex"

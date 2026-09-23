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

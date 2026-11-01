import logging
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel, Field, field_validator

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-3.8-flash"
MAX_MESSAGE_LENGTH = 10_000
MAX_HISTORY_MESSAGES = 40

app = FastAPI(title="Nexus Chat API")
_genai_client: genai.Client | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "model"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("Message content cannot be blank.")
        return content


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    history: list[ChatMessage] = Field(default_factory=list, max_length=MAX_HISTORY_MESSAGES)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("Message cannot be blank.")
        return message


def get_genai_client() -> genai.Client:
    global _genai_client

    if _genai_client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="Chat is not configured. Set GEMINI_API_KEY in the backend environment.",
            )
        _genai_client = genai.Client(api_key=api_key)

    return _genai_client


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, str]:
    contents = [
        types.Content(role=turn.role, parts=[types.Part(text=turn.content)])
        for turn in request.history
    ]
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=request.message)],
        )
    )

    try:
        response = get_genai_client().models.generate_content(
            model=MODEL_NAME,
            contents=contents,
        )
    except APIError as error:
        logger.exception("Gemini API request failed")
        raise HTTPException(
            status_code=502,
            detail="The AI service could not complete your request. Please try again.",
        ) from error

    if not response.text or not response.text.strip():
        logger.error("Gemini returned an empty response")
        raise HTTPException(
            status_code=502,
            detail="The AI service returned an empty response. Please try again.",
        )

    return {"reply": response.text}

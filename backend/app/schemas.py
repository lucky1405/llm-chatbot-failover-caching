import re
from typing import Optional, List, Union
from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    status: str = "ok"
    keys_configured: int
    cache_enabled: bool = True


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128, description="Session ID (1-128 chars)")
    message: str = Field(..., description="User message (1-4000 chars after trimming)")
    system_prompt: Optional[str] = Field(None, description="Optional system prompt override")

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        trimmed = v.strip() if v else ""
        if not trimmed:
            raise ValueError("session_id cannot be empty or whitespace only")
        if len(v) > 128:
            raise ValueError("session_id cannot exceed 128 characters")
        return v

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        trimmed = v.strip() if v else ""
        if len(trimmed) < 1:
            raise ValueError("message cannot be empty or whitespace only")
        if len(trimmed) > 4000:
            raise ValueError("message cannot exceed 4000 characters after trimming")
        return trimmed


class ChatResponseMetadata(BaseModel):
    resolution_source: str = Field(..., description="Exactly LIVE_INFERENCE or LLM_CACHE")
    model: str = Field(..., description="LiteLLM model name that produced reply")
    latency_ms: int = Field(..., description="Server-measured time for this request in milliseconds")
    input_tokens: int = Field(..., description="Prompt tokens for this request")
    output_tokens: int = Field(..., description="Completion tokens for this reply")
    key_id: Optional[str] = Field(None, description="Id of key (key_1, key_2, ...) or null on LLM_CACHE")
    fallback_attempts: int = Field(..., description="Keys that failed before this one succeeded")


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatResponseMetadata


class StoredAssistantMetadata(BaseModel):
    resolution_source: str
    input_tokens: int
    output_tokens: int


class UserHistoryMessage(BaseModel):
    role: str = "user"
    content: str


class AssistantHistoryMessage(BaseModel):
    role: str = "assistant"
    content: str
    metadata: StoredAssistantMetadata


class SessionMessagesResponse(BaseModel):
    session_id: str
    messages: List[Union[UserHistoryMessage, AssistantHistoryMessage]]


class ErrorResponse(BaseModel):
    detail: str

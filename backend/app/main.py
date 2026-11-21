import os
import sys

# Ensure backend root is always on sys.path regardless of working directory
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder

from app.config import settings
from app.database import (
    init_db,
    check_db_health,
    session_has_messages,
    get_session_messages_raw,
    get_session_history_for_llm,
    save_turn,
)
from app.llm_gateway import gateway
from app.schemas import (
    HealthResponse,
    ChatRequest,
    ChatResponse,
    ChatResponseMetadata,
    SessionMessagesResponse,
    UserHistoryMessage,
    AssistantHistoryMessage,
    StoredAssistantMetadata,
    ErrorResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize SQLite schema
    await init_db()
    yield
    # Shutdown logic if any


app = FastAPI(
    title="LLM Chatbot Gateway with Failover and Caching",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global Exception Handlers ensuring JSON with "detail" and no stack traces
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "an unexpected internal error occurred"},
    )


@app.get(
    "/",
    summary="Root index",
    include_in_schema=False
)
async def root():
    return {
        "status": "ok",
        "service": "Lyftr AI Chatbot Gateway",
        "health": "/health",
        "docs": "/docs"
    }


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    responses={
        200: {"description": "App running, DB reachable, key pool loaded"},
        503: {"model": ErrorResponse, "description": "Database or service unavailable"}
    }
)
async def health():
    db_ok = await check_db_health()
    if not db_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unreachable"
        )
    return HealthResponse(
        status="ok",
        keys_configured=len(settings.key_pool),
        cache_enabled=True
    )


@app.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send chat message",
    responses={
        200: {"description": "Chat response generated or cached"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        503: {"model": ErrorResponse, "description": "all providers unavailable"}
    }
)
async def chat(
    payload: ChatRequest,
    x_simulate_failure: Optional[str] = Header(None, alias="X-Simulate-Failure")
):
    session_id = payload.session_id
    user_message = payload.message

    # 1. Fetch prior conversation history from SQLite
    history = await get_session_history_for_llm(session_id)

    # 2. Determine system prompt
    system_prompt = payload.system_prompt if payload.system_prompt is not None else settings.DEFAULT_SYSTEM_PROMPT

    # 3. Build messages list for the model
    full_messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt}
    ]
    full_messages.extend(history)
    full_messages.append({"role": "user", "content": user_message})

    # 4. Invoke LLM Gateway (caching + key failover + simulation support)
    # If 503 is raised, it will propagate directly and will NOT be added to history
    llm_result = await gateway.execute_chat(
        messages=full_messages,
        simulate_failure_header=x_simulate_failure
    )

    # 5. Persist the turn into SQLite (user message + assistant message)
    assistant_meta_for_db = {
        "resolution_source": llm_result["resolution_source"],
        "input_tokens": llm_result["input_tokens"],
        "output_tokens": llm_result["output_tokens"]
    }
    await save_turn(
        session_id=session_id,
        user_content=user_message,
        assistant_content=llm_result["reply"],
        assistant_metadata=assistant_meta_for_db
    )

    # 6. Format and return response
    return ChatResponse(
        session_id=session_id,
        reply=llm_result["reply"],
        metadata=ChatResponseMetadata(
            resolution_source=llm_result["resolution_source"],
            model=llm_result["model"],
            latency_ms=llm_result["latency_ms"],
            input_tokens=llm_result["input_tokens"],
            output_tokens=llm_result["output_tokens"],
            key_id=llm_result["key_id"],
            fallback_attempts=llm_result["fallback_attempts"]
        )
    )


@app.get(
    "/sessions/{session_id}/messages",
    response_model=SessionMessagesResponse,
    summary="Get session message history",
    responses={
        200: {"description": "Stored session history oldest first"},
        404: {"model": ErrorResponse, "description": "session not found"}
    }
)
async def get_session_messages(session_id: str):
    # Verify session existence
    has_msgs = await session_has_messages(session_id)
    if not has_msgs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found"
        )

    rows = await get_session_messages_raw(session_id)
    formatted_messages: List[Any] = []

    for r in rows:
        role = r["role"]
        content = r["content"]
        if role == "user":
            formatted_messages.append(UserHistoryMessage(role="user", content=content))
        elif role == "assistant":
            meta_dict = {}
            if r["metadata"]:
                try:
                    meta_dict = json.loads(r["metadata"])
                except Exception:
                    pass
            stored_meta = StoredAssistantMetadata(
                resolution_source=meta_dict.get("resolution_source", "LIVE_INFERENCE"),
                input_tokens=meta_dict.get("input_tokens", 0),
                output_tokens=meta_dict.get("output_tokens", 0)
            )
            formatted_messages.append(
                AssistantHistoryMessage(
                    role="assistant",
                    content=content,
                    metadata=stored_meta
                )
            )

    return SessionMessagesResponse(
        session_id=session_id,
        messages=formatted_messages
    )

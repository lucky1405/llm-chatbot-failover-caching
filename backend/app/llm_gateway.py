import os
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
from fastapi import HTTPException
import litellm
from litellm.caching.caching import Cache

from app.config import settings

# Suppress network model cost map download in sandboxed/offline environments
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
litellm.suppress_debug_info = True

logger = logging.getLogger(__name__)

# Initialize LiteLLM Cache
litellm.enable_cache(type="local")
cache: Cache = litellm.cache


def parse_simulate_failure_header(header_value: Optional[str]) -> Dict[str, int]:
    """
    Parses comma-separated <key_id>=<status> pairs, or *=<status>.
    Statuses supported: 429, 500, 502, 503.
    """
    if not header_value:
        return {}
    simulations = {}
    for part in header_value.split(","):
        part = part.strip()
        if "=" in part:
            k, status_str = part.split("=", 1)
            k = k.strip()
            status_str = status_str.strip()
            try:
                status_code = int(status_str)
                if status_code in (429, 500, 502, 503):
                    simulations[k] = status_code
            except ValueError:
                pass
    return simulations


class LLMGateway:
    def __init__(self):
        self.model = settings.LLM_MODEL

    def get_cache_key(self, model: str, messages: List[Dict[str, str]]) -> str:
        """
        Generates deterministic cache key for model + full message list.
        """
        return cache.get_cache_key(model=model, messages=messages)

    async def execute_chat(
        self,
        messages: List[Dict[str, str]],
        simulate_failure_header: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a chat completion with:
        1. Response caching (via LiteLLM Cache)
        2. Key failover (iterating over key pool on 429, quota, or 5xx)
        3. Simulated failure testing (via X-Simulate-Failure header)
        4. Token tracking and latency measurement
        """
        start_time = time.perf_counter()
        model = self.model

        # Parse simulation header if enabled
        simulations = {}
        has_simulated_failure = False
        if settings.ENABLE_FAILURE_SIMULATION and simulate_failure_header:
            simulations = parse_simulate_failure_header(simulate_failure_header)
            if simulations:
                has_simulated_failure = True
                logger.info(f"Simulating failure header active: {simulations}")

        cache_key = self.get_cache_key(model=model, messages=messages)

        # 1. Check cache (bypassed if simulating key failures)
        if not has_simulated_failure:
            cached_data = cache.get_cache(cache_key=cache_key)
            if cached_data is not None:
                latency_ms = max(1, int((time.perf_counter() - start_time) * 1000))
                cached_reply = ""
                cached_in_tokens = 0
                cached_out_tokens = 0

                if isinstance(cached_data, dict):
                    if "reply" in cached_data:
                        cached_reply = cached_data["reply"]
                        cached_in_tokens = cached_data.get("input_tokens", 0)
                        cached_out_tokens = cached_data.get("output_tokens", 0)
                    elif "choices" in cached_data and cached_data["choices"]:
                        choice0 = cached_data["choices"][0]
                        msg = choice0.get("message", {})
                        cached_reply = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                        usage = cached_data.get("usage", {})
                        if isinstance(usage, dict):
                            cached_in_tokens = usage.get("prompt_tokens", 0) or 0
                            cached_out_tokens = usage.get("completion_tokens", 0) or 0
                        elif hasattr(usage, "prompt_tokens"):
                            cached_in_tokens = getattr(usage, "prompt_tokens", 0) or 0
                            cached_out_tokens = getattr(usage, "completion_tokens", 0) or 0
                    else:
                        cached_reply = str(cached_data)
                elif hasattr(cached_data, "choices") and cached_data.choices:
                    choice0 = cached_data.choices[0]
                    cached_reply = choice0.message.content if hasattr(choice0, "message") else str(choice0)
                    if hasattr(cached_data, "usage") and cached_data.usage:
                        cached_in_tokens = getattr(cached_data.usage, "prompt_tokens", 0) or 0
                        cached_out_tokens = getattr(cached_data.usage, "completion_tokens", 0) or 0
                else:
                    cached_reply = str(cached_data)

                if cached_in_tokens <= 0:
                    try:
                        cached_in_tokens = litellm.token_counter(model=model, messages=messages)
                    except Exception:
                        cached_in_tokens = 10

                if cached_out_tokens <= 0:
                    try:
                        cached_out_tokens = litellm.token_counter(model=model, text=cached_reply or "")
                    except Exception:
                        cached_out_tokens = 10

                logger.info(f"Cache HIT for key {cache_key} (latency: {latency_ms}ms)")
                return {
                    "reply": cached_reply,
                    "resolution_source": "LLM_CACHE",
                    "model": model,
                    "latency_ms": latency_ms,
                    "input_tokens": cached_in_tokens,
                    "output_tokens": cached_out_tokens,
                    "key_id": None,
                    "fallback_attempts": 0
                }

        # 2. Iterate through key pool with fallback
        key_pool = settings.key_pool
        fallback_attempts = 0
        successful_key_id: Optional[str] = None
        reply_text: Optional[str] = None
        input_tokens = 0
        output_tokens = 0

        for key_info in key_pool:
            k_id = key_info["id"]
            api_key = key_info["api_key"]

            # Check if this key should fail via simulation
            simulated_status = None
            if has_simulated_failure:
                if "*" in simulations:
                    simulated_status = simulations["*"]
                elif k_id in simulations:
                    simulated_status = simulations[k_id]

            if simulated_status is not None:
                logger.warning(
                    f"Simulating HTTP {simulated_status} failure on key {k_id}."
                )
                fallback_attempts += 1
                continue

            # Attempt actual call with LiteLLM
            try:
                # Check for mock key / mock response mode
                is_mock_key = api_key.startswith("dummy") or api_key.startswith("mock")
                mock_env = os.getenv("MOCK_LLM_RESPONSE")

                if is_mock_key or mock_env:
                    last_user_msg = next(
                        (m["content"] for m in reversed(messages) if m["role"] == "user"),
                        "Hello"
                    )
                    mock_content = (
                        mock_env
                        if mock_env
                        else f"This is an AI response to: '{last_user_msg}'"
                    )
                    response = await litellm.acompletion(
                        model=model,
                        messages=messages,
                        mock_response=mock_content
                    )
                else:
                    call_model = model
                    api_base = settings.LLM_API_BASE

                    # Auto-detect Groq keys (starts with gsk_)
                    if api_key.startswith("gsk_"):
                        if not api_base:
                            api_base = "https://api.groq.com/openai/v1"
                        if model.startswith("openai/") and not model.startswith("openai/openai/"):
                            call_model = f"openai/{model}"

                    completion_kwargs = {
                        "model": call_model,
                        "messages": messages,
                        "api_key": api_key,
                    }
                    if api_base:
                        completion_kwargs["api_base"] = api_base
                    response = await litellm.acompletion(**completion_kwargs)

                # Extract reply text
                choice = response.choices[0]
                if hasattr(choice, "message"):
                    reply_text = choice.message.content
                else:
                    reply_text = str(choice)

                # Extract token usage
                if hasattr(response, "usage") and response.usage:
                    input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                    output_tokens = getattr(response.usage, "completion_tokens", 0) or 0

                # Fallback token estimation if provider returns 0 or None
                if input_tokens <= 0:
                    try:
                        input_tokens = litellm.token_counter(model=model, messages=messages)
                    except Exception:
                        input_tokens = sum(len(m.get("content", "").split()) for m in messages) * 2

                if output_tokens <= 0:
                    try:
                        output_tokens = litellm.token_counter(model=model, text=reply_text or "")
                    except Exception:
                        output_tokens = max(1, len((reply_text or "").split()) * 2)

                successful_key_id = k_id
                logger.info(f"Successful inference with key {k_id} after {fallback_attempts} fallback(s).")
                break

            except Exception as e:
                err_str = str(e).lower()
                status_code = getattr(e, "status_code", None)

                # Check if error qualifies as 429, quota exhaustion, or 5xx
                is_retryable = (
                    status_code in (429, 500, 502, 503, 504)
                    or "429" in err_str
                    or "rate limit" in err_str
                    or "quota" in err_str
                    or "resource_exhausted" in err_str
                    or "500" in err_str
                    or "502" in err_str
                    or "503" in err_str
                    or "internal server error" in err_str
                    or "service unavailable" in err_str
                    or "overloaded" in err_str
                )

                logger.warning(
                    f"Key {k_id} failed with error (status: {status_code}): {e}. Retryable: {is_retryable}"
                )
                fallback_attempts += 1
                continue

        # If all keys failed
        if successful_key_id is None or reply_text is None:
            logger.error("Every key in the pool failed. Returning HTTP 503.")
            raise HTTPException(status_code=503, detail="all providers unavailable")

        # Save to cache if this was not a simulated failure
        cache.add_cache(
            cache_key=cache_key,
            result={
                "reply": reply_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            }
        )

        latency_ms = max(1, int((time.perf_counter() - start_time) * 1000))

        return {
            "reply": reply_text,
            "resolution_source": "LIVE_INFERENCE",
            "model": model,
            "latency_ms": latency_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "key_id": successful_key_id,
            "fallback_attempts": fallback_attempts
        }


gateway = LLMGateway()

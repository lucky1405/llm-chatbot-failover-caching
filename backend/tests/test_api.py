import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["keys_configured"] >= 2
    assert data["cache_enabled"] is True


@pytest.mark.asyncio
async def test_chat_validation_missing_fields(client: AsyncClient):
    # Missing session_id
    resp = await client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 422
    assert "detail" in resp.json()

    # Empty session_id
    resp = await client.post("/chat", json={"session_id": "   ", "message": "hello"})
    assert resp.status_code == 422
    assert "detail" in resp.json()

    # Session_id exceeding 128 characters
    long_id = "a" * 129
    resp = await client.post("/chat", json={"session_id": long_id, "message": "hello"})
    assert resp.status_code == 422
    assert "detail" in resp.json()

    # Missing message
    resp = await client.post("/chat", json={"session_id": "s-123"})
    assert resp.status_code == 422
    assert "detail" in resp.json()

    # Empty/whitespace message
    resp = await client.post("/chat", json={"session_id": "s-123", "message": "   "})
    assert resp.status_code == 422
    assert "detail" in resp.json()

    # Message exceeding 4000 characters
    long_msg = "x" * 4001
    resp = await client.post("/chat", json={"session_id": "s-123", "message": long_msg})
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_chat_live_inference_and_token_tracking(client: AsyncClient):
    payload = {
        "session_id": "test-session-1",
        "message": "What is the capital of France?"
    }
    response = await client.post("/chat", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["session_id"] == "test-session-1"
    assert isinstance(data["reply"], str) and len(data["reply"]) > 0

    meta = data["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert "gemini" in meta["model"] or "mock" in meta["model"] or len(meta["model"]) > 0
    assert isinstance(meta["latency_ms"], int)
    assert meta["latency_ms"] >= 0
    assert meta["input_tokens"] > 0
    assert meta["output_tokens"] > 0
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0


@pytest.mark.asyncio
async def test_response_caching(client: AsyncClient):
    # Session A sends prompt
    payload_a = {
        "session_id": "session-cache-a",
        "message": "Explain quantum computing in one sentence."
    }
    resp_a = await client.post("/chat", json=payload_a)
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert data_a["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert data_a["metadata"]["key_id"] == "key_1"
    assert data_a["metadata"]["fallback_attempts"] == 0

    # Session B sends EXACT SAME prompt in a new session
    payload_b = {
        "session_id": "session-cache-b",
        "message": "Explain quantum computing in one sentence."
    }
    resp_b = await client.post("/chat", json=payload_b)
    assert resp_b.status_code == 200
    data_b = resp_b.json()

    # Must be cache hit
    assert data_b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert data_b["reply"] == data_a["reply"]
    assert data_b["metadata"]["input_tokens"] == data_a["metadata"]["input_tokens"]
    assert data_b["metadata"]["output_tokens"] == data_a["metadata"]["output_tokens"]
    assert data_b["metadata"]["key_id"] is None
    assert data_b["metadata"]["fallback_attempts"] == 0

    # Different prompt in Session C must NEVER come from cache
    payload_c = {
        "session_id": "session-cache-c",
        "message": "Explain black holes in one sentence."
    }
    resp_c = await client.post("/chat", json=payload_c)
    assert resp_c.status_code == 200
    data_c = resp_c.json()
    assert data_c["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert data_c["metadata"]["key_id"] == "key_1"


@pytest.mark.asyncio
async def test_multi_turn_and_session_history(client: AsyncClient):
    session_id = "multi-turn-session-99"

    # Turn 1
    resp1 = await client.post("/chat", json={
        "session_id": session_id,
        "message": "Hello, my name is Alice."
    })
    assert resp1.status_code == 200

    # Turn 2
    resp2 = await client.post("/chat", json={
        "session_id": session_id,
        "message": "What is my name?"
    })
    assert resp2.status_code == 200

    # Retrieve history
    hist_resp = await client.get(f"/sessions/{session_id}/messages")
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    assert hist["session_id"] == session_id

    messages = hist["messages"]
    assert len(messages) == 4
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello, my name is Alice."
    assert messages[1]["role"] == "assistant"
    assert "metadata" in messages[1]
    assert messages[1]["metadata"]["resolution_source"] in ("LIVE_INFERENCE", "LLM_CACHE")
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "What is my name?"
    assert messages[3]["role"] == "assistant"
    assert "metadata" in messages[3]


@pytest.mark.asyncio
async def test_unknown_session_history_returns_404(client: AsyncClient):
    resp = await client.get("/sessions/unknown-session-xyz/messages")
    assert resp.status_code == 404
    data = resp.json()
    assert data == {"detail": "session not found"}


@pytest.mark.asyncio
async def test_simulate_failure_key_1_429(client: AsyncClient):
    headers = {"X-Simulate-Failure": "key_1=429"}
    payload = {
        "session_id": "session-failover-1",
        "message": "Test failover from key 1 to key 2"
    }
    response = await client.post("/chat", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    # Must have failed over to key_2
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1
    assert data["metadata"]["resolution_source"] == "LIVE_INFERENCE"


@pytest.mark.asyncio
async def test_simulate_failure_key_1_500(client: AsyncClient):
    headers = {"X-Simulate-Failure": "key_1=500"}
    payload = {
        "session_id": "session-failover-2",
        "message": "Test 500 error failover from key 1 to key 2"
    }
    response = await client.post("/chat", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1


@pytest.mark.asyncio
async def test_simulate_failure_all_keys_unavailable_503(client: AsyncClient):
    session_id = "session-all-fail"
    headers = {"X-Simulate-Failure": "*=429"}
    payload = {
        "session_id": session_id,
        "message": "This request should completely fail"
    }
    response = await client.post("/chat", json=payload, headers=headers)
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}

    # Verify that failed request is NOT added to session history
    hist_resp = await client.get(f"/sessions/{session_id}/messages")
    assert hist_resp.status_code == 404
    assert hist_resp.json() == {"detail": "session not found"}

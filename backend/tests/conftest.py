import os
import tempfile
import pytest
from httpx import AsyncClient, ASGITransport

# Set test environment variables before importing app
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"
os.environ["LLM_API_KEYS"] = "mock_key_1,mock_key_2,mock_key_3"
os.environ["MOCK_LLM_RESPONSE"] = "This is a reliable AI response."

from app.config import settings
from app.main import app
from app.database import init_db
from app.llm_gateway import cache


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path):
    # Use temporary sqlite database for isolation
    test_db_file = tmp_path / "test_app.db"
    settings.DATABASE_URL = f"sqlite:///{test_db_file}"
    # Clear litellm cache
    try:
        if hasattr(cache, "cache") and hasattr(cache.cache, "flush_cache"):
            cache.cache.flush_cache()
        elif hasattr(cache, "cache") and hasattr(cache.cache, "cache_dict"):
            cache.cache.cache_dict.clear()
    except Exception:
        pass
    await init_db()
    yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

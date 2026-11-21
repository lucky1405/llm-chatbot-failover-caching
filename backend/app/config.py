import os
from typing import List
from dotenv import load_dotenv

load_dotenv()


class Settings:
    LLM_API_KEYS_RAW: str = os.getenv("LLM_API_KEYS", "dummy_key_1,dummy_key_2")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    ALLOWED_ORIGINS_RAW: str = os.getenv("ALLOWED_ORIGINS", "*")
    ENABLE_FAILURE_SIMULATION: bool = os.getenv("ENABLE_FAILURE_SIMULATION", "true").lower() in ("true", "1", "yes")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini/gemini-2.0-flash")
    DEFAULT_SYSTEM_PROMPT: str = os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful, friendly, and concise AI assistant.")
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    @property
    def key_pool(self) -> List[dict]:
        """
        Parses LLM_API_KEYS into a list of key items:
        [{"id": "key_1", "api_key": "..."}, {"id": "key_2", "api_key": "..."}]
        """
        raw_keys = [k.strip() for k in self.LLM_API_KEYS_RAW.split(",") if k.strip()]
        if not raw_keys:
            raw_keys = ["mock_key_1", "mock_key_2"]
        return [{"id": f"key_{i+1}", "api_key": key} for i, key in enumerate(raw_keys)]

    @property
    def allowed_origins(self) -> List[str]:
        if not self.ALLOWED_ORIGINS_RAW or self.ALLOWED_ORIGINS_RAW.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.ALLOWED_ORIGINS_RAW.split(",") if origin.strip()]

    @property
    def db_path(self) -> str:
        """
        Parses sqlite URL to a filesystem path.
        Handles sqlite:////data/app.db (absolute), sqlite:///data/app.db (relative), or plain path.
        """
        url = self.DATABASE_URL
        if url.startswith("sqlite:////"):
            path = "/" + url[len("sqlite:////"):]
        elif url.startswith("sqlite:///"):
            path = url[len("sqlite:///"):]
        elif url.startswith("sqlite://"):
            path = url[len("sqlite://"):]
        else:
            path = url
        return os.path.abspath(path)


settings = Settings()

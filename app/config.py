import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

# Define a static class to hold the application settings
@dataclass(frozen=True)
class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    AI_MODE: str = os.getenv("AI_MODE", "openai")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    AI_MAX_REQUEST_PER_HOUR: int = int(os.getenv("AI_MAX_REQUEST_PER_HOUR", 60))
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"
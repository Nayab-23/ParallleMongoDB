import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from typing import Literal

# Load .env from the same directory as this file (if it exists)
env_path = Path(__file__).with_name(".env")
if env_path.exists():
    try:
        load_dotenv(dotenv_path=env_path)
    except Exception:
        pass  # Ignore if .env can't be read
else:
    load_dotenv()  # Try loading from default locations

DeploymentMode = Literal["cloud", "self-hosted", "development", "production"]

class Config:
    """Application configuration with environment-based defaults"""
    
    # ============================================
    # DEPLOYMENT
    # ============================================
    # Legacy support: PARALLEL_ENV (development/production)
    # New: DEPLOYMENT_MODE (cloud/self-hosted)
    PARALLEL_ENV: str = os.getenv("PARALLEL_ENV", "development")
    MODE: DeploymentMode = os.getenv("DEPLOYMENT_MODE", "development")
    
    # ============================================
    # DATABASE
    # ============================================
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
    # ============================================
    # AUTH & SECURITY
    # ============================================
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    
    # ============================================
    # FRONTEND URL
    # ============================================
    FRONTEND_APP_URL: str = os.getenv("FRONTEND_APP_URL", "http://localhost:5173/app")
    
    # ============================================
    # OAUTH
    # ============================================
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    
    # ============================================
    # OPENAI / AI
    # ============================================
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai").lower()
    FIREWORKS_API_KEY: str = os.getenv("FIREWORKS_API_KEY", "")
    FIREWORKS_BASE_URL: str = os.getenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
    FIREWORKS_MODEL: str = os.getenv("FIREWORKS_MODEL", "")

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if LLM_PROVIDER == "fireworks":
        if FIREWORKS_API_KEY:
            OPENAI_API_KEY = FIREWORKS_API_KEY
        if FIREWORKS_MODEL:
            OPENAI_MODEL = FIREWORKS_MODEL
    OPENAI_INLINE_MODEL: str = os.getenv("OPENAI_INLINE_MODEL", OPENAI_MODEL)
    OPENAI_PLAN_MODEL: str = os.getenv("OPENAI_PLAN_MODEL", OPENAI_MODEL)
    OPENAI_EXPLAIN_MODEL: str = os.getenv("OPENAI_EXPLAIN_MODEL", OPENAI_MODEL)
    OPENAI_TESTS_MODEL: str = os.getenv("OPENAI_TESTS_MODEL", OPENAI_MODEL)
    OPENAI_INLINE_TEMPERATURE: float = float(os.getenv("OPENAI_INLINE_TEMPERATURE", "0.1"))
    OPENAI_AGENT_TEMPERATURE: float = float(os.getenv("OPENAI_AGENT_TEMPERATURE", "0.2"))
    
    # ============================================
    # INVITE SYSTEM
    # ============================================
    # Legacy support: PARALLEL_INVITE_CODE
    INVITE_CODE: str = os.getenv("INVITE_CODE") or os.getenv("PARALLEL_INVITE_CODE", "")
    DISABLE_INVITE_CODE: bool = os.getenv("DISABLE_INVITE_CODE", "false").lower() == "true"
    ALLOW_SELF_REGISTRATION: bool = os.getenv("ALLOW_SELF_REGISTRATION", "false").lower() == "true"
    
    # ============================================
    # ADMIN & ROLES
    # ============================================
    ADMIN_EMAILS_STR: str = os.getenv("ADMIN_EMAILS", "")
    ROLE_OPTIONS_STR: str = os.getenv("ROLE_OPTIONS", "Product,Engineering,Design,Data,Ops,Other")
    
    @property
    def ADMIN_EMAILS(self) -> set:
        """Parse admin emails into a set"""
        if not self.ADMIN_EMAILS_STR:
            return set()
        return {e.strip().lower() for e in self.ADMIN_EMAILS_STR.split(",") if e.strip()}
    
    @property
    def ROLE_OPTIONS(self) -> list:
        """Parse role options into a list"""
        return [r.strip() for r in self.ROLE_OPTIONS_STR.split(",") if r.strip()]
    
    # ============================================
    # COOKIE SETTINGS
    # ============================================
    @property
    def COOKIE_SECURE(self) -> bool:
        """
        Use secure cookies in production/cloud, allow insecure in development/self-hosted
        Legacy: Uses PARALLEL_ENV if DEPLOYMENT_MODE not set
        """
        if self.MODE in ["cloud", "production"]:
            return True
        if self.PARALLEL_ENV == "production":
            return True
        return False
    
    @property
    def COOKIE_SAMESITE(self) -> str:
        """Use 'none' for cross-origin (cloud), 'lax' for same-origin (self-hosted/dev)"""
        return "none" if self.MODE == "cloud" else "lax"
    
    @property
    def COOKIE_DOMAIN(self) -> str | None:
        """Set cookie domain (None for local/dev unless explicitly configured)."""
        cookie_domain = os.getenv("COOKIE_DOMAIN", "").strip()
        return cookie_domain or None
    
    # ============================================
    # OPENAI CLIENT
    # ============================================
    @property
    def openai_client(self) -> OpenAI | None:
        """
        Get OpenAI client instance (lazy loaded)
        Returns None if OPENAI_API_KEY not configured
        """
        if not self.OPENAI_API_KEY:
            return None
        if not hasattr(self, '_openai_client'):
            client_kwargs: dict[str, str] = {"api_key": self.OPENAI_API_KEY}
            if self.LLM_PROVIDER == "fireworks" and self.FIREWORKS_BASE_URL:
                client_kwargs["base_url"] = self.FIREWORKS_BASE_URL
            self._openai_client = OpenAI(**client_kwargs)
        return self._openai_client
    
    # ============================================
    # VALIDATION
    # ============================================
    def validate(self):
        """Validate required configuration"""
        errors = []
        
        if not self.DATABASE_URL:
            errors.append("DATABASE_URL is required")
        
        if not self.SECRET_KEY:
            errors.append("SECRET_KEY is required")
        
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")

# ============================================
# GLOBAL CONFIG INSTANCE
# ============================================
config = Config()

# Validate on import (will fail fast if misconfigured)
try:
    config.validate()
except ValueError as e:
    import sys
    # Don't validate during tests
    if "pytest" not in sys.modules:
        print(f"⚠️  Configuration warning: {e}")

# ============================================
# LEGACY EXPORTS (for backward compatibility)
# ============================================
OPENAI_API_KEY = config.OPENAI_API_KEY
openai_client = config.openai_client
OPENAI_MODEL = config.OPENAI_MODEL
OPENAI_INLINE_MODEL = config.OPENAI_INLINE_MODEL
OPENAI_PLAN_MODEL = config.OPENAI_PLAN_MODEL
OPENAI_EXPLAIN_MODEL = config.OPENAI_EXPLAIN_MODEL
OPENAI_TESTS_MODEL = config.OPENAI_TESTS_MODEL
OPENAI_INLINE_TEMPERATURE = config.OPENAI_INLINE_TEMPERATURE
OPENAI_AGENT_TEMPERATURE = config.OPENAI_AGENT_TEMPERATURE
COOKIE_SECURE = config.COOKIE_SECURE
INVITE_CODE = config.INVITE_CODE
PARALLEL_ENV = config.PARALLEL_ENV

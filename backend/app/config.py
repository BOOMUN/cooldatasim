from dataclasses import dataclass
import os


@dataclass
class Settings:
    database_url: str = os.getenv("COOLDATASIM_DATABASE_URL", "sqlite:///./development.db")
    admin_username: str = os.getenv("COOLDATASIM_ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("COOLDATASIM_ADMIN_PASSWORD", "")
    qwen_base_url: str = os.getenv("COOLDATASIM_QWEN_BASE_URL", "")
    qwen_model: str = os.getenv("COOLDATASIM_QWEN_MODEL", "qwen3.8-27b")
    qwen_api_key: str = os.getenv("COOLDATASIM_QWEN_API_KEY", "")
    chat_provider: str = os.getenv("COOLDATASIM_CHAT_PROVIDER", "")
    chat_base_url: str = os.getenv("COOLDATASIM_CHAT_BASE_URL", "")
    chat_model: str = os.getenv("COOLDATASIM_CHAT_MODEL", "")
    chat_api_key: str = os.getenv("COOLDATASIM_CHAT_API_KEY", "")
    chat_reasoning_effort: str = os.getenv("COOLDATASIM_CHAT_REASONING_EFFORT", "")
    chat_session_namespace: str = os.getenv("COOLDATASIM_CHAT_SESSION_NAMESPACE", "")
    embedding_base_url: str = os.getenv("COOLDATASIM_EMBEDDING_BASE_URL", "")
    embedding_model: str = os.getenv("COOLDATASIM_EMBEDDING_MODEL", "Qwen3-Embedding-0.6B")
    embedding_api_key: str = os.getenv("COOLDATASIM_EMBEDDING_API_KEY", "")
    embedding_dimensions: int = 1024
    reranker_base_url: str = os.getenv("COOLDATASIM_RERANKER_BASE_URL", "")
    reranker_model: str = os.getenv("COOLDATASIM_RERANKER_MODEL", "Qwen3-Reranker-0.6B")
    reranker_api_key: str = os.getenv("COOLDATASIM_RERANKER_API_KEY", "")
    evolution_base_url: str = os.getenv("COOLDATASIM_EVOLUTION_BASE_URL", "")
    evolution_api_key: str = os.getenv("COOLDATASIM_EVOLUTION_API_KEY", "")
    evolution_instance: str = os.getenv("COOLDATASIM_EVOLUTION_INSTANCE", "")
    webhook_secret: str = os.getenv("COOLDATASIM_WEBHOOK_SECRET", "")
    allow_external_send: bool = os.getenv("COOLDATASIM_ALLOW_EXTERNAL_SEND", "false").lower() == "true"
    crawl_allowed_hosts: str = os.getenv("COOLDATASIM_CRAWL_ALLOWED_HOSTS", "www.cooldatasim.com,cooldatasim.com")
    secure_cookies: bool = os.getenv("COOLDATASIM_SECURE_COOKIES", "false").lower() == "true"

    @property
    def uses_chat_config(self) -> bool:
        # Switch as one group: an incomplete external configuration must never
        # fall back to sending the private Qwen credential to a different host.
        return any((self.chat_provider, self.chat_base_url, self.chat_model,
                    self.chat_api_key, self.chat_reasoning_effort))

    @property
    def active_chat_provider(self) -> str:
        return (self.chat_provider.strip().lower() or "openai_compatible") if self.uses_chat_config else "qwen"

    @property
    def active_chat_base_url(self) -> str:
        return self.chat_base_url.strip() if self.uses_chat_config else self.qwen_base_url.strip()

    @property
    def active_chat_model(self) -> str:
        return self.chat_model.strip() if self.uses_chat_config else self.qwen_model.strip()

    @property
    def active_chat_api_key(self) -> str:
        return self.chat_api_key if self.uses_chat_config else self.qwen_api_key

    @property
    def active_chat_reasoning_effort(self) -> str:
        return (self.chat_reasoning_effort.strip().lower() or "high") if self.active_chat_provider in ("opencode", "deepseek") else ""


settings = Settings()

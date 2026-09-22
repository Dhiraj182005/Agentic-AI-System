from app.core.config import get_settings
from app.llm.base import BaseLLMProvider, LLMConfigurationError
from app.llm.providers.groq_provider import GroqProvider

SUPPORTED_PROVIDERS = ("groq",)


def get_llm_provider() -> BaseLLMProvider:
    """Return the configured LLM provider based on LLM_PROVIDER."""
    settings = get_settings()
    provider_name = (settings.LLM_PROVIDER or "").strip().lower()

    if provider_name == "groq":
        return GroqProvider()

    raise LLMConfigurationError(
        "Unsupported LLM_PROVIDER. Supported providers: "
        + ", ".join(SUPPORTED_PROVIDERS)
    )
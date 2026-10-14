from app.core.config import get_settings
from app.evidence.base import (
    EvidenceConfigurationError,
    EvidenceProvider,
    SearchResult,
)
from app.evidence.tavily import TavilyEvidenceProvider

SUPPORTED_EVIDENCE_PROVIDERS = ("tavily",)


def get_evidence_provider() -> EvidenceProvider:
    """Return the configured evidence provider based on EVIDENCE_PROVIDER."""
    settings = get_settings()
    provider_name = (settings.EVIDENCE_PROVIDER or "").strip().lower()

    if provider_name == "tavily":
        return TavilyEvidenceProvider()

    raise EvidenceConfigurationError(
        "Unsupported EVIDENCE_PROVIDER. Supported providers: "
        + ", ".join(SUPPORTED_EVIDENCE_PROVIDERS)
    )

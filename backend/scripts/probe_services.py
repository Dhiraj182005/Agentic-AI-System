"""Opt-in live checks. Uses small real API requests; prints no keys or payloads."""
import asyncio
import json

from app.core.config import get_settings
from app.evidence.google_fact_check import GoogleFactCheckClient
from app.evidence import get_evidence_provider
from app.llm.factory import get_llm_provider
from app.llm.base import LLMMessage


async def main():
    settings = get_settings()
    results = {"configured_model": settings.GROQ_MODEL}
    async def probe(name, configured, operation):
        if not configured:
            results[name] = {"configured": False, "status": "not_tested"}
            return
        try:
            result = await asyncio.wait_for(operation(), timeout=45)
            results[name] = {"configured": True, "status": "ok",
                             "results": len(result) if isinstance(result, list) else None}
        except Exception as exc:
            results[name] = {"configured": True, "status": "failed", "category": type(exc).__name__}
    await probe("google_fact_check", bool(settings.GOOGLE_FACT_CHECK_API_KEY),
                lambda: GoogleFactCheckClient().search("Earth is flat", max_results=1))
    await probe("tavily", bool(settings.TAVILY_API_KEY),
                lambda: get_evidence_provider().search("NASA Earth shape", max_results=1))
    await probe("groq", bool(settings.GROQ_API_KEY),
                lambda: get_llm_provider().generate([LLMMessage(role="user", content="Reply with OK.")], max_tokens=512))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

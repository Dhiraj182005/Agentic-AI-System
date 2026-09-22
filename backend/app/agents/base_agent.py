from app.llm.base import BaseLLMProvider, LLMMessage, LLMResponse
from app.llm.factory import get_llm_provider

GENERIC_SYSTEM_PROMPT = (
    "You are a knowledgeable, balanced AI assistant. "
    "Provide clear, accurate, and well-reasoned answers."
)


class BaseAgent:
    """Reusable base for future role-specific AI agents."""

    name: str = "generic"
    role: str = "assistant"
    system_prompt: str = GENERIC_SYSTEM_PROMPT

    def __init__(
        self,
        llm_provider: BaseLLMProvider | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.llm_provider = llm_provider or get_llm_provider()
        if system_prompt is not None:
            self.system_prompt = system_prompt

    async def generate_response(
        self,
        user_input: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        messages = [
            LLMMessage(role="system", content=self.system_prompt),
            LLMMessage(role="user", content=user_input),
        ]
        return await self.llm_provider.generate(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
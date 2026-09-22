import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.agents.base_agent import BaseAgent
from app.api.auth import get_current_user
from app.llm.base import (
    LLMConfigurationError,
    LLMProviderAPIError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.models.user import User
from app.schemas.ai import AITestRequest, AITestResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/test", response_model=AITestResponse)
async def ai_test(
    data: AITestRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        agent = BaseAgent()
        result = await agent.generate_response(data.message)
    except LLMConfigurationError as exc:
        logger.error("LLM configuration error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The LLM provider is not configured correctly.",
        ) from exc
    except LLMTimeoutError as exc:
        logger.error("LLM timeout error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The LLM request timed out.",
        ) from exc
    except LLMProviderAPIError as exc:
        logger.error("LLM provider API error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The LLM provider request failed.",
        ) from exc
    except LLMProviderError as exc:
        logger.error("LLM provider error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The LLM provider returned an error.",
        ) from exc

    return AITestResponse(
        response=result.content,
        provider=result.provider,
        model=result.model,
    )
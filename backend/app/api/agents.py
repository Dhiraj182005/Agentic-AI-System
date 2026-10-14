import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.agents.factory import UnsupportedAgentError, get_agent_by_role
from app.db.database import get_db
from app.llm.base import (
    LLMConfigurationError,
    LLMProviderAPIError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.models.user import User
from app.schemas.agents import AgentTestRequest, AgentTestResponse, CoreAgentResponse
from app.services.agent_service import list_active_core_agents

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[CoreAgentResponse])
async def list_agents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_active_core_agents(db)


@router.post("/test", response_model=AgentTestResponse)
async def agent_test(
    data: AgentTestRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        agent = get_agent_by_role(data.agent)
    except UnsupportedAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unsupported agent role: {data.agent}",
        ) from exc

    try:
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

    return AgentTestResponse(
        agent=agent.identifier,
        role=agent.role,
        response=result.content,
        provider=result.provider,
        model=result.model,
    )
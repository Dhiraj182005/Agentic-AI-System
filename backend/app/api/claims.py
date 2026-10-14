import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.database import get_db
from app.evidence.base import EvidenceConfigurationError, EvidenceProviderError
from app.models.user import User
from app.schemas.claim import (
    ClaimListResponse,
    ClaimResponse,
    ClaimVerificationResponse,
    EvidenceListResponse,
    EvidenceResponse,
)
from app.services import claim_service, debate_service
from app.services.claim_extraction import ClaimExtractionError
from app.services.verification_service import ClaimVerificationError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["claims"])


def _claim_response(claim, agent_name: str) -> ClaimResponse:
    return ClaimResponse(
        id=claim.id,
        debate_id=claim.debate_id,
        message_id=claim.message_id,
        agent_id=claim.agent_id,
        agent_name=agent_name,
        text=claim.text,
        claim_type=claim.claim_type,
        position=claim.position,
        created_at=claim.created_at,
    )


@router.post(
    "/debates/{debate_id}/claims/extract", response_model=ClaimListResponse
)
async def extract_claims(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = await claim_service.extract_claims(db, current_user, debate_id)
    except debate_service.DebateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    except claim_service.ClaimValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except ClaimExtractionError as exc:
        logger.error("Claim extraction failed for debate %s", debate_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Claim extraction failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Claim extraction failed because of an internal error",
        )
    return ClaimListResponse(
        debate_id=debate_id,
        claims=[_claim_response(claim, agent_name) for claim, agent_name in rows],
    )


@router.get("/debates/{debate_id}/claims", response_model=ClaimListResponse)
async def list_claims(
    debate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = await claim_service.list_claims(db, current_user, debate_id)
    except debate_service.DebateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Debate not found"
        )
    return ClaimListResponse(
        debate_id=debate_id,
        claims=[_claim_response(claim, agent_name) for claim, agent_name in rows],
    )


@router.post(
    "/claims/{claim_id}/evidence/retrieve",
    response_model=EvidenceListResponse,
)
async def retrieve_evidence(
    claim_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        evidence = await claim_service.retrieve_evidence(
            db, current_user, claim_id
        )
    except claim_service.ClaimNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found"
        )
    except claim_service.ClaimValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except EvidenceConfigurationError as exc:
        logger.error("Evidence provider is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    except EvidenceProviderError:
        logger.error(
            "Evidence provider failed for claim %s", claim_id, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The evidence provider failed while retrieving search results",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Evidence retrieval failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Evidence retrieval failed because of an internal error",
        )
    return EvidenceListResponse(
        claim_id=claim_id,
        evidence=[EvidenceResponse.model_validate(item) for item in evidence],
    )


@router.get("/claims/{claim_id}/evidence", response_model=EvidenceListResponse)
async def get_evidence(
    claim_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        evidence = await claim_service.get_evidence(db, current_user, claim_id)
    except claim_service.ClaimNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found"
        )
    return EvidenceListResponse(
        claim_id=claim_id,
        evidence=[EvidenceResponse.model_validate(item) for item in evidence],
    )


@router.post(
    "/claims/{claim_id}/verify", response_model=ClaimVerificationResponse
)
async def verify_claim(
    claim_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await claim_service.verify_claim(db, current_user, claim_id)
    except claim_service.ClaimNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found"
        )
    except ClaimVerificationError as exc:
        logger.error("Claim verification failed for claim %s", claim_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Claim verification failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Claim verification failed because of an internal error",
        )
    return ClaimVerificationResponse.model_validate(result)


@router.get(
    "/claims/{claim_id}/verification",
    response_model=ClaimVerificationResponse,
)
async def get_verification(
    claim_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await claim_service.get_verification(
            db, current_user, claim_id
        )
    except claim_service.ClaimNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return ClaimVerificationResponse.model_validate(result)

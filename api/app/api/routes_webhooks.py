"""
Point d'entrée des webhooks des agrégateurs.

    POST /api/v1/payments/webhooks/{provider_code}

Trois détails qui comptent :

1. on lit le corps **brut** (`await request.body()`). Si on laissait FastAPI
   le parser en JSON puis le re-sérialiser, l'ordre des clés changerait et la
   signature HMAC calculée par l'agrégateur ne correspondrait plus jamais.
2. on répond vite : le traitement financier est court, mais si un jour il
   devient long il faudra passer par une file et répondre 200 immédiatement.
3. les codes de réponse sont choisis pour piloter les renvois de l'agrégateur :
   200 = "j'ai pris, n'insiste pas", 502 = "réessaie plus tard".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..deps import get_registry
from ..payments.base import ProviderNotAvailableError
from ..payments.router import ProviderRegistry
from ..schemas import WebhookResponse
from ..services.webhooks import ingest_webhook

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/payments", tags=["paiements"])


@router.post("/webhooks/{provider_code}", response_model=WebhookResponse)
async def receive_webhook(
    provider_code: str,
    request: Request,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
) -> Response:
    settings = get_settings()

    try:
        provider = registry.get(provider_code)
    except ProviderNotAvailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    raw_body = await request.body()
    result = ingest_webhook(session, provider, raw_body, dict(request.headers))

    payload = WebhookResponse(
        outcome=result.outcome,
        detail=result.detail,
        event_id=result.event_id,
        transaction_id=str(result.transaction_id) if result.transaction_id else None,
        action=result.flow.action if result.flow else None,
    )
    return Response(
        content=payload.model_dump_json(),
        status_code=result.http_status,
        media_type="application/json",
        headers={"X-GeneraPay-Environment": settings.environment},
    )

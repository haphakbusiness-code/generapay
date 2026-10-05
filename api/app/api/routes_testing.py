"""
Endpoints de bac à sable — DÉSACTIVÉS EN PRODUCTION.

Ils existent pour une raison simple : sans eux, personne ne peut voir le
système fonctionner avant d'avoir un compte marchand FlexPaie. Une église
pilote peut ainsi tester le parcours complet, et vous pouvez montrer une
démonstration crédible.

`GENERAPAY_ALLOW_TESTING_ENDPOINTS=false` les coupe net (valeur imposée en
production). Ils ne manipulent que le MockProvider : jamais d'argent réel.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..deps import get_registry
from ..domain.enums import PaymentStatus
from ..payments.base import ProviderNotAvailableError
from ..payments.mock import MockProvider
from ..payments.router import ProviderRegistry
from ..seed import seed_demo_data
from ..services.reconciliation import reconcile_pending
from ..services.webhooks import ingest_webhook

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/testing", tags=["bac à sable"])


def _require_enabled() -> None:
    if not get_settings().allow_testing_endpoints:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Les endpoints de test sont désactivés dans cet environnement.",
        )


class SimulateOutcomeRequest(BaseModel):
    outcome: Literal["success", "failed", "expired"]
    # Permet de simuler un montant falsifié pour tester le contrôle de cohérence.
    amount_minor: int | None = None
    fee_minor: int | None = None


@router.post("/seed")
def seed(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Crée l'organisation de démonstration et les routes de paiement."""
    _require_enabled()
    organization = seed_demo_data(session)
    return {"organization_slug": organization.slug, "name": organization.name}


@router.post("/mock/transactions/{provider_transaction_id}/outcome")
def simulate_outcome(
    provider_transaction_id: str,
    payload: SimulateOutcomeRequest,
    request: Request,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
) -> dict[str, Any]:
    """Joue le rôle du téléphone du donateur, puis envoie le webhook signé.

    Cet appel traverse le VRAI chemin de production : signature vérifiée,
    événement journalisé, transaction ré-interrogée, écritures comptables
    créées. Rien n'est court-circuité.
    """
    _require_enabled()

    try:
        provider = registry.get("mock")
    except ProviderNotAvailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    assert isinstance(provider, MockProvider)

    try:
        provider.record_outcome(
            provider_transaction_id,
            PaymentStatus(payload.outcome),
            amount_minor=payload.amount_minor,
            fee_minor=payload.fee_minor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    event_type = {
        "success": "payment.succeeded",
        "failed": "payment.failed",
        "expired": "payment.expired",
    }[payload.outcome]

    body, headers = provider.build_webhook(
        provider_transaction_id,
        event_type,
        PaymentStatus(payload.outcome),
        amount_minor=payload.amount_minor,
        fee_minor=payload.fee_minor,
    )

    result = ingest_webhook(session, provider, body, headers)
    return {
        "simulated_outcome": payload.outcome,
        "webhook_outcome": result.outcome,
        "detail": result.detail,
        "action": result.flow.action if result.flow else None,
        "ledger_entries_created": (
            result.flow.ledger_entries_created if result.flow else 0
        ),
    }


@router.post("/reconcile")
def run_reconciliation(
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
) -> dict[str, Any]:
    """Lance un cycle de réconciliation des paiements en attente."""
    _require_enabled()
    report = reconcile_pending(session, registry)
    return report.as_dict()

"""
Traitement des webhooks (AGENTS.md §10).

Ordre imposé, et il n'est pas décoratif :

    1. vérifier l'authenticité  -> sinon on refuse tout ;
    2. journaliser l'événement brut -> pièce à conviction + idempotence ;
    3. rejouer un événement déjà traité -> réponse "déjà vu", aucun effet ;
    4. retrouver la transaction ;
    5. RE-INTERROGER le prestataire -> le webhook n'est qu'un déclencheur,
       la source de vérité reste l'API du prestataire ;
    6. appliquer l'état (machine à états + grand livre) ;
    7. marquer l'événement traité.

Pourquoi l'étape 5 alors qu'on a déjà le webhook ?
Parce qu'un webhook peut être falsifié, tronqué, ou arriver dans le désordre.
Un attaquant qui devine l'URL du webhook pourrait autrement créditer un don
de 10 000 USD sans rien payer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PaymentTransaction, WebhookEvent
from ..payments.base import PaymentProvider, WebhookVerificationError
from .transaction_flow import FlowOutcome, apply_provider_state, utcnow

__all__ = ["WebhookOutcome", "WebhookResult", "ingest_webhook"]


class WebhookOutcome:
    PROCESSED = "processed"    # traité pour la première fois
    DUPLICATE = "duplicate"    # déjà traité : aucun effet de bord
    IGNORED = "ignored"        # accepté mais sans effet (transaction inconnue...)
    REJECTED = "rejected"      # authentification impossible


@dataclass
class WebhookResult:
    outcome: str
    http_status: int
    detail: str
    event_id: str | None = None
    transaction_id: Any = None
    flow: FlowOutcome | None = None


def ingest_webhook(
    session: Session,
    provider: PaymentProvider,
    raw_body: bytes,
    headers: dict[str, str],
) -> WebhookResult:
    # ------------------------------------------------- 1. authentification du webhook
    try:
        provider.verify_webhook(raw_body, headers)
    except WebhookVerificationError as exc:
        _store_unverified(session, provider.code, raw_body, str(exc))
        session.commit()
        return WebhookResult(
            outcome=WebhookOutcome.REJECTED,
            http_status=400,
            detail=f"Webhook refusé : {exc}",
        )

    envelope = provider.parse_webhook(raw_body, headers)

    # --------------------------------------------------- 2. journal + idempotence
    existing = session.execute(
        select(WebhookEvent).where(
            WebhookEvent.provider_code == provider.code,
            WebhookEvent.provider_event_id == envelope.provider_event_id,
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.processed_at is not None:
            return WebhookResult(
                outcome=WebhookOutcome.DUPLICATE,
                http_status=200,
                detail="Événement déjà traité (aucune écriture comptable créée).",
                event_id=envelope.provider_event_id,
            )
        event = existing
    else:
        event = WebhookEvent(
            provider_code=provider.code,
            provider_event_id=envelope.provider_event_id,
            event_type=envelope.event_type,
            signature_valid=True,
            raw_payload=envelope.raw,
        )
        session.add(event)
    session.flush()

    # ------------------------------------------------------- 3. retrouver la transaction
    transaction = session.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.provider_code == provider.code,
            PaymentTransaction.provider_transaction_id
            == envelope.provider_transaction_id,
        )
    ).scalar_one_or_none()

    if transaction is None:
        # On ne marque PAS l'événement comme traité : si la transaction apparaît
        # plus tard (course entre webhook et écriture en base), un renvoi du
        # prestataire permettra de le traiter.
        event.processing_error = (
            f"Transaction inconnue : {envelope.provider_transaction_id!r}"
        )
        session.commit()
        return WebhookResult(
            outcome=WebhookOutcome.IGNORED,
            http_status=200,
            detail=event.processing_error,
            event_id=envelope.provider_event_id,
        )

    # ------------------------------------------- 4. vérification auprès du prestataire
    try:
        authoritative = provider.fetch_transaction(envelope.provider_transaction_id)
    except Exception as exc:  # réseau, 5xx, timeout...
        event.processing_error = f"Vérification prestataire impossible : {exc}"
        session.commit()
        # 502 : le prestataire renverra l'événement plus tard.
        return WebhookResult(
            outcome=WebhookOutcome.IGNORED,
            http_status=502,
            detail=event.processing_error,
            event_id=envelope.provider_event_id,
            transaction_id=transaction.id,
        )

    # --------------------------------------------------------- 5. application de l'état
    flow = apply_provider_state(session, transaction, authoritative)

    event.processed_at = utcnow()
    event.processing_error = None
    session.commit()

    return WebhookResult(
        outcome=WebhookOutcome.PROCESSED,
        http_status=200,
        detail=flow.detail or "État appliqué.",
        event_id=envelope.provider_event_id,
        transaction_id=transaction.id,
        flow=flow,
    )


def _store_unverified(
    session: Session, provider_code: str, raw_body: bytes, reason: str
) -> None:
    """Conserve la trace d'un webhook non authentifié.

    L'identifiant est dérivé du corps (empreinte SHA-256) : déterministe, donc
    un attaquant qui renvoie 10 000 fois la même charge ne remplit pas la table.
    """
    digest = hashlib.sha256(raw_body).hexdigest()[:32]
    event_id = f"unverified-{digest}"
    already = session.execute(
        select(WebhookEvent).where(
            WebhookEvent.provider_code == provider_code,
            WebhookEvent.provider_event_id == event_id,
        )
    ).scalar_one_or_none()
    if already is not None:
        return

    try:
        import json

        payload: dict[str, Any] | None = json.loads(raw_body.decode())
    except Exception:
        payload = {"unparsed_body": raw_body[:2000].decode("utf-8", "replace")}

    session.add(
        WebhookEvent(
            provider_code=provider_code,
            provider_event_id=event_id,
            event_type="signature_verification_failed",
            signature_valid=False,
            raw_payload={"reason": reason, "payload": payload},
            processing_error=reason,
        )
    )

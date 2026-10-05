"""
Réconciliation des paiements en attente (AGENTS.md §12).

Un paiement peut rester bloqué en PENDING pour de bonnes raisons :
    * le webhook n'est jamais arrivé (réseau, panne de l'agrégateur) ;
    * le donateur a abandonné sans fermer la page ;
    * le webhook est arrivé avant que notre transaction soit commitée.

Le principe : ne JAMAIS laisser un paiement en attente indéfiniment.
Ce job, lancé périodiquement :

    1. reprend les transactions PENDING ;
    2. redemande leur état au prestataire ;
    3. applique le résultat par le MÊME chemin que le webhook ;
    4. expire celles dont le délai est dépassé.

Au MVP, un simple planificateur suffit. Quand le volume l'exigera, on passera
sur une file (Redis/RQ, Celery, ou une tâche planifiée Supabase).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import PaymentStatus
from ..models import PaymentTransaction
from ..payments.base import PaymentProviderError, ProviderTransaction
from ..payments.router import ProviderRegistry
from .transaction_flow import FlowAction, apply_provider_state, utcnow

__all__ = ["ReconciliationReport", "reconcile_pending"]


@dataclass
class ReconciliationReport:
    scanned: int = 0
    succeeded: int = 0
    failed: int = 0
    expired: int = 0
    still_pending: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "expired": self.expired,
            "still_pending": self.still_pending,
            "errors": self.errors,
        }


def reconcile_pending(
    session: Session,
    registry: ProviderRegistry,
    *,
    limit: int = 100,
    now=None,
) -> ReconciliationReport:
    now = now or utcnow()
    report = ReconciliationReport()

    pending = (
        session.execute(
            select(PaymentTransaction)
            .where(PaymentTransaction.status == PaymentStatus.PENDING)
            .order_by(PaymentTransaction.created_at)
            .limit(limit)
        )
        .scalars()
        .all()
    )

    for transaction in pending:
        report.scanned += 1

        try:
            provider = registry.get(transaction.provider_code)
        except PaymentProviderError as exc:
            report.errors.append(f"{transaction.id}: {exc}")
            continue

        try:
            authoritative = provider.fetch_transaction(transaction.provider_transaction_id)
        except Exception as exc:  # noqa: BLE001 - on journalise, on continue
            report.errors.append(f"{transaction.id}: vérification impossible ({exc})")
            continue

        if authoritative.status is PaymentStatus.PENDING:
            # Le prestataire ne sait pas encore : on expire si le délai est dépassé.
            if transaction.expires_at is not None and transaction.expires_at <= now:
                expired_state = ProviderTransaction(
                    provider_transaction_id=transaction.provider_transaction_id,
                    status=PaymentStatus.EXPIRED,
                    amount_minor=transaction.amount_minor,
                    currency=transaction.currency,
                    raw_status="EXPIRED_BY_GENERAPAY",
                    failure_code="timeout",
                    failure_reason="Délai de confirmation dépassé.",
                )
                apply_provider_state(session, transaction, expired_state)
                report.expired += 1
                session.commit()
            else:
                report.still_pending += 1
            continue

        outcome = apply_provider_state(session, transaction, authoritative)
        session.commit()

        if outcome.action == FlowAction.SUCCEEDED:
            report.succeeded += 1
        else:
            report.failed += 1

    return report

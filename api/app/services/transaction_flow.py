"""
Cœur financier : appliquer l'état d'un prestataire à nos enregistrements.

C'est LA fonction la plus sensible du système. Elle est appelée par deux
chemins très différents :

    * le webhook (`services/webhooks.py`)     -> événement poussé ;
    * la réconciliation (`services/reconciliation.py`) -> interrogation périodique.

Les deux doivent produire EXACTEMENT le même résultat, sinon l'état d'un don
dépendrait du chemin par lequel l'information est arrivée.

Ce que cette fonction garantit :
    1. l'état vient du prestataire, jamais du navigateur du donateur ;
    2. un SUCCESS ne peut pas redevenir FAILED ;
    3. un montant différent de celui attendu = échec, jamais un encaissement ;
    4. les écritures comptables sont créées une seule fois.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..domain.enums import LedgerEntryType, PaymentStatus
from ..domain.ledger import plan_success_entries
from ..domain.state_machine import can_transition
from ..models import Donation, LedgerEntry, PaymentTransaction
from ..payments.base import ProviderTransaction

__all__ = ["FlowAction", "FlowOutcome", "apply_provider_state", "utcnow"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FlowAction:
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"
    NO_CHANGE = "no_change"          # déjà dans cet état (webhook dupliqué)
    ALREADY_FINAL = "already_final"  # ex. un "failed" qui arrive après le succès
    AMOUNT_MISMATCH = "amount_mismatch"


@dataclass
class FlowOutcome:
    action: str
    transaction: PaymentTransaction
    ledger_entries_created: int
    detail: str = ""

    @property
    def changed(self) -> bool:
        return self.action not in (FlowAction.NO_CHANGE, FlowAction.ALREADY_FINAL)


def apply_provider_state(
    session: Session,
    transaction: PaymentTransaction,
    provider_state: ProviderTransaction,
    *,
    platform_fee_bps: int | None = None,
) -> FlowOutcome:
    """Met à jour transaction + don + grand livre de façon idempotente.

    Ne fait PAS de commit : l'appelant décide du périmètre transactionnel,
    afin que « statut + écritures comptables » soient atomiques.
    """
    settings = get_settings()
    bps = settings.platform_fee_bps if platform_fee_bps is None else platform_fee_bps

    current = PaymentStatus(transaction.status)
    target = PaymentStatus(provider_state.status)

    # ---------------------------------------------------------- 1. contrôle montant
    # Un webhook peut être falsifié, et un donateur peut manipuler le montant
    # côté client. Si ce qui a été réellement encaissé diffère de ce qui était
    # attendu, on refuse le succès.
    #
    # ⚠️ On ne touche PAS encore à la transaction : si la machine à états refuse
    # la transition (webhook dupliqué ou tardif), aucun champ ne doit être modifié.
    mismatch_code: str | None = None
    mismatch_reason: str | None = None
    if target is PaymentStatus.SUCCESS and (
        provider_state.amount_minor != transaction.amount_minor
        or provider_state.currency.upper() != transaction.currency.upper()
    ):
        target = PaymentStatus.FAILED
        mismatch_code = "amount_mismatch"
        mismatch_reason = (
            f"Montant encaissé ({provider_state.amount_minor} "
            f"{provider_state.currency}) différent du montant attendu "
            f"({transaction.amount_minor} {transaction.currency})."
        )

    # --------------------------------------------------------- 2. machine à états
    if not can_transition(current, target):
        # Exemple : un "failed" arrive 2 minutes après le "success".
        # On ne touche à rien et on laisse la trace dans le journal webhook.
        return FlowOutcome(
            action=FlowAction.ALREADY_FINAL,
            transaction=transaction,
            ledger_entries_created=0,
            detail=f"{current.value} est un état final ; '{target.value}' ignoré.",
        )

    if current is target:
        # Webhook dupliqué : même statut, rien à faire.
        return FlowOutcome(
            action=FlowAction.NO_CHANGE,
            transaction=transaction,
            ledger_entries_created=0,
            detail="Statut déjà enregistré.",
        )

    # ------------------------------------------------------------------ 3. écriture
    now = utcnow()
    transaction.status = target
    transaction.provider_status_raw = provider_state.raw_status
    transaction.fee_minor = provider_state.fee_minor
    if target.is_final:
        transaction.completed_at = now
    if target is PaymentStatus.FAILED:
        transaction.failure_code = (
            transaction.failure_code
            or mismatch_code
            or provider_state.failure_code
            or "provider_failure"
        )
        transaction.failure_reason = (
            transaction.failure_reason
            or mismatch_reason
            or provider_state.failure_reason
        )
    elif target is PaymentStatus.EXPIRED:
        # Une expiration est aussi une information de support : le donateur n'a
        # jamais confirmé dans les délais.
        transaction.failure_code = (
            transaction.failure_code or provider_state.failure_code or "timeout"
        )
        transaction.failure_reason = (
            transaction.failure_reason
            or provider_state.failure_reason
            or "Délai de confirmation dépassé."
        )

    created_entries = 0
    if target is PaymentStatus.SUCCESS:
        created_entries = _create_ledger_entries(session, transaction, bps)

    _sync_donation(session, transaction, target, now)

    action = {
        PaymentStatus.SUCCESS: FlowAction.SUCCEEDED,
        PaymentStatus.FAILED: (
            FlowAction.AMOUNT_MISMATCH
            if transaction.failure_code == "amount_mismatch"
            else FlowAction.FAILED
        ),
        PaymentStatus.EXPIRED: FlowAction.EXPIRED,
        PaymentStatus.PENDING: FlowAction.NO_CHANGE,
    }[target]

    return FlowOutcome(
        action=action,
        transaction=transaction,
        ledger_entries_created=created_entries,
        detail=f"{current.value} -> {target.value}",
    )


def _create_ledger_entries(
    session: Session, transaction: PaymentTransaction, platform_fee_bps: int
) -> int:
    """Crée les écritures comptables manquantes (0 si déjà créées)."""
    from ..money import Money

    gross = Money.from_minor(transaction.amount_minor, transaction.currency)
    provider_fee = Money.from_minor(transaction.fee_minor, transaction.currency)

    existing = set(
        session.execute(
            select(LedgerEntry.entry_type).where(
                LedgerEntry.payment_transaction_id == transaction.id
            )
        ).scalars()
    )

    created = 0
    for planned in plan_success_entries(gross, provider_fee, platform_fee_bps):
        if planned.entry_type in existing:
            continue  # déjà comptabilisé (webhook rejoué) -> on ne double pas
        session.add(
            LedgerEntry(
                organization_id=transaction.organization_id,
                donation_id=transaction.donation_id,
                payment_transaction_id=transaction.id,
                entry_type=LedgerEntryType(planned.entry_type),
                amount_minor=planned.amount.amount_minor,
                currency=planned.amount.code,
                description=planned.description,
            )
        )
        created += 1
    return created


def _sync_donation(
    session: Session,
    transaction: PaymentTransaction,
    status: PaymentStatus,
    now: datetime,
) -> None:
    """Le statut du don reflète le résultat de sa meilleure tentative."""
    donation = session.get(Donation, transaction.donation_id)
    if donation is None:  # pragma: no cover - intégrité référentielle
        return

    if status is PaymentStatus.SUCCESS:
        donation.status = PaymentStatus.SUCCESS
        donation.succeeded_at = now
        return

    # Un autre essai a peut-être déjà réussi : on ne rétrograde pas un succès.
    if PaymentStatus(donation.status) is PaymentStatus.SUCCESS:
        return

    donation.status = status

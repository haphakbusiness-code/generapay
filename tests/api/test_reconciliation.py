"""
Réconciliation : aucun paiement ne doit rester bloqué en attente indéfiniment
(AGENTS.md §12).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import get_registry
from app.domain.enums import LedgerEntryType, PaymentStatus
from app.models import Donation, LedgerEntry, PaymentTransaction
from app.payments.mock import MockProvider
from app.services.reconciliation import reconcile_pending
from app.services.transaction_flow import utcnow

pytestmark = pytest.mark.usefixtures("organization")


def make_pending_donation(client: TestClient, amount: str = "20.00") -> str:
    response = client.post(
        "/api/v1/public/organizations/eglise-pilote/donations",
        json={
            "amount": amount,
            "currency": "USD",
            "payment_method": "mobile_money",
            "donor": {"phone": "+243810000001"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["reference"]


def transaction_of(session: Session, reference: str) -> PaymentTransaction:
    session.expire_all()
    donation = session.execute(
        select(Donation).where(Donation.reference == reference)
    ).scalar_one()
    return session.execute(
        select(PaymentTransaction).where(PaymentTransaction.donation_id == donation.id)
    ).scalar_one()


def test_un_paiement_confirme_sans_webhook_est_recupere(client: TestClient, session: Session):
    """Cas réel : le webhook se perd, mais l'argent est bien arrivé."""
    reference = make_pending_donation(client)
    transaction = transaction_of(session, reference)

    provider = get_registry().get("mock")
    assert isinstance(provider, MockProvider)
    provider.record_outcome(transaction.provider_transaction_id, PaymentStatus.SUCCESS, fee_minor=50)

    report = reconcile_pending(session, get_registry())

    assert report.as_dict()["succeeded"] == 1
    assert transaction_of(session, reference).status is PaymentStatus.SUCCESS

    session.expire_all()
    entries = session.execute(select(LedgerEntry)).scalars().all()
    assert {LedgerEntryType(e.entry_type): e.amount_minor for e in entries} == {
        LedgerEntryType.DONATION: 2000,
        LedgerEntryType.PROVIDER_FEE: -50,
    }


def test_un_paiement_toujours_en_attente_avant_echeance_n_est_pas_touche(
    client: TestClient, session: Session
):
    reference = make_pending_donation(client)

    report = reconcile_pending(session, get_registry())

    assert report.as_dict()["still_pending"] == 1
    assert transaction_of(session, reference).status is PaymentStatus.PENDING


def test_un_paiement_depassant_le_delai_est_expire(client: TestClient, session: Session):
    reference = make_pending_donation(client)

    # On simule une réconciliation exécutée une heure plus tard.
    report = reconcile_pending(session, get_registry(), now=utcnow() + timedelta(hours=1))

    assert report.as_dict()["expired"] == 1
    transaction = transaction_of(session, reference)
    assert transaction.status is PaymentStatus.EXPIRED
    assert transaction.failure_code == "timeout"

    # Aucune écriture comptable pour un paiement jamais abouti.
    session.expire_all()
    assert session.execute(select(LedgerEntry)).scalars().all() == []


def test_la_reconciliation_est_idempotente(client: TestClient, session: Session):
    reference = make_pending_donation(client)
    transaction = transaction_of(session, reference)

    provider = get_registry().get("mock")
    assert isinstance(provider, MockProvider)
    provider.record_outcome(transaction.provider_transaction_id, PaymentStatus.SUCCESS)

    reconcile_pending(session, get_registry())
    second = reconcile_pending(session, get_registry())

    assert second.as_dict()["scanned"] == 0  # plus rien en attente
    session.expire_all()
    assert session.execute(select(func.count(LedgerEntry.id))).scalar_one() == 2

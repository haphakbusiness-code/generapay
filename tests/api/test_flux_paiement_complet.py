"""
Test de bout en bout du parcours de don, en passant par le VRAI HTTP.

C'est le test le plus important du dépôt : il traverse la page publique,
le routage, le prestataire, le webhook signé, la vérification serveur,
la machine à états et le grand livre.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import get_registry
from app.domain.enums import LedgerEntryType, PaymentStatus
from app.models import Donation, LedgerEntry, PaymentTransaction, WebhookEvent
from app.payments.mock import MockProvider

pytestmark = pytest.mark.usefixtures("organization")


# --------------------------------------------------------------------------- #
# Aide
# --------------------------------------------------------------------------- #
def mock_provider() -> MockProvider:
    provider = get_registry().get("mock")
    assert isinstance(provider, MockProvider)
    return provider


def create_donation(
    client: TestClient,
    *,
    amount: str = "10.00",
    currency: str = "USD",
    contribution_type: str = "tithe",
    headers: dict[str, str] | None = None,
) -> dict:
    response = client.post(
        "/api/v1/public/organizations/eglise-pilote/donations",
        json={
            "amount": amount,
            "currency": currency,
            "contribution_type": contribution_type,
            "payment_method": "mobile_money",
            "donor": {"full_name": "Jean Mukendi", "phone": "+243810000000"},
        },
        headers=headers or {},
    )
    assert response.status_code == 201, response.text
    return response.json()


def provider_transaction_id(session: Session, reference: str) -> str:
    session.expire_all()
    donation = session.execute(
        select(Donation).where(Donation.reference == reference)
    ).scalar_one()
    transaction = session.execute(
        select(PaymentTransaction).where(PaymentTransaction.donation_id == donation.id)
    ).scalar_one()
    return transaction.provider_transaction_id


def ledger_total(session: Session) -> dict[str, int]:
    session.expire_all()
    rows = session.execute(
        select(LedgerEntry.entry_type, func.sum(LedgerEntry.amount_minor)).group_by(
            LedgerEntry.entry_type
        )
    ).all()
    return {LedgerEntryType(t).value: int(total) for t, total in rows}


# --------------------------------------------------------------------------- #
# Système
# --------------------------------------------------------------------------- #
def test_sonde_de_vie(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] is True


def test_profil_public_de_l_organisation(client: TestClient):
    response = client.get("/api/v1/public/organizations/eglise-pilote")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Église Pilote GeneraPay"
    assert set(body["supported_currencies"]) == {"USD", "CDF", "EUR"}
    assert "mobile_money" in body["payment_methods"]


def test_organisation_inconnue(client: TestClient):
    assert client.get("/api/v1/public/organizations/inexistante").status_code == 404


# --------------------------------------------------------------------------- #
# Création du don
# --------------------------------------------------------------------------- #
def test_creation_d_un_don_en_attente(client: TestClient):
    body = create_donation(client)
    assert body["status"] == "pending"
    assert body["reference"].startswith("GP-")
    assert body["provider"] == "mock"
    assert body["amount"] == "10.00"
    assert body["next_action"] == "await_payer_confirmation"
    assert body["status_url"].endswith(body["reference"])


def test_montant_invalide_refuse(client: TestClient):
    response = client.post(
        "/api/v1/public/organizations/eglise-pilote/donations",
        json={"amount": "abc", "currency": "USD"},
    )
    assert response.status_code == 422


def test_montant_negatif_refuse(client: TestClient):
    response = client.post(
        "/api/v1/public/organizations/eglise-pilote/donations",
        json={"amount": "-10", "currency": "USD"},
    )
    assert response.status_code == 422


def test_don_en_cdf_conserve_sa_devise(client: TestClient, session: Session):
    body = create_donation(client, amount="5000", currency="CDF")
    assert body["amount"] == "5000"
    assert body["currency"] == "CDF"

    session.expire_all()
    donation = session.execute(
        select(Donation).where(Donation.reference == body["reference"])
    ).scalar_one()
    # ISO 4217 : 5000 FC = 500 000 unités mineures. La devise n'est jamais convertie.
    assert donation.amount_minor == 500_000
    assert donation.currency == "CDF"


def test_cle_d_idempotence_evite_les_dons_doubles(client: TestClient):
    headers = {"Idempotency-Key": "cle-unique-123"}
    first = create_donation(client, headers=headers)
    second = create_donation(client, headers=headers)

    assert first["reference"] == second["reference"]
    assert second["was_duplicate"] is True


# --------------------------------------------------------------------------- #
# Webhook : le chemin qui crédite réellement l'argent
# --------------------------------------------------------------------------- #
def test_webhook_de_succes_credite_le_grand_livre(client: TestClient, session: Session):
    body = create_donation(client)
    txn_id = provider_transaction_id(session, body["reference"])

    response = client.post(
        f"/api/v1/testing/mock/transactions/{txn_id}/outcome",
        json={"outcome": "success", "fee_minor": 25},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["webhook_outcome"] == "processed"
    assert result["action"] == "succeeded"
    assert result["ledger_entries_created"] == 2

    # Le donateur voit son don confirmé...
    status = client.get(f"/api/v1/public/donations/{body['reference']}").json()
    assert status["status"] == "success"

    # ...et la comptabilité est exacte : +10.00 USD, -0.25 USD de frais.
    totals = ledger_total(session)
    assert totals["donation"] == 1000
    assert totals["provider_fee"] == -25


def test_webhook_duplique_ne_double_pas_la_comptabilite(client: TestClient, session: Session):
    body = create_donation(client)
    txn_id = provider_transaction_id(session, body["reference"])

    provider = mock_provider()
    provider.record_outcome(txn_id, PaymentStatus.SUCCESS, fee_minor=25)
    raw, headers = provider.build_webhook(txn_id, "payment.succeeded", PaymentStatus.SUCCESS)

    first = client.post(
        "/api/v1/payments/webhooks/mock", content=raw, headers=headers
    )
    second = client.post(
        "/api/v1/payments/webhooks/mock", content=raw, headers=headers
    )

    assert first.json()["outcome"] == "processed"
    assert second.json()["outcome"] == "duplicate"

    session.expire_all()
    entries = session.execute(select(LedgerEntry)).scalars().all()
    assert len(entries) == 2  # et pas 4
    assert ledger_total(session) == {"donation": 1000, "provider_fee": -25}


def test_webhook_non_signe_est_refuse(client: TestClient, session: Session):
    body = create_donation(client)
    txn_id = provider_transaction_id(session, body["reference"])

    provider = mock_provider()
    provider.record_outcome(txn_id, PaymentStatus.SUCCESS)
    raw, headers = provider.build_webhook(txn_id, "payment.succeeded", PaymentStatus.SUCCESS)

    tampered = raw.replace(b'"success"', b'"success"') + b" "
    response = client.post(
        "/api/v1/payments/webhooks/mock", content=tampered, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["outcome"] == "rejected"

    # Aucune écriture comptable, et la tentative est tracée.
    session.expire_all()
    assert session.execute(select(LedgerEntry)).scalars().all() == []
    event = session.execute(select(WebhookEvent)).scalar_one()
    assert event.signature_valid is False


def test_montant_falsifie_ne_credite_rien(client: TestClient, session: Session):
    body = create_donation(client, amount="10.00")
    txn_id = provider_transaction_id(session, body["reference"])

    # L'agresseur annonce 10 000 USD alors que le don était de 10 USD.
    response = client.post(
        f"/api/v1/testing/mock/transactions/{txn_id}/outcome",
        json={"outcome": "success", "amount_minor": 1_000_000},
    )
    assert response.status_code == 200
    assert response.json()["action"] == "amount_mismatch"

    session.expire_all()
    assert session.execute(select(LedgerEntry)).scalars().all() == []
    transaction = session.execute(select(PaymentTransaction)).scalar_one()
    assert transaction.status is PaymentStatus.FAILED
    assert transaction.failure_code == "amount_mismatch"


def test_un_echec_arrive_apres_le_succes_ne_change_rien(client: TestClient, session: Session):
    body = create_donation(client)
    txn_id = provider_transaction_id(session, body["reference"])

    client.post(
        f"/api/v1/testing/mock/transactions/{txn_id}/outcome", json={"outcome": "success"}
    )
    late = client.post(
        f"/api/v1/testing/mock/transactions/{txn_id}/outcome", json={"outcome": "failed"}
    )

    assert late.json()["action"] == "already_final"

    status = client.get(f"/api/v1/public/donations/{body['reference']}").json()
    assert status["status"] == "success"
    assert ledger_total(session)["donation"] == 1000


def test_un_evenement_tardif_ne_modifie_aucun_champ(client: TestClient, session: Session):
    """Un événement ignoré ne doit laisser AUCUNE trace sur la transaction.

    Piège classique : le code "prépare" les champs d'échec avant de vérifier la
    machine à états, puis sort sans écrire... alors que l'objet ORM, lui, a déjà
    été modifié en mémoire et sera flushé au prochain commit.
    """
    body = create_donation(client)
    txn_id = provider_transaction_id(session, body["reference"])

    provider = mock_provider()
    provider.record_outcome(txn_id, PaymentStatus.SUCCESS, fee_minor=25)
    raw, headers = provider.build_webhook(txn_id, "payment.succeeded", PaymentStatus.SUCCESS)
    assert (
        client.post("/api/v1/payments/webhooks/mock", content=raw, headers=headers)
        .json()
        .get("outcome")
        == "processed"
    )

    # Second événement, montant falsifié, identifiant différent : il sera ignoré.
    provider.record_outcome(txn_id, PaymentStatus.SUCCESS, amount_minor=999_999)
    raw, headers = provider.build_webhook(
        txn_id,
        "payment.succeeded",
        PaymentStatus.SUCCESS,
        amount_minor=999_999,
        event_id="evt_tardif_falsifie",
    )
    response = client.post("/api/v1/payments/webhooks/mock", content=raw, headers=headers)
    assert response.json()["action"] == "already_final"

    session.expire_all()
    transaction = session.execute(select(PaymentTransaction)).scalar_one()
    assert transaction.status is PaymentStatus.SUCCESS
    assert transaction.failure_code is None       # aucune trace de l'attaque
    assert transaction.amount_minor == 1000       # montant d'origine intact
    assert ledger_total(session) == {"donation": 1000, "provider_fee": -25}


def test_paiement_echoue_ne_cree_aucune_ecriture(client: TestClient, session: Session):
    body = create_donation(client)
    txn_id = provider_transaction_id(session, body["reference"])

    response = client.post(
        f"/api/v1/testing/mock/transactions/{txn_id}/outcome", json={"outcome": "failed"}
    )
    assert response.json()["action"] == "failed"

    session.expire_all()
    assert session.execute(select(LedgerEntry)).scalars().all() == []
    assert (
        client.get(f"/api/v1/public/donations/{body['reference']}").json()["status"] == "failed"
    )


def test_webhook_d_une_transaction_inconnue_est_journalise(client: TestClient, session: Session):
    """Un webhook valide mais orphelin ne doit rien créditer — et rester tracé."""
    raw, headers = _forged_webhook_for_unknown_transaction()

    response = client.post("/api/v1/payments/webhooks/mock", content=raw, headers=headers)
    assert response.status_code == 200
    assert response.json()["outcome"] == "ignored"

    session.expire_all()
    assert session.execute(select(LedgerEntry)).scalars().all() == []
    event = session.execute(select(WebhookEvent)).scalar_one()
    assert event.signature_valid is True
    assert "Transaction inconnue" in (event.processing_error or "")


def _forged_webhook_for_unknown_transaction() -> tuple[bytes, dict[str, str]]:
    """Webhook correctement signé mais portant une référence inexistante chez nous."""
    import hashlib
    import hmac
    import time

    from app.config import get_settings

    payload = {
        "event_id": "evt_orphelin",
        "event_type": "payment.succeeded",
        "created_at": int(time.time()),
        "data": {
            "transaction_id": "MOCK-GP-ORPHELIN",
            "status": "success",
            "amount": 1000,
            "currency": "USD",
            "fee": 0,
        },
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ts = str(payload["created_at"])
    signature = hmac.new(
        get_settings().mock_webhook_secret.encode(),
        f"{ts}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    return body, {
        "x-generapay-mock-signature": f"t={ts},v1={signature}",
        "content-type": "application/json",
    }


def test_prestataire_inconnu_en_webhook(client: TestClient):
    assert (
        client.post("/api/v1/payments/webhooks/paypal", content=b"{}").status_code == 404
    )

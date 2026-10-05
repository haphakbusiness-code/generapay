"""
Adaptateur FlexPaie.

Comme la documentation technique n'est pas encore livrée, ces tests verrouillent
le comportement de SÉCURITÉ : tant qu'on ne peut pas authentifier un webhook,
on le refuse. Mieux vaut un paiement qui attend qu'un don fantôme.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.config import Settings
from app.domain.enums import PaymentMethod, PaymentStatus
from app.payments.base import PaymentProviderError, WebhookVerificationError
from app.payments.flexpaie import FlexpaieProvider


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def signed_body(secret: str, payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    return body, hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
# Capacités : rien de plus que ce que FlexPaie a confirmé par écrit
# --------------------------------------------------------------------------- #
def test_capacites_limitees_a_ce_qui_est_confirme():
    provider = FlexpaieProvider(make_settings())
    capabilities = provider.capabilities

    assert capabilities.currencies == ("USD", "CDF")
    assert PaymentMethod.MOBILE_MONEY in capabilities.methods
    assert PaymentMethod.CARD in capabilities.methods
    assert not provider.supports("CD", "EUR", PaymentMethod.CARD)


# --------------------------------------------------------------------------- #
# Sécurité des webhooks
# --------------------------------------------------------------------------- #
def test_webhook_refuse_tant_que_le_schema_de_signature_n_est_pas_confirme():
    provider = FlexpaieProvider(make_settings(flexpaie_signature_scheme="unverified"))
    with pytest.raises(WebhookVerificationError, match="non confirmé"):
        provider.verify_webhook(b'{"status":"success"}', {})


def test_webhook_refuse_si_l_entete_de_signature_manque():
    provider = FlexpaieProvider(
        make_settings(
            flexpaie_signature_scheme="hmac-sha256",
            flexpaie_webhook_secret="secret",
            flexpaie_signature_header="x-flexpaie-signature",
        )
    )
    with pytest.raises(WebhookVerificationError, match="absent"):
        provider.verify_webhook(b'{"status":"success"}', {"content-type": "application/json"})


def test_webhook_valide_avec_une_bonne_signature_hmac():
    secret = "secret-flexpaie"
    provider = FlexpaieProvider(
        make_settings(
            flexpaie_signature_scheme="hmac-sha256",
            flexpaie_webhook_secret=secret,
            flexpaie_signature_header="x-flexpaie-signature",
        )
    )
    body, signature = signed_body(secret, {"event_id": "evt_1", "data": {"status": "success"}})

    provider.verify_webhook(body, {"X-FlexPaie-Signature": signature})  # ne lève pas


def test_webhook_refuse_avec_une_signature_erronee():
    provider = FlexpaieProvider(
        make_settings(
            flexpaie_signature_scheme="hmac-sha256",
            flexpaie_webhook_secret="secret-flexpaie",
            flexpaie_signature_header="x-flexpaie-signature",
        )
    )
    with pytest.raises(WebhookVerificationError, match="invalide"):
        provider.verify_webhook(b'{"status":"success"}', {"x-flexpaie-signature": "0" * 64})


def test_schema_de_signature_inconnu_refuse():
    provider = FlexpaieProvider(make_settings(flexpaie_signature_scheme="rsa-magique"))
    with pytest.raises(WebhookVerificationError, match="non pris en charge"):
        provider.verify_webhook(b"{}", {})


# --------------------------------------------------------------------------- #
# Interprétation des statuts
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SUCCESS", PaymentStatus.SUCCESS),
        ("paid", PaymentStatus.SUCCESS),
        ("FAILED", PaymentStatus.FAILED),
        ("expired", PaymentStatus.EXPIRED),
        ("processing", PaymentStatus.PENDING),
        ("statut_invente", PaymentStatus.PENDING),  # jamais SUCCESS par défaut
        ("", PaymentStatus.PENDING),
    ],
)
def test_statut_inconnu_reste_en_attente(raw, expected):
    provider = FlexpaieProvider(make_settings())
    assert provider._map_status(raw) is expected


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def test_aucun_appel_reseau_sans_identifiants_marchand():
    provider = FlexpaieProvider(make_settings())
    assert provider.is_configured is False

    from app.payments.base import PaymentRequest

    with pytest.raises(PaymentProviderError, match="n'est pas configuré"):
        provider.initiate(
            PaymentRequest(
                reference="GP-TEST01",
                amount_minor=1000,
                currency="USD",
                payment_method=PaymentMethod.MOBILE_MONEY,
                country_code="CD",
            )
        )

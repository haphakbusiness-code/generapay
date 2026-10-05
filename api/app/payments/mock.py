"""
MockProvider : un agrégateur fictif mais réaliste.

Il sert à trois choses :

1. **Développer** tout le flux (webhook, idempotence, grand livre) sans attendre
   les accès sandbox de FlexPaie ;
2. **Tester** automatiquement les cas dangereux : webhook dupliqué, statut qui
   arrive en retard, montant modifié, signature invalide ;
3. **Démontrer** la plateforme à une église pilote avant le premier franc réel.

Il imite un vrai agrégateur :
    - signature HMAC-SHA256 du corps du webhook (comme Stripe/FlexPaie),
    - fenêtre anti-rejeu de 5 minutes,
    - statut conservé de son côté, interrogeable via `fetch_transaction`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings
from ..domain.enums import PaymentMethod, PaymentStatus
from .base import (
    InitiationResult,
    PaymentProvider,
    PaymentRequest,
    ProviderCapabilities,
    ProviderTransaction,
    WebhookEnvelope,
    WebhookVerificationError,
)

__all__ = ["MockProvider"]

SIGNATURE_HEADER = "x-generapay-mock-signature"


def _display(amount_minor: int, currency: str) -> str:
    """Montant lisible pour les messages destinés au donateur."""
    from ..money import Money

    return Money.from_minor(amount_minor, currency).display()
REPLAY_WINDOW_SECONDS = 300


class MockProvider(PaymentProvider):
    code = "mock"
    display_name = "GénéraPay Mock (bac à sable interne)"

    def __init__(self, secret: str | None = None) -> None:
        self._secret = (secret or get_settings().mock_webhook_secret).encode()
        # "Système du prestataire" : ce que le mock sait de chaque transaction.
        # En mémoire : suffisant pour un mock mono-processus, et volontairement
        # distinct de notre base pour que la vérification serveur ait un sens.
        self._store: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------- capacités
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            countries=("CD",),
            currencies=("USD", "CDF", "EUR"),
            methods=(PaymentMethod.MOBILE_MONEY, PaymentMethod.CARD),
            note="Bac à sable interne : aucune devise n'est réellement refusée.",
        )

    # ------------------------------------------------------------ initiation
    def initiate(self, request: PaymentRequest) -> InitiationResult:
        provider_txn_id = f"MOCK-{request.reference}"

        # Idempotence : rejouer la même référence ne crée pas une 2e transaction.
        self._store.setdefault(
            provider_txn_id,
            {
                "status": PaymentStatus.PENDING,
                "amount_minor": request.amount_minor,
                "currency": request.currency,
                "fee_minor": 0,
                "raw_status": "WAITING_PAYER",
                "reference": request.reference,
            },
        )

        return InitiationResult(
            provider_transaction_id=provider_txn_id,
            next_action="await_payer_confirmation",
            instructions=(
                f"[SIMULATION] Le donateur doit confirmer le paiement de "
                f"{_display(request.amount_minor, request.currency)} {request.currency} "
                f"sur son téléphone."
            ),
            raw={"mock": True, "prompt": "*122# (simulation)"},
        )

    # ------------------------------------------------------ simulation d'un tiers
    def record_outcome(
        self,
        provider_transaction_id: str,
        status: PaymentStatus,
        *,
        amount_minor: int | None = None,
        fee_minor: int | None = None,
    ) -> None:
        """Joue le rôle du téléphone du donateur / du système de l'opérateur.

        Utilisé par les tests et par l'endpoint de démonstration.
        """
        record = self._store.get(provider_transaction_id)
        if record is None:
            raise KeyError(f"Transaction inconnue du mock : {provider_transaction_id}")
        record["status"] = status
        record["raw_status"] = {
            PaymentStatus.SUCCESS: "SUCCESS",
            PaymentStatus.FAILED: "FAILED",
            PaymentStatus.EXPIRED: "EXPIRED",
            PaymentStatus.PENDING: "WAITING_PAYER",
        }[status]
        if amount_minor is not None:
            record["amount_minor"] = amount_minor
        if fee_minor is not None:
            record["fee_minor"] = fee_minor

    # ------------------------------------------------------- vérification serveur
    def fetch_transaction(self, provider_transaction_id: str) -> ProviderTransaction:
        record = self._store.get(provider_transaction_id)
        if record is None:
            raise KeyError(f"Transaction inconnue du mock : {provider_transaction_id}")
        return ProviderTransaction(
            provider_transaction_id=provider_transaction_id,
            status=PaymentStatus(record["status"]),
            amount_minor=int(record["amount_minor"]),
            currency=record["currency"],
            fee_minor=int(record.get("fee_minor", 0)),
            raw_status=record.get("raw_status"),
            completed_at=datetime.now(timezone.utc)
            if record["status"] is not PaymentStatus.PENDING
            else None,
            raw=dict(record),
        )

    # ------------------------------------------------------------------ webhook
    def build_webhook(
        self,
        provider_transaction_id: str,
        event_type: str,
        status: PaymentStatus,
        *,
        amount_minor: int | None = None,
        fee_minor: int | None = None,
        event_id: str | None = None,
        timestamp: int | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        """Fabrique un webhook signé, exactement comme le ferait l'agrégateur.

        Retourne (corps, entêtes). Permet aux tests d'envoyer des webhooks
        valides, dupliqués, ou volontairement falsifiés.
        """
        record = self._store[provider_transaction_id]
        payload = {
            "event_id": event_id or f"evt_{uuid.uuid4().hex[:16]}",
            "event_type": event_type,
            "created_at": int(timestamp or time.time()),
            "data": {
                "transaction_id": provider_transaction_id,
                "reference": record.get("reference"),
                "status": status.value,
                "amount": (
                    record["amount_minor"] if amount_minor is None else amount_minor
                ),
                "currency": record["currency"],
                "fee": record.get("fee_minor", 0) if fee_minor is None else fee_minor,
            },
        }
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ts = str(payload["created_at"])
        signature = hmac.new(self._secret, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        headers = {
            SIGNATURE_HEADER: f"t={ts},v1={signature}",
            "content-type": "application/json",
        }
        return body, headers

    def _lookup_header(self, headers: dict[str, str], name: str) -> str | None:
        lowered = {k.lower(): v for k, v in headers.items()}
        return lowered.get(name)

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> None:
        header = self._lookup_header(headers, SIGNATURE_HEADER)
        if not header:
            raise WebhookVerificationError("En-tête de signature absent.")

        parts = dict(
            (p.split("=", 1)[0].strip(), p.split("=", 1)[1].strip())
            for p in header.split(",")
            if "=" in p
        )
        ts = parts.get("t")
        received_sig = parts.get("v1")
        if not ts or not received_sig:
            raise WebhookVerificationError("Signature malformée.")

        try:
            ts_value = int(ts)
        except ValueError as exc:
            raise WebhookVerificationError("Horodatage de signature invalide.") from exc

        # Anti-rejeu : un vieux webhook capturé ne doit plus être rejouable.
        if abs(time.time() - ts_value) > REPLAY_WINDOW_SECONDS:
            raise WebhookVerificationError("Webhook trop ancien (rejeu refusé).")

        expected = hmac.new(
            self._secret, f"{ts}.".encode() + raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, received_sig):
            raise WebhookVerificationError("Signature HMAC invalide.")

    def parse_webhook(self, raw_body: bytes, headers: dict[str, str]) -> WebhookEnvelope:
        try:
            payload = json.loads(raw_body.decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise WebhookVerificationError("Corps de webhook illisible.") from exc

        data = payload.get("data") or {}
        status_value = data.get("status")
        try:
            status = PaymentStatus(status_value)
        except ValueError as exc:
            raise WebhookVerificationError(
                f"Statut de webhook inconnu : {status_value!r}"
            ) from exc

        return WebhookEnvelope(
            provider_event_id=str(payload.get("event_id") or uuid.uuid4().hex),
            event_type=str(payload.get("event_type") or "unknown"),
            provider_transaction_id=str(data.get("transaction_id") or ""),
            status=status,
            amount_minor=int(data.get("amount") or 0),
            currency=str(data.get("currency") or ""),
            fee_minor=int(data.get("fee") or 0),
            raw_status=str(data.get("status") or ""),
            raw=payload,
        )

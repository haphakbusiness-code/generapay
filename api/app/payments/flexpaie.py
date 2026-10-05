"""
Adaptateur FlexPaie — état : ÉBAUCHE EN ATTENTE DE LA DOCUMENTATION OFFICIELLE.

Ce qui est CONFIRMÉ par l'e-mail de FlexPaie (reçu par HAPHAK) :
    * accès API après enregistrement marchand sur www.flexpaie.com ;
    * environnement Sandbox disponible ;
    * documentation technique (authentification, PayIn, PayOut, statut,
      webhooks) fournie aux marchands approuvés ;
    * frais d'acquisition API : 100 USD ; commission : 2,5 % par transaction ;
    * devises : USD et CDF ;
    * moyens de paiement : Mobile Money, Visa, Mastercard.

Ce qui n'est PAS encore connu (et qui bloque l'activation) :
    * URL de base et chemins exacts des endpoints ;
    * schéma d'authentification (clé API, OAuth, signature de requête) ;
    * format des montants (unités majeures avec décimales ? unités mineures ?) ;
    * schéma de signature des webhooks ;
    * existence de sous-comptes / reversement direct vers l'organisation.

RÈGLE DE SÉCURITÉ APPLIQUÉE ICI : *fail-closed*.
Tant que `flexpaie_signature_scheme` vaut "unverified", `verify_webhook()`
REFUSE tous les webhooks. Un agrégateur dont on ne sait pas authentifier les
notifications ne doit pas pouvoir créditer un don. On préfère un paiement qui
reste en attente (récupéré par la réconciliation) à un don fantôme.

L'euro (EUR) n'est PAS couvert par FlexPaie : il faudra un second prestataire
(Stripe / Adyen / PayPal / Mangopay). Le routage est déjà prévu pour ça.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..domain.enums import PaymentMethod, PaymentStatus
from .base import (
    InitiationResult,
    PaymentProvider,
    PaymentProviderError,
    PaymentRequest,
    ProviderCapabilities,
    ProviderTransaction,
    WebhookEnvelope,
    WebhookVerificationError,
)

__all__ = ["FlexpaieProvider"]


class FlexpaieProvider(PaymentProvider):
    code = "flexpaie"
    display_name = "FlexPaie (RDC — Mobile Money & cartes)"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # ------------------------------------------------------------- capacités
    @property
    def capabilities(self) -> ProviderCapabilities:
        # Source : e-mail FlexPaie, section 6. L'EUR est absent de leur offre.
        return ProviderCapabilities(
            countries=("CD",),
            currencies=("USD", "CDF"),
            methods=(PaymentMethod.MOBILE_MONEY, PaymentMethod.CARD),
            note="Confirmé par e-mail FlexPaie ; EUR non supporté.",
        )

    # ---------------------------------------------------------------- interne
    @property
    def is_configured(self) -> bool:
        s = self._settings
        return bool(s.flexpaie_base_url and s.flexpaie_api_key)

    def _require_configuration(self) -> None:
        if not self.is_configured:
            raise PaymentProviderError(
                "FlexPaie n'est pas configuré : renseignez GENERAPAY_FLEXPAIE_BASE_URL "
                "et GENERAPAY_FLEXPAIE_API_KEY une fois le compte marchand activé."
            )

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._settings.flexpaie_base_url.rstrip("/"),
            headers=self._auth_headers(),
            timeout=httpx.Timeout(30.0),
        )

    def _auth_headers(self) -> dict[str, str]:
        # ⚠️ NON VÉRIFIÉ : schéma d'authentification à confirmer avec la doc.
        # Deux schémas courants en Afrique francophone : `Authorization: Bearer`
        # ou une clé propriétaire type `X-Api-Key`. À trancher à la livraison.
        return {
            "Authorization": f"Bearer {self._settings.flexpaie_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------ initiation
    def initiate(self, request: PaymentRequest) -> InitiationResult:
        self._require_configuration()

        # ⚠️ NON VÉRIFIÉS : chemin de l'endpoint, noms des champs, et surtout
        # l'unité du montant. C'est LE point le plus dangereux de l'intégration :
        # si FlexPaie attend des francs entiers et qu'on envoie des centimes,
        # le donateur est débité 100 fois trop.
        payload: dict[str, Any] = {
            "amount": request.amount_minor,       # À CONFIRMER (unités)
            "currency": request.currency,
            "customer_msisdn": request.payer_phone,
            "customer_email": request.payer_email,
            "customer_name": request.payer_name,
            "reference": request.reference,       # NOTRE référence : idempotence
            "description": request.description,
            "return_url": request.return_url,
        }

        try:
            with self._client() as client:
                response = client.post("/api/v1/payin", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise PaymentProviderError(f"Appel FlexPaie en échec : {exc}") from exc

        # ⚠️ NON VÉRIFIÉ : noms des champs de réponse.
        return InitiationResult(
            provider_transaction_id=str(data.get("transaction_id") or data.get("id") or ""),
            next_action=str(data.get("next_action") or "await_payer_confirmation"),
            instructions=data.get("instructions") or data.get("message"),
            redirect_url=data.get("redirect_url"),
            raw=data,
        )

    # -------------------------------------------------- vérification serveur
    def fetch_transaction(self, provider_transaction_id: str) -> ProviderTransaction:
        self._require_configuration()
        try:
            with self._client() as client:
                response = client.get(f"/api/v1/payin/{provider_transaction_id}")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise PaymentProviderError(f"Appel FlexPaie en échec : {exc}") from exc

        return ProviderTransaction(
            provider_transaction_id=provider_transaction_id,
            status=self._map_status(str(data.get("status") or "")),
            amount_minor=int(data.get("amount") or 0),   # ⚠️ unité à confirmer
            currency=str(data.get("currency") or ""),
            fee_minor=int(data.get("fee") or 0),
            raw_status=str(data.get("status") or ""),
            failure_code=data.get("failure_code"),
            failure_reason=data.get("failure_reason"),
            raw=data,
        )

    def _map_status(self, raw_status: str) -> PaymentStatus:
        """Traduit le vocabulaire FlexPaie vers le nôtre.

        ⚠️ NON VÉRIFIÉ : la liste exacte des statuts vient de la documentation.
        Règle de prudence : tout statut inconnu reste PENDING, jamais SUCCESS.
        Un statut mal interprété dans le sens "succès" crée de l'argent fictif ;
        dans le sens "attente", il est rattrapé par la réconciliation.
        """
        table = {
            "success": PaymentStatus.SUCCESS,
            "succeeded": PaymentStatus.SUCCESS,
            "paid": PaymentStatus.SUCCESS,
            "completed": PaymentStatus.SUCCESS,
            "failed": PaymentStatus.FAILED,
            "failure": PaymentStatus.FAILED,
            "rejected": PaymentStatus.FAILED,
            "cancelled": PaymentStatus.FAILED,
            "canceled": PaymentStatus.FAILED,
            "expired": PaymentStatus.EXPIRED,
            "timeout": PaymentStatus.EXPIRED,
            "pending": PaymentStatus.PENDING,
            "processing": PaymentStatus.PENDING,
            "initiated": PaymentStatus.PENDING,
            "waiting_payer": PaymentStatus.PENDING,
        }
        return table.get(raw_status.strip().lower(), PaymentStatus.PENDING)

    # ------------------------------------------------------------------ webhook
    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> None:
        scheme = self._settings.flexpaie_signature_scheme.lower()

        if scheme == "unverified":
            # Fail-closed : tant que le schéma n'est pas documenté, on refuse.
            raise WebhookVerificationError(
                "Schéma de signature FlexPaie non confirmé. Webhook refusé. "
                "Renseignez GENERAPAY_FLEXPAIE_SIGNATURE_SCHEME après lecture "
                "de la documentation technique FlexPaie."
            )

        if scheme != "hmac-sha256":
            raise WebhookVerificationError(
                f"Schéma de signature non pris en charge : {scheme!r}"
            )

        import hashlib
        import hmac

        header_name = self._settings.flexpaie_signature_header.lower()
        lowered = {k.lower(): v for k, v in headers.items()}
        received = lowered.get(header_name)
        if not received:
            raise WebhookVerificationError(f"En-tête {header_name!r} absent.")
        if not self._settings.flexpaie_webhook_secret:
            raise WebhookVerificationError("Secret de webhook FlexPaie non configuré.")

        expected = hmac.new(
            self._settings.flexpaie_webhook_secret.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, received.strip()):
            raise WebhookVerificationError("Signature HMAC FlexPaie invalide.")

    def parse_webhook(self, raw_body: bytes, headers: dict[str, str]) -> WebhookEnvelope:
        try:
            payload = json.loads(raw_body.decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise WebhookVerificationError("Corps de webhook illisible.") from exc

        # ⚠️ NON VÉRIFIÉ : structure exacte de l'événement FlexPaie.
        data = payload.get("data") or payload
        return WebhookEnvelope(
            provider_event_id=str(payload.get("event_id") or payload.get("id") or ""),
            event_type=str(payload.get("event_type") or payload.get("type") or "unknown"),
            provider_transaction_id=str(
                data.get("transaction_id") or data.get("id") or ""
            ),
            status=self._map_status(str(data.get("status") or "")),
            amount_minor=int(data.get("amount") or 0),
            currency=str(data.get("currency") or ""),
            fee_minor=int(data.get("fee") or 0),
            raw_status=str(data.get("status") or ""),
            raw=payload,
        )

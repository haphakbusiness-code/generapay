"""
Abstraction des prestataires de paiement (AGENTS.md §7).

    PaymentProvider (ce fichier)
    ├── MockProvider      -> développe, teste, démontre sans argent réel
    └── FlexpaieProvider  -> agrégateur RDC (USD / CDF / Mobile Money / cartes)

Pourquoi cette couche ?
Parce que la logique métier (dons, grand livre, reçus, tableaux de bord) ne doit
JAMAIS connaître FlexPaie. Le jour où FlexPaie augmente ses frais, tombe en
panne, ou qu'un autre agrégateur devient nécessaire pour l'euro, on ajoute un
fichier — on ne réécrit pas la plateforme.

Contrat minimal qu'un prestataire doit savoir faire :

    initiate()            lancer un encaissement (prompt USSD, URL 3DS, ...)
    fetch_transaction()   redemander le statut à la source (vérification serveur)
    verify_webhook()      prouver que le webhook vient bien du prestataire
    parse_webhook()       transformer le JSON du prestataire en données neutres
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..domain.enums import PaymentMethod, PaymentStatus

__all__ = [
    "PaymentProvider",
    "PaymentProviderError",
    "WebhookVerificationError",
    "ProviderNotAvailableError",
    "PaymentRequest",
    "InitiationResult",
    "ProviderTransaction",
    "WebhookEnvelope",
    "ProviderCapabilities",
]


# --------------------------------------------------------------------------- #
# Erreurs
# --------------------------------------------------------------------------- #
class PaymentProviderError(Exception):
    """Erreur générique d'un prestataire (réseau, refus, configuration)."""


class WebhookVerificationError(PaymentProviderError):
    """Le webhook n'a pas pu être authentifié de façon certaine.

    On refuse alors de traiter l'événement : un faux webhook "success"
    fabriqué par un attaquant créditerait un don inexistant.
    """


class ProviderNotAvailableError(PaymentProviderError):
    """Le prestataire ne couvre pas ce pays / cette devise / ce moyen de paiement."""


# --------------------------------------------------------------------------- #
# Données échangées (objets neutres, indépendants de tout prestataire)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PaymentRequest:
    """Ce que GeneraPay demande à un prestataire d'encaisser."""

    reference: str              # référence interne GeneraPay (GP-XXXXXX)
    amount_minor: int
    currency: str
    payment_method: PaymentMethod
    country_code: str
    payer_phone: str | None = None
    payer_email: str | None = None
    payer_name: str | None = None
    description: str | None = None
    return_url: str | None = None
    expires_at: datetime | None = None
    # Contexte spécifique (slug de l'organisation, id de campagne...).
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InitiationResult:
    """Ce que le prestataire nous rend après initiation."""

    provider_transaction_id: str
    # Ce que le donateur doit faire : "Confirmez sur votre téléphone", "Ouvrez ce lien"...
    next_action: str
    instructions: str | None = None
    redirect_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderTransaction:
    """L'état d'une transaction TEL QUE LE DIT LE PRESTATAIRE.

    C'est la seule information de confiance : jamais un message du navigateur.
    """

    provider_transaction_id: str
    status: PaymentStatus
    amount_minor: int
    currency: str
    fee_minor: int = 0
    raw_status: str | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    completed_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookEnvelope:
    """Un webhook traduit en vocabulaire GeneraPay."""

    provider_event_id: str
    event_type: str
    provider_transaction_id: str
    status: PaymentStatus
    amount_minor: int
    currency: str
    fee_minor: int = 0
    raw_status: str | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderCapabilities:
    """Ce qu'un prestataire couvre RÉELLEMENT (vérifié, pas supposé)."""

    countries: tuple[str, ...]
    currencies: tuple[str, ...]
    methods: tuple[PaymentMethod, ...]
    note: str = ""

    def covers(self, country: str, currency: str, method: PaymentMethod) -> bool:
        return (
            country.upper() in {c.upper() for c in self.countries}
            and currency.upper() in {c.upper() for c in self.currencies}
            and method in self.methods
        )


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #
class PaymentProvider(ABC):
    """Contrat que tout agrégateur doit implémenter."""

    #: identifiant court, stable, stocké en base (`provider_code`)
    code: str = "abstract"
    display_name: str = "Abstract provider"

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Pays / devises / moyens de paiement réellement supportés."""

    def supports(self, country: str, currency: str, method: PaymentMethod) -> bool:
        return self.capabilities.covers(country, currency, method)

    @abstractmethod
    def initiate(self, request: PaymentRequest) -> InitiationResult:
        """Demande d'encaissement. Doit être idempotente sur `request.reference`."""

    @abstractmethod
    def fetch_transaction(self, provider_transaction_id: str) -> ProviderTransaction:
        """Interroge le prestataire. Utilisé pour vérifier ET pour réconcilier."""

    @abstractmethod
    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> None:
        """Vérifie l'authenticité du webhook. Lève `WebhookVerificationError`."""

    @abstractmethod
    def parse_webhook(self, raw_body: bytes, headers: dict[str, str]) -> WebhookEnvelope:
        """Traduit la charge utile du prestataire en `WebhookEnvelope`."""

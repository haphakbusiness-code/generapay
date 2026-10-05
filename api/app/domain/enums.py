"""
Énumérations métier.

Pourquoi des chaînes plutôt que des `enum.IntEnum` côté base ?
Parce qu'un statut financier doit rester lisible dans un export SQL, un log,
ou l'écran d'un support client dans 5 ans. Les valeurs sont donc stockées
en texte, et contraintes par un CHECK en base (voir migrations).
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "PaymentStatus",
    "PaymentMethod",
    "ContributionType",
    "OrganizationRole",
    "LedgerEntryType",
    "SettlementMode",
]


class PaymentStatus(StrEnum):
    """Machine à états d'un paiement (AGENTS.md §8)."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    EXPIRED = "expired"

    @property
    def is_final(self) -> bool:
        return self is not PaymentStatus.PENDING


class PaymentMethod(StrEnum):
    MOBILE_MONEY = "mobile_money"
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"


class ContributionType(StrEnum):
    """Types de contribution initiaux (README). La colonne est du texte :
    ajouter 'construction' ou 'mission' ne demande aucune migration."""

    DONATION = "donation"
    TITHE = "tithe"
    OFFERING = "offering"
    CAMPAIGN = "campaign"


class OrganizationRole(StrEnum):
    """Du plus puissant au moins puissant (AGENTS.md §14)."""

    OWNER = "owner"
    ADMIN = "admin"
    TREASURER = "treasurer"
    VIEWER = "viewer"


class LedgerEntryType(StrEnum):
    DONATION = "donation"      # argent brut collecté
    PROVIDER_FEE = "provider_fee"  # commission de l'agrégateur (négatif)
    PLATFORM_FEE = "platform_fee"  # commission GeneraPay (négatif, 0 au MVP)
    REFUND = "refund"          # remboursement / entrée compensatrice
    PAYOUT = "payout"


class SettlementMode(StrEnum):
    """Où va l'argent après encaissement ?

    DIRECT_TO_ORGANIZATION : l'agrégateur verse directement sur le compte de
        l'organisation (modèle cible : GeneraPay ne détient jamais les fonds).
    PLATFORM_ACCOUNT : l'argent arrive chez HAPHAK puis doit être reversé.
        ⚠️ À ÉVITER : cela fait de HAPHAK un établissement de monnaie
        électronique de fait. Voir docs/01-plan-integration-flexpaie.md.
    UNCONFIRMED = le contrat n'a pas encore tranché la question.
    """

    DIRECT_TO_ORGANIZATION = "direct_to_organization"
    PLATFORM_ACCOUNT = "platform_account"
    UNCONFIRMED = "unconfirmed"

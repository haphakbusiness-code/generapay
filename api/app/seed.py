"""
Données de démonstration (bac à sable).

Crée une organisation pilote et les routes de paiement par défaut.
Idempotent : on peut l'appeler à chaque démarrage sans créer de doublons.

En production, ces données ne sont PAS créées : on passe par les migrations
`supabase/seed/` et par l'inscription des organisations.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain.enums import PaymentMethod, SettlementMode
from .models import MerchantAccount, Organization, PaymentRoute

__all__ = ["DEMO_SLUG", "seed_demo_data"]

DEMO_SLUG = "eglise-pilote"


def seed_demo_data(session: Session) -> Organization:
    """Retourne l'organisation de démonstration (créée si absente)."""
    organization = session.execute(
        select(Organization).where(Organization.slug == DEMO_SLUG)
    ).scalar_one_or_none()

    if organization is None:
        organization = Organization(
            name="Église Pilote GeneraPay",
            slug=DEMO_SLUG,
            country_code="CD",
            default_currency="USD",
            status="active",
            support_email="tresorier@eglise-pilote.example",
            support_phone="+243000000000",
        )
        session.add(organization)
        session.flush()

    _ensure_routes(session, organization)
    _ensure_merchant_account(session, organization)
    _ensure_campaign(session, organization)
    session.commit()
    return organization


def _ensure_campaign(session: Session, organization: Organization) -> None:
    """Campagne d'exemple : montre la collecte fléchée vers un projet."""
    from .models import Campaign

    exists = session.execute(
        select(Campaign).where(
            Campaign.organization_id == organization.id,
            Campaign.slug == "construction-temple",
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(
            Campaign(
                organization_id=organization.id,
                slug="construction-temple",
                title="Construction du temple",
                description="Campagne de collecte pour la construction du nouveau temple.",
                goal_amount_minor=5_000_000,  # 50 000.00 USD
                currency="USD",
                status="active",
            )
        )
    session.flush()


def _ensure_routes(session: Session, organization: Organization) -> None:
    """Routes par défaut : tout passe par le mock tant que FlexPaie n'est pas actif."""
    defaults = [
        # (pays, devise, moyen de paiement, prestataire, priorité)
        ("CD", "CDF", PaymentMethod.MOBILE_MONEY, "mock", 10),
        ("CD", "USD", PaymentMethod.MOBILE_MONEY, "mock", 10),
        ("CD", "USD", PaymentMethod.CARD, "mock", 10),
        ("CD", "EUR", PaymentMethod.CARD, "mock", 20),  # en attendant un PSP EUR
        (None, None, None, "mock", 999),  # filet de secours
    ]

    for country, currency, method, provider_code, priority in defaults:
        exists = session.execute(
            select(PaymentRoute).where(
                PaymentRoute.organization_id.is_(None),
                PaymentRoute.country_code.is_(None) if country is None
                else PaymentRoute.country_code == country,
                PaymentRoute.currency.is_(None) if currency is None
                else PaymentRoute.currency == currency,
                PaymentRoute.payment_method.is_(None) if method is None
                else PaymentRoute.payment_method == method,
                PaymentRoute.provider_code == provider_code,
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(
                PaymentRoute(
                    organization_id=None,
                    country_code=country,
                    currency=currency,
                    payment_method=method,
                    provider_code=provider_code,
                    priority=priority,
                    is_active=True,
                )
            )
    session.flush()


def _ensure_merchant_account(session: Session, organization: Organization) -> None:
    exists = session.execute(
        select(MerchantAccount).where(
            MerchantAccount.organization_id == organization.id,
            MerchantAccount.provider_code == "flexpaie",
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(
            MerchantAccount(
                organization_id=organization.id,
                provider_code="flexpaie",
                merchant_ref=None,
                settlement_mode=SettlementMode.UNCONFIRMED,
                status="pending_kyc",
                currencies=["USD", "CDF"],
                notes=(
                    "Compte marchand FlexPaie à ouvrir. "
                    "Question bloquante : le règlement va-t-il directement "
                    "sur le compte de l'organisation ?"
                ),
            )
        )
    session.flush()


def new_membership_user_id() -> uuid.UUID:
    """Identifiant d'utilisateur de test (simule un UUID Supabase Auth)."""
    return uuid.uuid4()

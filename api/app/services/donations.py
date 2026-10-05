"""
Cas d'usage : créer un don et lancer son encaissement.

Séquence complète (page publique de don) :

    1. on valide le montant (unités mineures + devise ISO 4217) ;
    2. on applique l'idempotence côté client (`Idempotency-Key`) ;
    3. on retrouve ou on crée le donateur ;
    4. on crée le don en PENDING ;
    5. le routeur choisit l'agrégateur (pays / devise / moyen de paiement) ;
    6. on demande l'encaissement au prestataire ;
    7. on enregistre la tentative de paiement avec son échéance.

À ce stade, RIEN n'est encaissé : le donateur doit encore confirmer sur son
téléphone. Le succès ne sera reconnu qu'après vérification serveur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..domain.enums import ContributionType, PaymentMethod, PaymentStatus
from ..models import Donation, Donor, Organization, PaymentTransaction
from ..money import Money
from ..payments.base import InitiationResult
from ..payments.router import PaymentRouter, ProviderRegistry
from .references import generate_donation_reference
from .transaction_flow import utcnow

__all__ = ["DonorInput", "DonationDraft", "CreatedDonation", "create_donation", "find_or_create_donor"]


@dataclass(frozen=True)
class DonorInput:
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    country_code: str | None = None
    is_anonymous: bool = False


@dataclass(frozen=True)
class DonationDraft:
    amount: Money
    payment_method: PaymentMethod = PaymentMethod.MOBILE_MONEY
    contribution_type: ContributionType = ContributionType.DONATION
    campaign_id: Any = None
    message: str | None = None
    donor: DonorInput = field(default_factory=DonorInput)
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CreatedDonation:
    donation: Donation
    transaction: PaymentTransaction
    initiation: InitiationResult | None
    was_duplicate: bool = False


def find_or_create_donor(
    session: Session, organization_id: Any, info: DonorInput
) -> Donor:
    """Retrouve un donateur existant (e-mail puis téléphone) ou le crée.

    Évite les doublons dans le fichier donateur d'une église, sans jamais
    mélanger deux organisations : la recherche est toujours bornée par
    `organization_id`.
    """
    if info.email:
        found = session.execute(
            select(Donor).where(
                Donor.organization_id == organization_id,
                Donor.email == info.email.strip().lower(),
            )
        ).scalar_one_or_none()
        if found:
            return found
    elif info.phone:
        found = session.execute(
            select(Donor).where(
                Donor.organization_id == organization_id,
                Donor.phone == info.phone.strip(),
            )
        ).scalar_one_or_none()
        if found:
            return found

    donor = Donor(
        organization_id=organization_id,
        full_name=None if info.is_anonymous else info.full_name,
        email=info.email.strip().lower() if info.email else None,
        phone=info.phone.strip() if info.phone else None,
        country_code=info.country_code,
        is_anonymous=info.is_anonymous,
    )
    session.add(donor)
    session.flush()  # on a besoin de l'id tout de suite
    return donor


def create_donation(
    session: Session,
    *,
    organization: Organization,
    draft: DonationDraft,
    registry: ProviderRegistry,
    router: PaymentRouter,
    settings: Settings | None = None,
) -> CreatedDonation:
    settings = settings or get_settings()

    # ------------------------------------------------------------- 1. idempotence
    # Deux clics rapides sur « Donner » avec la même clé = un seul don.
    if draft.idempotency_key:
        existing = session.execute(
            select(Donation).where(
                Donation.organization_id == organization.id,
                Donation.idempotency_key == draft.idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            latest = session.execute(
                select(PaymentTransaction)
                .where(PaymentTransaction.donation_id == existing.id)
                .order_by(PaymentTransaction.created_at.desc())
            ).scalars().first()
            return CreatedDonation(
                donation=existing,
                transaction=latest,  # type: ignore[arg-type]
                initiation=None,
                was_duplicate=True,
            )

    # ------------------------------------------------------------ 2. validateurs
    if draft.amount.amount_minor <= 0:
        raise ValueError("Le montant du don doit être strictement positif.")

    donor = find_or_create_donor(session, organization.id, draft.donor)

    # ------------------------------------------------------------------ 3. le don
    donation = Donation(
        organization_id=organization.id,
        reference=generate_donation_reference(session),
        donor_id=donor.id,
        campaign_id=draft.campaign_id,
        contribution_type=ContributionType(draft.contribution_type),
        amount_minor=draft.amount.amount_minor,
        currency=draft.amount.code,
        status=PaymentStatus.PENDING,
        message=draft.message,
        is_anonymous=draft.donor.is_anonymous,
        idempotency_key=draft.idempotency_key,
        metadata_=draft.metadata or None,
    )
    session.add(donation)
    session.flush()

    # --------------------------------------------------------------- 4. routage
    decision = router.resolve(
        session,
        organization_id=organization.id,
        country_code=organization.country_code,
        currency=draft.amount.code,
        payment_method=draft.payment_method,
    )
    provider = registry.get(decision.provider_code)

    # ------------------------------------------------------------ 5. encaissement
    initiation = provider.initiate(
        _payment_request(donation, draft, organization)
    )

    now = utcnow()
    transaction = PaymentTransaction(
        organization_id=organization.id,
        donation_id=donation.id,
        provider_code=provider.code,
        provider_transaction_id=initiation.provider_transaction_id,
        payment_method=PaymentMethod(draft.payment_method),
        status=PaymentStatus.PENDING,
        amount_minor=donation.amount_minor,
        currency=donation.currency,
        provider_response=initiation.raw,
        initiated_at=now,
        expires_at=now + timedelta(seconds=settings.payment_ttl_seconds),
    )
    session.add(transaction)
    session.flush()

    return CreatedDonation(donation=donation, transaction=transaction, initiation=initiation)


def _payment_request(
    donation: Donation, draft: DonationDraft, organization: Organization
) -> Any:
    from ..payments.base import PaymentRequest

    return PaymentRequest(
        reference=donation.reference,
        amount_minor=donation.amount_minor,
        currency=donation.currency,
        payment_method=PaymentMethod(draft.payment_method),
        country_code=organization.country_code,
        payer_phone=draft.donor.phone,
        payer_email=draft.donor.email,
        payer_name=draft.donor.full_name,
        description=f"{organization.name} — {donation.contribution_type.value}",
        metadata={
            "organization_slug": organization.slug,
            "donation_id": str(donation.id),
        },
    )

"""
API publique de don : ce que voit le donateur (aucune authentification).

⚠️ Ces endpoints sont volontairement pauvres en informations : jamais d'e-mail,
jamais de téléphone, jamais de liste de donateurs. Seul le donateur qui connaît
la référence de SON don peut en consulter l'état.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import get_public_organization, get_registry, get_router
from ..domain.enums import ContributionType, PaymentMethod, PaymentStatus
from ..models import Campaign, Donation, Organization, PaymentRoute, PaymentTransaction
from ..money import SUPPORTED_CURRENCIES, Money, MoneyError
from ..payments.base import PaymentProviderError, ProviderNotAvailableError
from ..payments.router import PaymentRouter, ProviderRegistry
from ..schemas import (
    DonationCreateRequest,
    DonationCreateResponse,
    DonationStatusResponse,
    PublicOrganizationResponse,
)
from ..services.donations import DonationDraft, DonorInput, create_donation

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/public", tags=["public"])


# --------------------------------------------------------------------------- #
# Profil public de l'organisation
# --------------------------------------------------------------------------- #
@router.get("/organizations/{slug}", response_model=PublicOrganizationResponse)
def get_organization_profile(
    organization: Organization = Depends(get_public_organization),
    session: Session = Depends(get_session),
) -> PublicOrganizationResponse:
    currencies, methods = _available_options(session, organization)

    campaigns = session.execute(
        select(Campaign).where(
            Campaign.organization_id == organization.id, Campaign.status == "active"
        )
    ).scalars().all()

    return PublicOrganizationResponse(
        name=organization.name,
        slug=organization.slug,
        logo_url=organization.logo_url,
        country_code=organization.country_code,
        default_currency=organization.default_currency,
        supported_currencies=currencies,
        payment_methods=methods,
        support_email=organization.support_email,
        campaigns=[
            {
                "id": str(c.id),
                "slug": c.slug,
                "title": c.title,
                "goal": (
                    Money.from_minor(c.goal_amount_minor, c.currency).display()
                    if c.goal_amount_minor is not None
                    else None
                ),
                "currency": c.currency,
            }
            for c in campaigns
        ],
    )


def _available_options(
    session: Session, organization: Organization
) -> tuple[list[str], list[str]]:
    """Devises et moyens de paiement réellement routables pour cette organisation."""
    routes = session.execute(
        select(PaymentRoute).where(
            PaymentRoute.is_active.is_(True),
            (PaymentRoute.organization_id.is_(None))
            | (PaymentRoute.organization_id == organization.id),
        )
    ).scalars().all()

    currencies = {
        r.currency for r in routes if r.currency and r.currency in SUPPORTED_CURRENCIES
    }
    methods = {r.payment_method for r in routes if r.payment_method}

    # Si une règle globale existe (tout NULL), toutes les options sont ouvertes.
    if any(r.currency is None and r.organization_id is None for r in routes):
        currencies = set(SUPPORTED_CURRENCIES)
    if any(r.payment_method is None and r.organization_id is None for r in routes):
        methods = {PaymentMethod.MOBILE_MONEY, PaymentMethod.CARD}

    return sorted(currencies), sorted(m.value for m in methods)


# --------------------------------------------------------------------------- #
# Création d'un don
# --------------------------------------------------------------------------- #
@router.post(
    "/organizations/{slug}/donations",
    response_model=DonationCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_donation_endpoint(
    payload: DonationCreateRequest,
    request: Request,
    organization: Organization = Depends(get_public_organization),
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    payment_router: PaymentRouter = Depends(get_router),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DonationCreateResponse:
    try:
        amount = Money.from_major(payload.amount, payload.currency)
    except MoneyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    draft = DonationDraft(
        amount=amount,
        payment_method=PaymentMethod(payload.payment_method),
        contribution_type=ContributionType(payload.contribution_type),
        campaign_id=payload.campaign_id,
        message=payload.message,
        donor=DonorInput(
            full_name=payload.donor.full_name,
            email=payload.donor.email,
            phone=payload.donor.phone,
            is_anonymous=payload.donor.is_anonymous,
        ),
        idempotency_key=idempotency_key,
        metadata={
            "source": "public_page",
            "ip": request.client.host if request.client else None,
        },
    )

    try:
        result = create_donation(
            session,
            organization=organization,
            draft=draft,
            registry=registry,
            router=payment_router,
        )
    except ProviderNotAvailableError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except PaymentProviderError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    session.commit()

    return DonationCreateResponse(
        reference=result.donation.reference,
        status=result.donation.status.value,
        amount=Money.from_minor(
            result.donation.amount_minor, result.donation.currency
        ).display(),
        currency=result.donation.currency,
        contribution_type=result.donation.contribution_type.value,
        provider=result.transaction.provider_code,
        payment_method=result.transaction.payment_method.value,
        next_action=result.initiation.next_action if result.initiation else None,
        instructions=result.initiation.instructions if result.initiation else None,
        redirect_url=result.initiation.redirect_url if result.initiation else None,
        status_url=f"/api/v1/public/donations/{result.donation.reference}",
        expires_at=result.transaction.expires_at,
        was_duplicate=result.was_duplicate,
    )


# --------------------------------------------------------------------------- #
# Suivi d'un don (pour la page du donateur)
# --------------------------------------------------------------------------- #
@router.get("/donations/{reference}", response_model=DonationStatusResponse)
def get_donation_status(
    reference: str,
    session: Session = Depends(get_session),
) -> DonationStatusResponse:
    donation: Donation | None = session.execute(
        select(Donation).where(Donation.reference == reference.upper())
    ).scalar_one_or_none()

    if donation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Don introuvable."
        )

    transaction: PaymentTransaction | None = session.execute(
        select(PaymentTransaction)
        .where(PaymentTransaction.donation_id == donation.id)
        .order_by(PaymentTransaction.created_at.desc())
    ).scalars().first()

    return DonationStatusResponse(
        reference=donation.reference,
        status=PaymentStatus(donation.status).value,
        amount=Money.from_minor(donation.amount_minor, donation.currency).display(),
        currency=donation.currency,
        contribution_type=donation.contribution_type.value,
        provider=transaction.provider_code if transaction else None,
        failure_reason=transaction.failure_reason if transaction else None,
        created_at=donation.created_at,
        completed_at=donation.succeeded_at
        or (transaction.completed_at if transaction else None),
    )

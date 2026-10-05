"""
Routage : quel agrégateur traite quel paiement ?

C'est ce qui permettra d'ajouter Stripe/Adyen pour l'euro sans toucher au
reste du système : FlexPaie ne couvre que USD et CDF.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.domain.enums import PaymentMethod
from app.models import Organization, PaymentRoute
from app.payments.base import ProviderNotAvailableError
from app.payments.router import PaymentRouter, build_default_registry


@pytest.fixture
def organization(session: Session) -> Organization:
    org = Organization(name="Test", slug="test-org", country_code="CD", default_currency="USD")
    session.add(org)
    session.commit()
    return org


def add_route(session: Session, **kwargs) -> PaymentRoute:
    route = PaymentRoute(provider_code=kwargs.pop("provider_code"), **kwargs)
    session.add(route)
    session.commit()
    return route


def resolve(session: Session, organization: Organization, **kwargs):
    router = PaymentRouter(build_default_registry())
    return router.resolve(
        session,
        organization_id=organization.id,
        country_code=kwargs.pop("country", "CD"),
        currency=kwargs.pop("currency", "USD"),
        payment_method=kwargs.pop("method", PaymentMethod.MOBILE_MONEY),
    )


def test_la_regle_la_plus_precise_gagne(session: Session, organization: Organization):
    add_route(session, country_code=None, currency=None, payment_method=None,
              provider_code="mock", priority=999)
    add_route(session, country_code="CD", currency="CDF", payment_method=PaymentMethod.MOBILE_MONEY,
              provider_code="flexpaie", priority=100)

    assert resolve(session, organization, currency="CDF").provider_code == "flexpaie"
    # L'euro ne tombe pas dans la règle CDF : il repasse par le filet de secours.
    assert resolve(session, organization, currency="EUR").provider_code == "mock"


def test_une_regle_propre_a_une_organisation_l_emporte(session: Session, organization: Organization):
    add_route(session, country_code="CD", currency="USD", payment_method=None,
              provider_code="mock", priority=1)
    add_route(session, organization_id=organization.id, country_code="CD", currency="USD",
              payment_method=None, provider_code="flexpaie", priority=50)

    assert resolve(session, organization, currency="USD").provider_code == "flexpaie"


def test_une_regle_d_autre_organisation_ne_s_applique_jamais(
    session: Session, organization: Organization
):
    other = Organization(name="Autre", slug="autre-org")
    session.add(other)
    session.commit()

    add_route(session, organization_id=other.id, country_code="CD", currency="USD",
              payment_method=None, provider_code="flexpaie", priority=1)
    add_route(session, country_code=None, currency=None, payment_method=None,
              provider_code="mock", priority=999)

    assert resolve(session, organization).provider_code == "mock"


def test_les_regles_inactives_sont_ignorees(session: Session, organization: Organization):
    add_route(session, country_code="CD", currency="USD", payment_method=None,
              provider_code="flexpaie", priority=1, is_active=False)
    add_route(session, country_code=None, currency=None, payment_method=None,
              provider_code="mock", priority=999)

    assert resolve(session, organization).provider_code == "mock"


def test_aucune_route_disponible_levé_une_erreur_claire(session: Session, organization: Organization):
    add_route(session, country_code="KE", currency="KES", payment_method=None,
              provider_code="mock", priority=1)

    with pytest.raises(ProviderNotAvailableError, match="Aucune route"):
        resolve(session, organization)


def test_les_capacites_reelles_du_prestataire_priment_sur_la_table(
    session: Session, organization: Organization
):
    """Une erreur humaine dans payment_routes ne doit pas produire un paiement invalide."""
    add_route(session, country_code="CD", currency="EUR", payment_method=PaymentMethod.CARD,
              provider_code="flexpaie", priority=1)

    # FlexPaie ne traite pas l'euro (confirmé par leur e-mail) : refus explicite.
    with pytest.raises(ProviderNotAvailableError, match="ne couvre pas"):
        resolve(session, organization, currency="EUR", method=PaymentMethod.CARD)


def test_flexpaie_ne_couvre_que_usd_et_cdf():
    registry = build_default_registry()
    flexpaie = registry.get("flexpaie")

    assert flexpaie.supports("CD", "USD", PaymentMethod.MOBILE_MONEY)
    assert flexpaie.supports("CD", "CDF", PaymentMethod.MOBILE_MONEY)
    assert not flexpaie.supports("CD", "EUR", PaymentMethod.CARD)
    assert not flexpaie.supports("FR", "EUR", PaymentMethod.CARD)


def test_prestataire_inconnu():
    registry = build_default_registry()
    with pytest.raises(ProviderNotAvailableError, match="Prestataire inconnu"):
        registry.get("paypal")

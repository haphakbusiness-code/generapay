"""
Dépendances FastAPI (injection).

Un seul registre de prestataires par processus : les adaptateurs conservent
leur état (le MockProvider garde la mémoire des transactions simulées).
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_session
from .models import Organization
from .payments.router import PaymentRouter, ProviderRegistry, build_default_registry

__all__ = [
    "get_registry",
    "get_router",
    "get_public_organization",
]


@lru_cache
def get_registry() -> ProviderRegistry:
    return build_default_registry()


@lru_cache
def get_router() -> PaymentRouter:
    return PaymentRouter(get_registry())


def get_public_organization(
    slug: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Organization:
    """Récupère une organisation active à partir de son slug public."""
    organization = session.query(Organization).filter(Organization.slug == slug).first()
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation introuvable.",
        )
    if organization.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cette organisation n'accepte pas de dons pour le moment.",
        )
    return organization

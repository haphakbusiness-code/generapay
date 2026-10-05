"""
Références lisibles.

Un donateur qui appelle le support doit pouvoir dire autre chose qu'un UUID.
Format : GP-XXXXXX (alphabet sans caractères ambigus : pas de 0/O ni 1/I).
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Donation

__all__ = ["generate_donation_reference", "generate_receipt_number"]

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _random_token(length: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def generate_donation_reference(session: Session, attempts: int = 10) -> str:
    """Génère une référence unique, vérifiée en base."""
    for _ in range(attempts):
        candidate = f"GP-{_random_token(6)}"
        exists = session.execute(
            select(Donation.id).where(Donation.reference == candidate)
        ).first()
        if exists is None:
            return candidate
    raise RuntimeError("Impossible de générer une référence de don unique.")


def generate_receipt_number(session: Session, attempts: int = 10) -> str:
    from ..models import Receipt

    for _ in range(attempts):
        candidate = f"REC-{_random_token(8)}"
        exists = session.execute(
            select(Receipt.id).where(Receipt.receipt_number == candidate)
        ).first()
        if exists is None:
            return candidate
    raise RuntimeError("Impossible de générer un numéro de reçu unique.")

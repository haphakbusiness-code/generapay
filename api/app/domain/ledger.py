"""
Le grand livre (ledger) — la source de vérité comptable.

Principes :

* **Immuable** : on n'UPDATE jamais une écriture historique. Une correction
  passe par une écriture *compensatrice* (AGENTS.md §11).
* **Signé** : `amount_minor` est positif pour l'argent qui entre dans la
  caisse de l'organisation, négatif pour ce qui en sort (frais, remboursements).
* **Traçable** : chaque écriture pointe vers le don ET la transaction de
  paiement qui l'a produite.
* **Idempotent** : la contrainte unique `(payment_transaction_id, entry_type)`
  garantit qu'un webhook rejoué ne peut pas doubler une écriture.

Exemple pour un don de 10.00 USD avec 2,5 % de commission agrégateur :

    | entry_type    | amount_minor | currency |
    |---------------|--------------|----------|
    | donation      |        +1000 | USD      |
    | provider_fee  |         -25  | USD      |
    | platform_fee  |           0  | USD      |

    Net qui revient à l'organisation : 975 minor = 9.75 USD
"""

from __future__ import annotations

from dataclasses import dataclass

from ..money import Money
from .enums import LedgerEntryType

__all__ = ["PlannedEntry", "plan_success_entries", "fee_from_basis_points", "bps_to_rate"]


def bps_to_rate(basis_points: int) -> float:
    """Points de base -> taux. 250 bp = 2.5 %.

    Le taux est un `float` **uniquement** parce qu'il s'agit d'un ratio, pas
    d'un montant. Le résultat, lui, est immédiatement arrondi en unités mineures.
    """
    if basis_points < 0:
        raise ValueError("basis_points ne peut pas être négatif.")
    return basis_points / 10_000


def fee_from_basis_points(gross: Money, basis_points: int) -> Money:
    """Commission calculée sur le brut, arrondie AU CENTIME SUPÉRIEUR.

    Pourquoi arrondir vers le haut ? Parce que l'agrégateur, lui, prélèvera au
    moins ce montant. Si on arrondissait vers le bas, GeneraPay annoncerait un
    net légèrement supérieur à la réalité — et l'écart se retrouverait dans la
    poche de l'organisation.

    Le calcul est fait en `Decimal` : aucun `float` ne touche l'argent.
    """
    from decimal import ROUND_CEILING, Decimal

    if basis_points == 0:
        return Money.from_minor(0, gross.code)
    if basis_points < 0:
        raise ValueError("basis_points ne peut pas être négatif.")

    exact = Decimal(gross.amount_minor) * Decimal(basis_points) / Decimal(10_000)
    rounded = int(exact.to_integral_value(rounding=ROUND_CEILING))
    return Money.from_minor(rounded, gross.code)


@dataclass(frozen=True)
class PlannedEntry:
    """Une écriture de grand livre à créer, avant insertion en base."""

    entry_type: LedgerEntryType
    amount: Money
    description: str


def plan_success_entries(
    gross: Money,
    provider_fee: Money,
    platform_fee_basis_points: int = 0,
) -> list[PlannedEntry]:
    """Construit la liste des écritures d'un paiement réussi.

    C'est ici — et nulle part ailleurs — que la comptabilité d'un don est décidée.
    """
    if provider_fee.code != gross.code:
        raise ValueError(
            "La commission du prestataire doit être dans la même devise que le don "
            "(on ne convertit jamais de devise pendant le traitement)."
        )

    platform_fee = fee_from_basis_points(gross, platform_fee_basis_points)

    entries = [
        PlannedEntry(
            entry_type=LedgerEntryType.DONATION,
            amount=gross,
            description="Don encaissé (brut)",
        ),
        PlannedEntry(
            entry_type=LedgerEntryType.PROVIDER_FEE,
            amount=Money.from_minor(-abs(provider_fee.amount_minor), gross.code),
            description="Commission agrégateur",
        ),
    ]

    if platform_fee_basis_points:
        entries.append(
            PlannedEntry(
                entry_type=LedgerEntryType.PLATFORM_FEE,
                amount=Money.from_minor(-abs(platform_fee.amount_minor), gross.code),
                description="Commission plateforme GeneraPay",
            )
        )

    return entries

"""
Machine à états des paiements.

    PENDING ──> SUCCESS ──> (écriture au grand livre + reçu)
       │
       ├──> FAILED
       │
       └──> EXPIRED

Trois règles non négociables (AGENTS.md §8) :

1. un SUCCESS ne redevient jamais FAILED (ni EXPIRED) ;
2. on ne saute pas d'état : il n'y a pas de chemin direct vers SUCCESS ;
3. toute tentative illégale lève une erreur explicite plutôt que d'écrire
   silencieusement une valeur fausse dans la base.

Pourquoi c'est vital : un agrégateur peut renvoyer un webhook en retard,
en double, ou dans le désordre. Sans machine à états, le dernier webhook
reçu "gagne" et votre comptabilité devient fausse.
"""

from __future__ import annotations

from .enums import PaymentStatus

__all__ = ["AllowedTransitions", "PaymentStateError", "assert_transition", "can_transition"]


class PaymentStateError(RuntimeError):
    """Transition d'état interdite."""


# La table des transitions autorisées. Absence d'une clé = état terminal.
AllowedTransitions: dict[PaymentStatus, frozenset[PaymentStatus]] = {
    PaymentStatus.PENDING: frozenset(
        {PaymentStatus.SUCCESS, PaymentStatus.FAILED, PaymentStatus.EXPIRED}
    ),
    PaymentStatus.SUCCESS: frozenset(),  # terminal : rien ne sort d'ici
    PaymentStatus.FAILED: frozenset(),   # terminal
    PaymentStatus.EXPIRED: frozenset(),  # terminal
}


def can_transition(current: PaymentStatus, target: PaymentStatus) -> bool:
    """True si la transition est autorisée.

    current == target renvoie True : recevoir deux fois le même statut
    (webhook dupliqué) n'est pas une erreur, c'est une non-opération.
    """
    if current is target:
        return True
    return target in AllowedTransitions.get(current, frozenset())


def assert_transition(current: PaymentStatus, target: PaymentStatus) -> None:
    """Lève `PaymentStateError` si la transition est interdite."""
    if not can_transition(current, target):
        raise PaymentStateError(
            f"Transition interdite : {current.value} -> {target.value}. "
            f"Un état final ne se corrige pas en place : utilisez une écriture "
            f"compensatrice au grand livre."
        )

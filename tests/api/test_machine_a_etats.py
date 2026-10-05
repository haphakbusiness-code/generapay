"""
Machine à états des paiements (AGENTS.md §8).
"""

from __future__ import annotations

import pytest

from app.domain.enums import PaymentStatus
from app.domain.state_machine import (
    PaymentStateError,
    assert_transition,
    can_transition,
)


@pytest.mark.parametrize(
    "current,target",
    [
        (PaymentStatus.PENDING, PaymentStatus.SUCCESS),
        (PaymentStatus.PENDING, PaymentStatus.FAILED),
        (PaymentStatus.PENDING, PaymentStatus.EXPIRED),
    ],
)
def test_transitions_autorisees(current, target):
    assert can_transition(current, target)
    assert_transition(current, target)  # ne lève pas


@pytest.mark.parametrize(
    "current,target",
    [
        (PaymentStatus.SUCCESS, PaymentStatus.FAILED),
        (PaymentStatus.SUCCESS, PaymentStatus.EXPIRED),
        (PaymentStatus.FAILED, PaymentStatus.SUCCESS),
        (PaymentStatus.EXPIRED, PaymentStatus.SUCCESS),
        (PaymentStatus.FAILED, PaymentStatus.PENDING),
    ],
)
def test_transitions_interdites(current, target):
    assert not can_transition(current, target)
    with pytest.raises(PaymentStateError):
        assert_transition(current, target)


def test_recevoir_deux_fois_le_meme_statut_est_une_non_operation():
    assert can_transition(PaymentStatus.SUCCESS, PaymentStatus.SUCCESS)

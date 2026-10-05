"""
Calcul des frais et plan comptable d'un don réussi.

Cas réel : FlexPaie facture 2,5 % (250 points de base) sur Mobile Money
et cartes — chiffre donné par leur e-mail, à confirmer au contrat.
"""

from __future__ import annotations

import pytest

from app.domain.enums import LedgerEntryType
from app.domain.ledger import bps_to_rate, fee_from_basis_points, plan_success_entries
from app.money import Money


def test_conversion_points_de_base():
    assert bps_to_rate(250) == 0.025
    assert bps_to_rate(0) == 0.0


def test_commission_flexpaie_de_2_5_pourcent():
    gross = Money.from_major("10.00", "USD")          # 1000 minor
    fee = fee_from_basis_points(gross, 250)
    assert fee.amount_minor == 25                      # 0.25 USD
    assert fee.code == "USD"


def test_commission_arrondie_au_centime_superieur():
    # 1001 minor x 2.5% = 25.025 -> 26 (jamais 25 : l'agrégateur prélèvera 26)
    gross = Money.from_minor(1001, "USD")
    assert fee_from_basis_points(gross, 250).amount_minor == 26


def test_aucune_commission_si_zero_points_de_base():
    assert fee_from_basis_points(Money.from_major("50", "USD"), 0).amount_minor == 0


def test_commission_en_cdf():
    gross = Money.from_major("50000", "CDF")           # 5 000 000 minor
    assert fee_from_basis_points(gross, 250).amount_minor == 125_000  # 1250 FC


def test_plan_comptable_d_un_don_reussi():
    gross = Money.from_major("10.00", "USD")
    provider_fee = Money.from_minor(25, "USD")

    entries = plan_success_entries(gross, provider_fee)

    assert [e.entry_type for e in entries] == [
        LedgerEntryType.DONATION,
        LedgerEntryType.PROVIDER_FEE,
    ]
    assert entries[0].amount.amount_minor == 1000       # brut, positif
    assert entries[1].amount.amount_minor == -25        # frais, négatif
    # Net qui revient à l'organisation :
    assert sum(e.amount.amount_minor for e in entries) == 975


def test_commission_plateforme_ajoutee_seulement_si_configuree():
    gross = Money.from_major("100.00", "USD")
    entries = plan_success_entries(gross, Money.from_minor(250, "USD"), platform_fee_basis_points=100)
    types = [e.entry_type for e in entries]
    assert LedgerEntryType.PLATFORM_FEE in types
    platform = next(e for e in entries if e.entry_type is LedgerEntryType.PLATFORM_FEE)
    assert platform.amount.amount_minor == -100          # 1 % de 100.00 USD
    assert sum(e.amount.amount_minor for e in entries) == 10000 - 250 - 100


def test_devise_des_frais_doit_correspondre_a_celle_du_don():
    with pytest.raises(ValueError, match="même devise"):
        plan_success_entries(Money.from_major("10", "USD"), Money.from_minor(25, "CDF"))

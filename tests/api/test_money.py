"""
L'argent est la partie du système où une erreur se voit sur un relevé bancaire.
Ces tests verrouillent les règles de AGENTS.md §6.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.money import SUPPORTED_CURRENCIES, Money, MoneyError, parse_amount


def test_les_trois_devises_initiales_sont_declarees():
    assert set(SUPPORTED_CURRENCIES) == {"USD", "CDF", "EUR"}


def test_montant_usd_converti_en_unites_mineures():
    assert Money.from_major("10.00", "USD").amount_minor == 1000
    assert Money.from_major("0.01", "USD").amount_minor == 1
    assert Money.from_major(25, "USD").amount_minor == 2500


def test_le_cdf_est_stocke_selon_iso_4217_mais_affiche_sans_decimale():
    # ISO 4217 : le CDF a 2 décimales -> 5000 FC = 500 000 unités mineures.
    money = Money.from_major("5000", "CDF")
    assert money.amount_minor == 500_000
    # Mais personne n'écrit "5 000,00 FC" sur une page de don.
    assert money.display() == "5000"
    assert money.major_decimal() == Decimal("5000.00")


def test_les_float_sont_refuses():
    with pytest.raises(MoneyError, match="float"):
        Money.from_major(10.50, "USD")


def test_devise_inconnue_refusee():
    with pytest.raises(MoneyError, match="non supportée"):
        Money.from_major("10", "XOF")


def test_montant_negatif_refuse():
    with pytest.raises(MoneyError, match="négatif"):
        Money.from_major("-5", "USD")


def test_precision_excessive_refusee_plutot_qu_arrondie_en_silence():
    # 10.005 USD n'existe pas : mieux vaut refuser que d'arrondir sans trace.
    with pytest.raises(MoneyError, match="précision"):
        Money.from_major("10.005", "USD")


def test_format_avec_virgule_accepte():
    # Habitude francophone : "10,50".
    assert Money.from_major("10,50", "USD").amount_minor == 1050


def test_aller_retour_unites_mineures():
    money = Money.from_minor(123456, "CDF")
    assert money.display() == "1235"  # 1234.56 FC arrondi à l'affichage
    assert money.amount_minor == 123456


def test_money_est_immuable():
    money = Money.from_major("10", "USD")
    with pytest.raises(Exception):
        money.amount_minor = 999  # type: ignore[misc]


def test_parse_amount_est_un_alias():
    assert parse_amount("1.00", "EUR").amount_minor == 100

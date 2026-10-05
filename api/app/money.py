"""
Représentation de l'argent dans GeneraPay.

RÈGLE ABSOLUE (AGENTS.md §6) : on n'utilise JAMAIS de `float` pour de l'argent.

    >>> 0.1 + 0.2
    0.30000000000000004        # <- interdit dans un système financier

À la place :

1. on stocke toujours des **unités mineures entières** (`int`) : 10.00 USD -> 1000 ;
2. on garde toujours la **devise** à côté du montant (ISO 4217) ;
3. on ne convertit jamais une devise en une autre pendant le paiement :
   le montant et la devise d'origine sont sacrés.

Ce module est la seule porte d'entrée pour fabriquer un montant.
Si un montant passe par autre chose qu'ici, c'est un bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

__all__ = [
    "Currency",
    "Money",
    "SUPPORTED_CURRENCIES",
    "MoneyError",
    "parse_amount",
]


class MoneyError(ValueError):
    """Erreur de manipulation monétaire (devise inconnue, format invalide...)."""


@dataclass(frozen=True)
class Currency:
    """Métadonnées ISO 4217 d'une devise.

    exponent          : nombre de décimales officielles de l'unité mineure.
                        C'est lui qui définit ce qu'est une "unité mineure"
                        (USD -> 2 : le cent).
    display_decimals  : nombre de décimales affichées à l'utilisateur.
                        Pour le CDF, l'ISO dit 2 mais personne en RDC n'écrit
                        "5 000,00 FC" -> on affiche 0 décimale.
                        Les DEUX valeurs sont volontairement séparées :
                        le stockage ne doit jamais dépendre de l'affichage.
    """

    code: str
    exponent: int
    display_decimals: int
    label: str

    @property
    def scale(self) -> int:
        """Multiplicateur entre unité majeure et unité mineure (USD -> 100)."""
        return 10**self.exponent


# Devises initiales (AGENTS.md §6). Ajouter une devise = ajouter une ligne ici
# + la déclarer dans les routes de paiement. Rien d'autre à modifier.
SUPPORTED_CURRENCIES: dict[str, Currency] = {
    c.code: c
    for c in (
        Currency(code="USD", exponent=2, display_decimals=2, label="Dollar américain"),
        Currency(code="CDF", exponent=2, display_decimals=0, label="Franc congolais"),
        Currency(code="EUR", exponent=2, display_decimals=2, label="Euro"),
    )
}


def _reject_float(value: object) -> None:
    """Un `float` est refusé sans négociation : il a déjà perdu de la précision."""
    if isinstance(value, float):
        raise MoneyError(
            "Les float sont interdits pour l'argent. "
            "Passez une chaîne ('10.00') ou un Decimal."
        )


@dataclass(frozen=True)
class Money:
    """Un montant immuable : unités mineures + devise."""

    amount_minor: int
    currency: Currency

    # ---------------------------------------------------------------- fabriques

    @classmethod
    def from_major(cls, value: str | int | Decimal, currency_code: str) -> "Money":
        """Construit à partir d'un montant "humain" : Money.from_major('10.50', 'USD')."""
        cur = _currency(currency_code)
        _reject_float(value)

        if isinstance(value, int):
            decimal_value = Decimal(value)
        else:
            try:
                decimal_value = Decimal(str(value).replace(",", ".").strip())
            except (InvalidOperation, ValueError) as exc:
                raise MoneyError(f"Montant invalide : {value!r}") from exc

        if not decimal_value.is_finite():
            raise MoneyError(f"Montant invalide : {value!r}")
        if decimal_value < 0:
            raise MoneyError("Un montant ne peut pas être négatif.")

        quant = Decimal(1).scaleb(-cur.exponent)  # 0.01 si exponent == 2
        rounded = decimal_value.quantize(quant, rounding=ROUND_HALF_UP)

        # Un "10.005 USD" arrondi silencieusement = argent perdu sans trace.
        # On préfère refuser et laisser l'appelant décider.
        if rounded != decimal_value:
            raise MoneyError(
                f"Le montant {value!r} {cur.code} dépasse la précision de la devise "
                f"({cur.exponent} décimale(s))."
            )

        return cls(amount_minor=int(rounded.scaleb(cur.exponent)), currency=cur)

    @classmethod
    def from_minor(cls, amount_minor: int, currency_code: str) -> "Money":
        """Construit à partir d'unités mineures déjà entières (ce qui vient de la BDD)."""
        cur = _currency(currency_code)
        _reject_float(amount_minor)
        if not isinstance(amount_minor, int):
            raise MoneyError("amount_minor doit être un entier.")
        return cls(amount_minor=amount_minor, currency=cur)

    # ------------------------------------------------------------------ sorties

    @property
    def code(self) -> str:
        return self.currency.code

    def major_decimal(self) -> Decimal:
        """Le montant en unité majeure, en Decimal (jamais en float)."""
        return Decimal(self.amount_minor).scaleb(-self.currency.exponent)

    def display(self) -> str:
        """Chaîne prête pour l'affichage : '10.00' (USD), '5000' (CDF)."""
        quant = Decimal(1).scaleb(-self.currency.display_decimals)
        return str(self.major_decimal().quantize(quant, rounding=ROUND_HALF_UP))

    def __str__(self) -> str:  # pragma: no cover - confort de debug
        return f"{self.display()} {self.code}"


def _currency(currency_code: str) -> Currency:
    if not isinstance(currency_code, str):
        raise MoneyError("La devise doit être un code ISO 4217 (texte).")
    cur = SUPPORTED_CURRENCIES.get(currency_code.strip().upper())
    if cur is None:
        raise MoneyError(
            f"Devise non supportée : {currency_code!r}. "
            f"Supportées : {', '.join(sorted(SUPPORTED_CURRENCIES))}."
        )
    return cur


def parse_amount(value: str | int | Decimal, currency_code: str) -> Money:
    """Alias lisible pour les couches API : parse_amount('10.00', 'USD')."""
    return Money.from_major(value, currency_code)

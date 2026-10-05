"""
Registre des prestataires + routage.

Le routage répond à une seule question :
« Pour CE pays, CETTE devise et CE moyen de paiement, quel agrégateur utilise-t-on ? »

Il se base sur la table `payment_routes`, ce qui permet de changer de
prestataire SANS redéployer de code (une ligne en base suffit).

Score de spécificité : plus une règle est précise, plus elle gagne.

    organisation dédiée  +4
    pays exact           +3
    devise exacte        +2
    moyen de paiement    +1

À spécificité égale, la priorité numérique la plus basse gagne.
Une règle avec NULL partout est le filet de secours de la plateforme.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import PaymentMethod
from ..models import PaymentRoute
from .base import PaymentProvider, ProviderNotAvailableError
from .flexpaie import FlexpaieProvider
from .mock import MockProvider

__all__ = ["ProviderRegistry", "RoutingDecision", "PaymentRouter", "build_default_registry"]


# --------------------------------------------------------------------------- #
# Registre
# --------------------------------------------------------------------------- #
class ProviderRegistry:
    """Annuaire des adaptateurs disponibles dans ce déploiement."""

    def __init__(self, providers: Iterable[PaymentProvider] = ()) -> None:
        self._providers: dict[str, PaymentProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: PaymentProvider) -> None:
        if provider.code in self._providers:
            raise ValueError(f"Prestataire déjà enregistré : {provider.code}")
        self._providers[provider.code] = provider

    def get(self, code: str) -> PaymentProvider:
        try:
            return self._providers[code]
        except KeyError as exc:
            raise ProviderNotAvailableError(
                f"Prestataire inconnu : {code!r}. Disponibles : {self.codes()}"
            ) from exc

    def codes(self) -> list[str]:
        return sorted(self._providers)

    def all(self) -> list[PaymentProvider]:
        return [self._providers[c] for c in self.codes()]


def build_default_registry() -> ProviderRegistry:
    """Construit le registre par défaut à partir de la configuration."""
    return ProviderRegistry([MockProvider(), FlexpaieProvider()])


# --------------------------------------------------------------------------- #
# Routage
# --------------------------------------------------------------------------- #
class RoutingDecision:
    """Résultat du routage : quel prestataire, et pourquoi."""

    def __init__(self, provider_code: str, rule: PaymentRoute | None, score: int) -> None:
        self.provider_code = provider_code
        self.rule = rule
        self.score = score

    def __repr__(self) -> str:  # pragma: no cover - debug
        return f"<RoutingDecision provider={self.provider_code} score={self.score}>"


class PaymentRouter:
    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def resolve(
        self,
        session: Session,
        *,
        organization_id,
        country_code: str,
        currency: str,
        payment_method: PaymentMethod,
    ) -> RoutingDecision:
        """Choisit le prestataire applicable, en validant ses capacités réelles."""
        rules = session.execute(
            select(PaymentRoute).where(PaymentRoute.is_active.is_(True))
        ).scalars().all()

        best: RoutingDecision | None = None

        for rule in rules:
            # Une règle propre à une autre organisation ne s'applique jamais.
            if rule.organization_id is not None and rule.organization_id != organization_id:
                continue
            if not self._matches(rule, country_code, currency, payment_method):
                continue

            score = self._score(rule, organization_id, country_code, currency, payment_method)
            if best is None or score > best.score or (
                score == best.score and rule.priority < (best.rule.priority if best.rule else 0)
            ):
                best = RoutingDecision(rule.provider_code, rule, score)

        if best is None:
            raise ProviderNotAvailableError(
                f"Aucune route de paiement pour {country_code}/{currency}/"
                f"{payment_method.value}. Ajoutez une ligne dans payment_routes."
            )

        # Double sécurité : la table de routage peut mentir (erreur humaine),
        # les capacités déclarées par l'adaptateur, elles, viennent du contrat.
        provider = self.registry.get(best.provider_code)
        if not provider.supports(country_code, currency, payment_method):
            raise ProviderNotAvailableError(
                f"{provider.display_name} ne couvre pas {country_code}/{currency}/"
                f"{payment_method.value}. Capacités : {provider.capabilities}"
            )
        return best

    # ------------------------------------------------------------------ interne
    @staticmethod
    def _matches(
        rule: PaymentRoute,
        country_code: str,
        currency: str,
        payment_method: PaymentMethod,
    ) -> bool:
        if rule.country_code and rule.country_code.upper() != country_code.upper():
            return False
        if rule.currency and rule.currency.upper() != currency.upper():
            return False
        if rule.payment_method and rule.payment_method != payment_method:
            return False
        return True

    @staticmethod
    def _score(
        rule: PaymentRoute,
        organization_id,
        country_code: str,
        currency: str,
        payment_method: PaymentMethod,
    ) -> int:
        score = 0
        if rule.organization_id is not None and rule.organization_id == organization_id:
            score += 4
        if rule.country_code and rule.country_code.upper() == country_code.upper():
            score += 3
        if rule.currency and rule.currency.upper() == currency.upper():
            score += 2
        if rule.payment_method and rule.payment_method == payment_method:
            score += 1
        return score

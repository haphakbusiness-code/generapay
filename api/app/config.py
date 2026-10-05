"""
Configuration de l'API (12-factor : tout passe par l'environnement).

⚠️ Aucune clé ne doit jamais être commitée ni envoyée au navigateur
(AGENTS.md §13). `web/` ne voit que ce que l'API choisit de lui répondre.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="GENERAPAY_",
        extra="ignore",
    )

    # ------------------------------------------------------------------ service
    app_name: str = "generapay-api"
    environment: str = "development"  # development | staging | production
    version: str = "0.1.0"

    # ---------------------------------------------------------------- base
    # Production  : postgresql+psycopg://user:pass@host:5432/postgres
    # Tests locaux: sqlite:///./generapay.db  (ou sqlite+pysqlite:///:memory:)
    database_url: str = "sqlite:///./generapay.db"
    database_echo: bool = False

    # ---------------------------------------------------------------- sécurité
    # Utilisé par l'API pour vérifier les JWT Supabase (étape 3 du plan).
    supabase_url: str = ""
    supabase_service_role_key: str = ""  # serveur uniquement, JAMAIS côté client
    jwt_secret: str = ""

    # ---------------------------------------------------------------- paiements
    # `mock` tant que FlexPaie n'a pas livré sa documentation technique.
    default_provider: str = "mock"
    payment_ttl_seconds: int = 15 * 60  # un paiement non confirmé expire après 15 min
    platform_fee_bps: int = 0           # commission GeneraPay : 0 au MVP

    # Clé HMAC du MockProvider (simule le secret de signature d'un agrégateur).
    mock_webhook_secret: str = "mock-dev-secret-change-me"

    # --- FlexPaie : à remplir UNIQUEMENT quand les accès sandbox sont livrés ---
    flexpaie_base_url: str = ""
    flexpaie_api_key: str = ""
    flexpaie_webhook_secret: str = ""
    # FlexPaie ne documente pas encore son schéma de signature. Tant que ce
    # n'est pas confirmé, l'adaptateur REFUSE les webhooks (fail-closed).
    flexpaie_signature_header: str = "x-flexpaie-signature"
    flexpaie_signature_scheme: str = "unverified"  # hmac-sha256 | unverified
    flexpaie_fee_bps: int = 250  # 2,5 % annoncés par e-mail — à confirmer au contrat

    # Autorise les endpoints de simulation (démonstration/tests). Désactivé en prod.
    allow_testing_endpoints: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()

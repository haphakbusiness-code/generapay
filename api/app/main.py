"""
Point d'entrée de l'API GeneraPay.

    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Trois couches, et jamais d'autre :

    api/       -> HTTP : validation, format des réponses, codes d'erreur
    services/  -> métier : dons, webhooks, réconciliation, comptabilité
    models.py  -> données

Les règles de sécurité financières (idempotence, machine à états, grand livre)
vivent dans `services/` : elles doivent rester vraies quel que soit le canal
(API publique, tableau de bord, job de nuit, future application mobile).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import routes_health, routes_public, routes_testing, routes_webhooks
from .config import get_settings
from .money import MoneyError
from .payments.base import PaymentProviderError, ProviderNotAvailableError

__all__ = ["create_app", "app"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("generapay")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "GeneraPay API %s — environnement=%s — prestataire par défaut=%s",
        settings.version,
        settings.environment,
        settings.default_provider,
    )
    if settings.environment != "production" and settings.database_url.startswith("sqlite"):
        # Confort de développement uniquement : en production, le schéma vient
        # exclusivement de supabase/migrations/.
        from .db import get_engine
        from .models import Base
        from .db import session_scope

        Base.metadata.create_all(get_engine())
        if settings.allow_testing_endpoints:
            from .seed import seed_demo_data

            with session_scope() as session:
                seed_demo_data(session)
            logger.info("Bac à sable initialisé (organisation de démonstration créée).")
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="HAPHAK GeneraPay API",
        version=settings.version,
        description=(
            "Plateforme multi-organisations de collecte de dons et offrandes. "
            "Multi-devises (USD, CDF, EUR), multi-prestataires."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.environment != "production" else [],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes_health.router)
    app.include_router(routes_public.router)
    app.include_router(routes_webhooks.router)
    if settings.allow_testing_endpoints:
        app.include_router(routes_testing.router)

    @app.get("/", tags=["système"])
    def root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "version": settings.version,
            "health": "/health",
            "docs": "/docs",
        }

    # ------------------------------------------------------- gestion des erreurs
    @app.exception_handler(MoneyError)
    async def _money_error(_: Request, exc: MoneyError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ProviderNotAvailableError)
    async def _not_available(_: Request, exc: ProviderNotAvailableError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(PaymentProviderError)
    async def _provider_error(_: Request, exc: PaymentProviderError) -> JSONResponse:
        logger.warning("Erreur prestataire : %s", exc)
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    return app


app = create_app()

"""Sonde de vie : utilisée par le PaaS, le monitoring et les déploiements."""

from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..db import check_database
from ..schemas import HealthResponse

__all__ = ["router"]

router = APIRouter(tags=["système"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """`degraded` si la base ne répond pas : le processus vit mais ne sert à rien."""
    settings = get_settings()
    db_ok = check_database()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        service=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        database=db_ok,
    )

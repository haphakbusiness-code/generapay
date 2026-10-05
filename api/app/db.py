"""
Connexion à la base.

En production : PostgreSQL (Supabase).
En local / tests : SQLite, pour pouvoir lancer la suite de tests sans serveur.

La source de vérité du schéma de production reste `supabase/migrations/` :
ces fichiers SQL contiennent en plus la RLS, les triggers et les contraintes
que SQLite ne sait pas gérer. Le test
`tests/api/test_migrations_et_modeles.py` vérifie que les deux ne divergent pas.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

__all__ = ["get_engine", "SessionLocal", "get_session", "session_scope", "check_database"]

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    """Un seul moteur par processus (pool de connexions réutilisé)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        kwargs: dict = {"future": True, "echo": settings.database_echo}
        if url.startswith("sqlite"):
            # Nécessaire pour que plusieurs threads de FastAPI partagent SQLite.
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
    return _engine


def _session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _SessionLocal


def SessionLocal() -> Session:  # noqa: N802 - nom d'usage SQLAlchemy
    return _session_factory()()


def get_session() -> Iterator[Session]:
    """Dépendance FastAPI : une session par requête, toujours refermée."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Contexte transactionnel pour les jobs (réconciliation, scripts)."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> bool:
    """Sonde de vie : vrai si la base répond."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def reset_engine() -> None:
    """Réinitialise l'état global (utile entre deux configurations de test)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None

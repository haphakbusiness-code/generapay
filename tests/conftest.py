"""
Fixtures de test.

Tout tourne sur SQLite en mémoire de fichier : la suite complète s'exécute
sans serveur PostgreSQL, donc aussi bien sur votre machine qu'en CI.
Ce qui est testé ici est la LOGIQUE FINANCIÈRE (idempotence, machine à états,
grand livre, routage) — elle est identique quel que soit le moteur SQL.
La RLS Supabase, elle, est vérifiée séparément (voir docs/03-...).
"""

from __future__ import annotations

import os
import pathlib
import tempfile

# ⚠️ À faire AVANT tout import de l'application : la configuration est mise en cache.
_TMP_DIR = pathlib.Path(tempfile.mkdtemp(prefix="generapay-tests-"))
os.environ["GENERAPAY_DATABASE_URL"] = f"sqlite:///{_TMP_DIR / 'test.db'}"
os.environ["GENERAPAY_ENVIRONMENT"] = "test"
os.environ["GENERAPAY_ALLOW_TESTING_ENDPOINTS"] = "true"
os.environ["GENERAPAY_MOCK_WEBHOOK_SECRET"] = "secret-de-test"
os.environ["GENERAPAY_PLATFORM_FEE_BPS"] = "0"
os.environ.pop("GENERAPAY_FLEXPAIE_API_KEY", None)
os.environ.pop("GENERAPAY_FLEXPAIE_BASE_URL", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import get_engine, reset_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Organization  # noqa: E402
from app.seed import seed_demo_data  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database_schema():
    """Crée le schéma une fois pour toute la session de tests."""
    Base.metadata.create_all(get_engine())
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def clean_tables():
    """Vide les tables entre chaque test : aucun état ne fuite d'un test à l'autre."""
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def session() -> Session:
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def organization(session: Session) -> Organization:
    """Organisation de démonstration + routes de paiement par défaut."""
    return seed_demo_data(session)


@pytest.fixture
def client() -> TestClient:
    # Sans `with` : le lifespan (qui sèmerait des données) n'est pas déclenché,
    # ce sont les fixtures ci-dessus qui contrôlent l'état de la base.
    return TestClient(app)

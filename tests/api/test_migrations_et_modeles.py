"""
Garde-fou : le modèle ORM (utilisé par l'API et les tests SQLite) et les
migrations SQL (source de vérité PostgreSQL/Supabase) ne doivent JAMAIS diverger.

Sans ce test, la dérive est garantie : on ajoute une colonne dans le code, on
oublie la migration, et la production tombe au déploiement suivant.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.models import Base

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"

CONSTRAINT_KEYWORDS = {"primary", "unique", "foreign", "check", "constraint", "exclude", "like"}


def _split_top_level(body: str) -> list[str]:
    """Découpe le corps d'un CREATE TABLE sur les virgules de premier niveau."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    in_quote = False

    for char in body:
        if char == "'":
            in_quote = not in_quote
        elif not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append("".join(current))
                current = []
                continue
        current.append(char)

    if current:
        parts.append("".join(current))
    return parts


def _strip_sql_comments(sql: str) -> str:
    """Retire les commentaires `--` en respectant les chaînes entre apostrophes.

    Indispensable : un commentaire comme « -- signé : + encaissement, - frais »
    contient une virgule, et un découpage naïf y verrait une colonne de plus.
    """
    out: list[str] = []
    in_quote = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "'":
            in_quote = not in_quote
            out.append(char)
            index += 1
            continue
        if not in_quote and sql.startswith("--", index):
            while index < len(sql) and sql[index] != "\n":
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def tables_from_migrations() -> dict[str, set[str]]:
    """Extrait tables et colonnes des fichiers SQL de migration."""
    tables: dict[str, set[str]] = {}

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert sql_files, f"Aucune migration trouvée dans {MIGRATIONS_DIR}"

    for path in sql_files:
        sql = _strip_sql_comments(path.read_text(encoding="utf-8"))
        for match in re.finditer(
            r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?(\w+)\s*\(",
            sql,
            re.IGNORECASE,
        ):
            name = match.group(1).lower()
            depth = 1
            index = match.end()
            while index < len(sql) and depth > 0:
                if sql[index] == "(":
                    depth += 1
                elif sql[index] == ")":
                    depth -= 1
                index += 1

            body = sql[match.end() : index - 1]
            columns = set()
            for part in _split_top_level(body):
                part = part.strip()
                if not part:
                    continue
                first = part.split()[0].strip('"').lower()
                if first in CONSTRAINT_KEYWORDS:
                    continue
                columns.add(first)

            tables.setdefault(name, set()).update(columns)

    return tables


def tables_from_models() -> dict[str, set[str]]:
    return {
        name: {column.name for column in table.columns}
        for name, table in Base.metadata.tables.items()
    }


def test_les_migrations_couvrent_exactement_le_modele():
    migrations = tables_from_migrations()
    models = tables_from_models()

    assert set(migrations) == set(models), (
        "Tables manquantes dans les migrations : "
        f"{sorted(set(models) - set(migrations))} ; "
        f"tables en trop : {sorted(set(migrations) - set(models))}"
    )

    for table, model_columns in sorted(models.items()):
        sql_columns = migrations[table]
        assert sql_columns == model_columns, (
            f"Divergence sur {table} — "
            f"colonnes absentes des migrations : {sorted(model_columns - sql_columns)} ; "
            f"colonnes absentes du modèle : {sorted(sql_columns - model_columns)}"
        )


def test_toutes_les_tables_sensibles_ont_la_rls_activee():
    rls_sql = (MIGRATIONS_DIR / "0003_row_level_security.sql").read_text(encoding="utf-8")
    protected = set(re.findall(r"alter\s+table\s+public\.(\w+)\s+enable\s+row\s+level\s+security",
                               rls_sql, re.IGNORECASE))

    # Tables qui contiennent des données d'organisation : isolation obligatoire.
    expected = {
        "organizations",
        "organization_members",
        "donors",
        "campaigns",
        "donations",
        "payment_transactions",
        "webhook_events",
        "ledger_entries",
        "payment_routes",
        "merchant_accounts",
        "receipts",
        "notifications",
        "audit_logs",
    }
    assert expected <= protected, f"RLS manquante sur : {sorted(expected - protected)}"


def test_le_grand_livre_est_protege_par_un_trigger_d_immuabilite():
    integrity = (MIGRATIONS_DIR / "0004_integrite_financiere.sql").read_text(encoding="utf-8")
    assert "trg_ledger_no_update" in integrity
    assert "trg_ledger_no_delete" in integrity
    assert "trg_pmt_no_status_regression" in integrity


def test_les_migrations_sont_numerotees_dans_l_ordre():
    names = [p.name for p in sorted(MIGRATIONS_DIR.glob("*.sql"))]
    prefixes = [name.split("_")[0] for name in names]
    assert prefixes == sorted(prefixes), f"Ordre de migration incohérent : {names}"


@pytest.mark.parametrize("table", sorted(tables_from_models()))
def test_chaque_table_a_une_migration_correspondante(table: str):
    assert table in tables_from_migrations(), f"Aucun CREATE TABLE pour {table}"

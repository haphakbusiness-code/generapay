"""
Types de colonnes réutilisables, compatibles PostgreSQL (production, Supabase)
et SQLite (tests locaux sans serveur de base).

Ces deux adaptateurs évitent les deux pièges classiques du multi-backend :

* `EnumText`  : une énumération Python stockée en TEXT + contrainte CHECK,
                au lieu d'un `ENUM` PostgreSQL difficile à faire évoluer
                (un `ALTER TYPE` est une opération à risque en production).
* `UTCDateTime`: des horodatages toujours conscient de leur fuseau (UTC).
                SQLite rend des datetimes "naïfs" : sans cette couche, on se
                retrouve avec `TypeError: can't compare offset-naive and
                offset-aware datetimes` le jour où l'on écrit la réconciliation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import String, TypeDecorator

__all__ = ["EnumText", "UTCDateTime"]


class EnumText(TypeDecorator):
    """Stocke une `StrEnum` Python sous forme de texte."""

    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type[StrEnum], length: int = 40, **kwargs: Any) -> None:
        super().__init__(length=length, **kwargs)
        self.enum_cls = enum_cls

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return str(value.value)
        return str(self.enum_cls(value).value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return self.enum_cls(value)


class UTCDateTime(TypeDecorator):
    """TIMESTAMP WITH TIME ZONE qui rend toujours un datetime UTC conscient."""

    impl = String(32)  # surchargé par `load_dialect_impl` pour PostgreSQL
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        from sqlalchemy import DateTime

        if dialect.name == "postgresql":
            return dialect.type_descriptor(DateTime(timezone=True))
        return dialect.type_descriptor(String(32))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"datetime attendu, reçu {type(value)!r}")
        if value.tzinfo is None:
            # Un horodatage naïf est considéré comme UTC, puis explicité.
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        if dialect.name == "postgresql":
            return value
        return value.isoformat()

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return datetime.fromisoformat(value)

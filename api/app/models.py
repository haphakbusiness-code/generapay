"""
Modèle de données GeneraPay (couche ORM).

RÈGLE D'OR DU MULTI-TENANT (AGENTS.md §2) :
    toute donnée appartenant à une organisation porte `organization_id`.
Sans cette colonne, une fuite entre deux églises est inévitable un jour ou
l'autre. Elle est aussi le pivot de la Row Level Security en base.

RÈGLE D'OR DE L'ARGENT (AGENTS.md §6) :
    `amount_minor` (entier) + `currency` (ISO 4217). Jamais de float.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .db_types import EnumText, UTCDateTime
from .domain.enums import (
    ContributionType,
    LedgerEntryType,
    OrganizationRole,
    PaymentMethod,
    PaymentStatus,
    SettlementMode,
)

__all__ = [
    "Base",
    "Organization",
    "OrganizationMember",
    "Donor",
    "Campaign",
    "Donation",
    "PaymentTransaction",
    "WebhookEvent",
    "LedgerEntry",
    "PaymentRoute",
    "MerchantAccount",
    "Receipt",
    "Notification",
    "AuditLog",
]


# Conventions de nommage explicites : indispensable pour que les migrations
# générées plus tard produisent des noms d'index/constraintes stables.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# JSONB sur PostgreSQL, JSON ailleurs (SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _timestamps() -> tuple:
    return (
        mapped_column(UTCDateTime, nullable=False, server_default=func.now()),
        mapped_column(
            UTCDateTime, nullable=False, server_default=func.now(), onupdate=func.now()
        ),
    )


# --------------------------------------------------------------------------- #
# ORGANISATION (le tenant)
# --------------------------------------------------------------------------- #
class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Identifiant public utilisé dans l'URL de la page de don : /don/{slug}
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="CD")
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    support_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    created_at, updated_at = _timestamps()

    members: Mapped[list[OrganizationMember]] = relationship(back_populates="organization")
    donations: Mapped[list[Donation]] = relationship(back_populates="organization")


# --------------------------------------------------------------------------- #
# MEMBRES (identité Supabase ≠ appartenance à une organisation)
# --------------------------------------------------------------------------- #
class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # UUID de `auth.users` côté Supabase. Pas de clé étrangère : deux systèmes.
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    role: Mapped[OrganizationRole] = mapped_column(
        EnumText(OrganizationRole), nullable=False, default=OrganizationRole.VIEWER
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at, updated_at = _timestamps()

    organization: Mapped[Organization] = relationship(back_populates="members")


# --------------------------------------------------------------------------- #
# DONATEURS
# --------------------------------------------------------------------------- #
class Donor(Base):
    __tablename__ = "donors"
    __table_args__ = (
        # Un donateur est unique par organisation ET par canal d'identification.
        # Les index partiels évitent les collisions entre donateurs anonymes.
        Index(
            "ix_donors_org_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
            sqlite_where=text("email IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at, updated_at = _timestamps()


# --------------------------------------------------------------------------- #
# CAMPAGNES
# --------------------------------------------------------------------------- #
class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_campaign_org_slug"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    created_at, updated_at = _timestamps()


# --------------------------------------------------------------------------- #
# DONS (l'intention du donateur)
# --------------------------------------------------------------------------- #
class Donation(Base):
    """Un don = ce que le donateur a décidé de donner.

    Un don peut donner lieu à plusieurs tentatives de paiement (échec puis
    réessai) : c'est le rôle de `payment_transactions`.
    """

    __tablename__ = "donations"
    __table_args__ = (
        # Idempotence côté client : deux POST avec la même clé ne créent qu'un don.
        Index(
            "ix_donations_org_idempotency",
            "organization_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_donations_org_created", "organization_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Référence lisible pour le donateur et le support : GP-8F3K2Q
    reference: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    donor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("donors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contribution_type: Mapped[ContributionType] = mapped_column(
        EnumText(ContributionType), nullable=False, default=ContributionType.DONATION
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        EnumText(PaymentStatus), nullable=False, default=PaymentStatus.PENDING
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Contexte utile au debugging : ip, user-agent, source de la page.
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONType, nullable=True)
    succeeded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    created_at, updated_at = _timestamps()

    organization: Mapped[Organization] = relationship(back_populates="donations")
    transactions: Mapped[list[PaymentTransaction]] = relationship(
        back_populates="donation", order_by="PaymentTransaction.created_at"
    )
    ledger_entries: Mapped[list[LedgerEntry]] = relationship(back_populates="donation")


# --------------------------------------------------------------------------- #
# TRANSACTIONS DE PAIEMENT (une tentative chez un prestataire)
# --------------------------------------------------------------------------- #
class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    __table_args__ = (
        # Un même identifiant prestataire ne peut pas être enregistré deux fois :
        # c'est ce qui rend un webhook dupliqué inoffensif.
        Index(
            "ix_pmt_provider_txn",
            "provider_code",
            "provider_transaction_id",
            unique=True,
            postgresql_where=text("provider_transaction_id IS NOT NULL"),
            sqlite_where=text("provider_transaction_id IS NOT NULL"),
        ),
        Index("ix_pmt_org_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    donation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("donations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        EnumText(PaymentMethod), nullable=False, default=PaymentMethod.MOBILE_MONEY
    )
    status: Mapped[PaymentStatus] = mapped_column(
        EnumText(PaymentStatus), nullable=False, default=PaymentStatus.PENDING
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Le statut brut tel que renvoyé par le prestataire (traçabilité).
    provider_status_raw: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ce que le prestataire a renvoyé (prompt USSD, numéro à appeler, URL 3DS...).
    provider_response: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    initiated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    created_at, updated_at = _timestamps()

    donation: Mapped[Donation] = relationship(back_populates="transactions")
    ledger_entries: Mapped[list[LedgerEntry]] = relationship(back_populates="payment_transaction")


# --------------------------------------------------------------------------- #
# ÉVÉNEMENTS WEBHOOK (journal brut + preuve d'idempotence)
# --------------------------------------------------------------------------- #
class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider_code", "provider_event_id", name="uq_webhook_event"),
        Index("ix_webhook_events_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Le corps brut est conservé INTÉGRALEMENT : c'est la pièce à conviction
    # en cas de litige avec l'agrégateur.
    raw_payload: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at, updated_at = _timestamps()


# --------------------------------------------------------------------------- #
# GRAND LIVRE (immuable)
# --------------------------------------------------------------------------- #
class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        # Un webhook rejoué ne peut pas doubler une écriture.
        UniqueConstraint(
            "payment_transaction_id", "entry_type", name="uq_ledger_txn_type"
        ),
        Index("ix_ledger_org_created", "organization_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    donation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("donations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payment_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_transactions.id", ondelete="SET NULL"), nullable=True
    )
    entry_type: Mapped[LedgerEntryType] = mapped_column(
        EnumText(LedgerEntryType), nullable=False
    )
    # Signé : + encaissement, - frais / remboursement.
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Aucune colonne `updated_at` : une écriture comptable ne se modifie pas.
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now()
    )

    donation: Mapped[Donation] = relationship(back_populates="ledger_entries")
    payment_transaction: Mapped[PaymentTransaction] = relationship(
        back_populates="ledger_entries"
    )


# --------------------------------------------------------------------------- #
# ROUTAGE DES PAIEMENTS
# --------------------------------------------------------------------------- #
class PaymentRoute(Base):
    """Décide quel prestataire traite quel paiement.

    Exemple :
        CD + CDF + mobile_money -> flexpaie  (priorité 10)
        FR + EUR + card         -> stripe    (priorité 10)   [à intégrer]
        *  + *   + *            -> mock      (priorité 999)  [filet de secours]
    """

    __tablename__ = "payment_routes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # NULL = règle par défaut de la plateforme ; sinon règle propre à une organisation.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    payment_method: Mapped[PaymentMethod | None] = mapped_column(
        EnumText(PaymentMethod), nullable=True
    )
    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at, updated_at = _timestamps()


# --------------------------------------------------------------------------- #
# COMPTES MARCHANDS
# --------------------------------------------------------------------------- #
class MerchantAccount(Base):
    """Le compte marchand d'une organisation chez un prestataire.

    ⚠️ C'est cette table qui répond à la question juridique centrale :
    l'argent va-t-il directement à l'église (`direct_to_organization`) ou
    chez HAPHAK (`platform_account`) ? Voir docs/01-plan-integration-flexpaie.md.
    """

    __tablename__ = "merchant_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider_code", name="uq_merchant_org_provider"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    merchant_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    settlement_mode: Mapped[SettlementMode] = mapped_column(
        EnumText(SettlementMode), nullable=False, default=SettlementMode.UNCONFIRMED
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_kyc")
    currencies: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at, updated_at = _timestamps()


# --------------------------------------------------------------------------- #
# REÇUS
# --------------------------------------------------------------------------- #
class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    donation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("donations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    receipt_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    delivered_via: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    created_at, updated_at = _timestamps()


# --------------------------------------------------------------------------- #
# NOTIFICATIONS
# --------------------------------------------------------------------------- #
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    donation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("donations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # email | sms | whatsapp
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    created_at, updated_at = _timestamps()


# --------------------------------------------------------------------------- #
# JOURNAL D'AUDIT
# --------------------------------------------------------------------------- #
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now()
    )

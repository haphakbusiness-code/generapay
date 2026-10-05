"""
Schémas d'API (validation des entrées / format des sorties).

Principe : le monde extérieur ne voit jamais nos objets SQLAlchemy, et ne
manipule jamais d'unités mineures. Il envoie et reçoit des montants "humains"
("10.00") ; la conversion en unités mineures se fait dans `money.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

__all__ = [
    "DonorPayload",
    "DonationCreateRequest",
    "DonationCreateResponse",
    "DonationStatusResponse",
    "PublicOrganizationResponse",
    "HealthResponse",
    "WebhookResponse",
]


class DonorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    is_anonymous: bool = False


class DonationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Chaîne volontairement : "10.00" n'a aucune perte de précision, 10.00 (float) si.
    amount: str = Field(..., examples=["10.00"], description="Montant en unité majeure")
    currency: Literal["USD", "CDF", "EUR"]
    contribution_type: Literal["donation", "tithe", "offering", "campaign"] = "donation"
    payment_method: Literal["mobile_money", "card"] = "mobile_money"
    campaign_id: str | None = None
    message: str | None = Field(default=None, max_length=1000)
    donor: DonorPayload = Field(default_factory=DonorPayload)


class DonationCreateResponse(BaseModel):
    reference: str
    status: str
    amount: str
    currency: str
    contribution_type: str
    provider: str
    payment_method: str
    next_action: str | None = None
    instructions: str | None = None
    redirect_url: str | None = None
    status_url: str
    expires_at: datetime | None = None
    was_duplicate: bool = False


class DonationStatusResponse(BaseModel):
    reference: str
    status: str
    amount: str
    currency: str
    contribution_type: str
    provider: str | None = None
    failure_reason: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class PublicOrganizationResponse(BaseModel):
    name: str
    slug: str
    logo_url: str | None = None
    country_code: str
    default_currency: str
    supported_currencies: list[str]
    payment_methods: list[str]
    support_email: str | None = None
    campaigns: list[dict[str, Any]] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    database: bool


class WebhookResponse(BaseModel):
    outcome: str
    detail: str
    event_id: str | None = None
    transaction_id: str | None = None
    action: str | None = None

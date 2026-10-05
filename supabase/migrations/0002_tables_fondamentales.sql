-- ===========================================================================
-- GeneraPay — Migration 0002 : tables fondamentales
-- ===========================================================================
-- Conventions :
--   * identifiants : uuid, générés par la base ;
--   * argent       : bigint `amount_minor` + char(3) `currency` (ISO 4217).
--                    JAMAIS de numeric/float pour un montant : les unités
--                    mineures entières évitent toute erreur d'arrondi ;
--   * statuts      : text + contrainte CHECK (lisible dans un export, simple
--                    à faire évoluer, contrairement à un ENUM PostgreSQL) ;
--   * tenant       : toute donnée d'organisation porte `organization_id`.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- ORGANISATIONS (le tenant)
-- ---------------------------------------------------------------------------
create table if not exists public.organizations (
    id                uuid primary key default gen_random_uuid(),
    name              text        not null,
    slug              text        not null,
    country_code      char(2)     not null default 'CD',
    default_currency  char(3)     not null default 'USD',
    status            text        not null default 'active'
                      check (status in ('active', 'suspended', 'pending')),
    logo_url          text,
    support_email     text,
    support_phone     text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    constraint uq_organizations_slug unique (slug)
);

comment on table public.organizations is
    'Tenant racine. Toute donnée métier référence une ligne de cette table.';

create index if not exists ix_organizations_status on public.organizations (status);

drop trigger if exists trg_organizations_updated_at on public.organizations;
create trigger trg_organizations_updated_at
    before update on public.organizations
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- MEMBRES : identité (Supabase Auth) ≠ appartenance à une organisation
-- ---------------------------------------------------------------------------
create table if not exists public.organization_members (
    id               uuid primary key default gen_random_uuid(),
    organization_id  uuid not null references public.organizations (id) on delete cascade,
    user_id          uuid not null,          -- auth.users.id (pas de FK : deux systèmes)
    role             text not null default 'viewer'
                     check (role in ('owner', 'admin', 'treasurer', 'viewer')),
    status           text not null default 'active'
                     check (status in ('active', 'invited', 'revoked')),
    email            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint uq_org_member unique (organization_id, user_id)
);

create index if not exists ix_organization_members_user on public.organization_members (user_id);

drop trigger if exists trg_organization_members_updated_at on public.organization_members;
create trigger trg_organization_members_updated_at
    before update on public.organization_members
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- DONATEURS
-- ---------------------------------------------------------------------------
create table if not exists public.donors (
    id               uuid primary key default gen_random_uuid(),
    organization_id  uuid not null references public.organizations (id) on delete cascade,
    full_name        text,
    email            text,
    phone            text,
    country_code     char(2),
    is_anonymous     boolean not null default false,
    notes            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

-- Unicité par organisation ET par canal : les index partiels laissent les
-- donateurs anonymes (email NULL) coexister sans collision.
create unique index if not exists ix_donors_org_email
    on public.donors (organization_id, email) where email is not null;
create index if not exists ix_donors_org_phone
    on public.donors (organization_id, phone) where phone is not null;

drop trigger if exists trg_donors_updated_at on public.donors;
create trigger trg_donors_updated_at
    before update on public.donors
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- CAMPAGNES
-- ---------------------------------------------------------------------------
create table if not exists public.campaigns (
    id                 uuid primary key default gen_random_uuid(),
    organization_id    uuid not null references public.organizations (id) on delete cascade,
    slug               text not null,
    title              text not null,
    description        text,
    goal_amount_minor  bigint check (goal_amount_minor is null or goal_amount_minor >= 0),
    currency           char(3) not null default 'USD',
    status             text not null default 'draft'
                       check (status in ('draft', 'active', 'closed', 'archived')),
    starts_at          timestamptz,
    ends_at            timestamptz,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    constraint uq_campaign_org_slug unique (organization_id, slug)
);

drop trigger if exists trg_campaigns_updated_at on public.campaigns;
create trigger trg_campaigns_updated_at
    before update on public.campaigns
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- DONS
-- ---------------------------------------------------------------------------
create table if not exists public.donations (
    id                 uuid primary key default gen_random_uuid(),
    organization_id    uuid not null references public.organizations (id) on delete cascade,
    reference          text not null,
    donor_id           uuid references public.donors (id) on delete set null,
    campaign_id        uuid references public.campaigns (id) on delete set null,
    contribution_type  text not null default 'donation'
                       check (contribution_type in
                              ('donation', 'tithe', 'offering', 'campaign',
                               'mission', 'construction', 'event', 'other')),
    amount_minor       bigint not null check (amount_minor > 0),
    currency           char(3) not null,
    status             text not null default 'pending'
                       check (status in ('pending', 'success', 'failed', 'expired')),
    message            text,
    is_anonymous       boolean not null default false,
    idempotency_key    text,
    "metadata"         jsonb,
    succeeded_at       timestamptz,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    constraint uq_donations_reference unique (reference)
);

-- Idempotence côté client : deux POST identiques ne créent qu'un seul don.
create unique index if not exists ix_donations_org_idempotency
    on public.donations (organization_id, idempotency_key)
    where idempotency_key is not null;
create index if not exists ix_donations_org_created
    on public.donations (organization_id, created_at desc);
create index if not exists ix_donations_donor on public.donations (donor_id);
create index if not exists ix_donations_campaign on public.donations (campaign_id);

drop trigger if exists trg_donations_updated_at on public.donations;
create trigger trg_donations_updated_at
    before update on public.donations
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- TRANSACTIONS DE PAIEMENT (une tentative chez un prestataire)
-- ---------------------------------------------------------------------------
create table if not exists public.payment_transactions (
    id                       uuid primary key default gen_random_uuid(),
    organization_id          uuid not null references public.organizations (id) on delete cascade,
    donation_id              uuid not null references public.donations (id) on delete cascade,
    provider_code            text not null,
    provider_transaction_id  text,
    payment_method           text not null default 'mobile_money'
                             check (payment_method in
                                    ('mobile_money', 'card', 'bank_transfer')),
    status                   text not null default 'pending'
                             check (status in ('pending', 'success', 'failed', 'expired')),
    amount_minor             bigint not null check (amount_minor > 0),
    currency                 char(3) not null,
    fee_minor                bigint not null default 0 check (fee_minor >= 0),
    provider_status_raw      text,
    failure_code             text,
    failure_reason           text,
    provider_response        jsonb,
    initiated_at             timestamptz,
    completed_at             timestamptz,
    expires_at               timestamptz,
    created_at               timestamptz not null default now(),
    updated_at               timestamptz not null default now()
);

-- Un même identifiant prestataire ne peut pas être enregistré deux fois :
-- c'est le premier verrou contre le double encaissement.
create unique index if not exists ix_pmt_provider_txn
    on public.payment_transactions (provider_code, provider_transaction_id)
    where provider_transaction_id is not null;
create index if not exists ix_pmt_org_status on public.payment_transactions (organization_id, status);
create index if not exists ix_pmt_pending on public.payment_transactions (created_at)
    where status = 'pending';

drop trigger if exists trg_payment_transactions_updated_at on public.payment_transactions;
create trigger trg_payment_transactions_updated_at
    before update on public.payment_transactions
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- ÉVÉNEMENTS WEBHOOK (journal brut + preuve d'idempotence)
-- ---------------------------------------------------------------------------
create table if not exists public.webhook_events (
    id                 uuid primary key default gen_random_uuid(),
    provider_code      text not null,
    provider_event_id  text not null,
    event_type         text,
    signature_valid    boolean not null default false,
    raw_payload        jsonb,
    processed_at       timestamptz,
    processing_error   text,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    constraint uq_webhook_event unique (provider_code, provider_event_id)
);

create index if not exists ix_webhook_events_created on public.webhook_events (created_at desc);
create index if not exists ix_webhook_events_unprocessed on public.webhook_events (created_at)
    where processed_at is null;

drop trigger if exists trg_webhook_events_updated_at on public.webhook_events;
create trigger trg_webhook_events_updated_at
    before update on public.webhook_events
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- GRAND LIVRE (immuable)
-- ---------------------------------------------------------------------------
create table if not exists public.ledger_entries (
    id                      uuid primary key default gen_random_uuid(),
    organization_id         uuid not null references public.organizations (id) on delete cascade,
    donation_id             uuid references public.donations (id) on delete set null,
    payment_transaction_id  uuid references public.payment_transactions (id) on delete set null,
    entry_type              text not null
                            check (entry_type in ('donation', 'provider_fee', 'platform_fee',
                                                  'refund', 'payout')),
    amount_minor            bigint not null,     -- signé : + encaissement, - frais
    currency                char(3) not null,
    description             text,
    created_at              timestamptz not null default now()
);

-- Un webhook rejoué ne peut pas doubler une écriture.
create unique index if not exists uq_ledger_txn_type
    on public.ledger_entries (payment_transaction_id, entry_type)
    where payment_transaction_id is not null;
create index if not exists ix_ledger_org_created
    on public.ledger_entries (organization_id, created_at desc);

-- Pas de `updated_at` : une écriture comptable ne se modifie pas.
-- L'immuabilité est imposée par un trigger dans la migration 0004.

-- ---------------------------------------------------------------------------
-- ROUTAGE DES PAIEMENTS
-- ---------------------------------------------------------------------------
create table if not exists public.payment_routes (
    id               uuid primary key default gen_random_uuid(),
    organization_id  uuid references public.organizations (id) on delete cascade,
    country_code     char(2),
    currency         char(3),
    payment_method   text check (payment_method is null or payment_method in
                                ('mobile_money', 'card', 'bank_transfer')),
    provider_code    text not null,
    priority         integer not null default 100,
    is_active        boolean not null default true,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create index if not exists ix_payment_routes_active on public.payment_routes (is_active);

drop trigger if exists trg_payment_routes_updated_at on public.payment_routes;
create trigger trg_payment_routes_updated_at
    before update on public.payment_routes
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- COMPTES MARCHANDS
-- ---------------------------------------------------------------------------
create table if not exists public.merchant_accounts (
    id               uuid primary key default gen_random_uuid(),
    organization_id  uuid not null references public.organizations (id) on delete cascade,
    provider_code    text not null,
    merchant_ref     text,
    settlement_mode  text not null default 'unconfirmed'
                     check (settlement_mode in ('direct_to_organization',
                                                'platform_account', 'unconfirmed')),
    status           text not null default 'pending_kyc'
                     check (status in ('pending_kyc', 'active', 'suspended', 'rejected')),
    currencies       jsonb,
    notes            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint uq_merchant_org_provider unique (organization_id, provider_code)
);

drop trigger if exists trg_merchant_accounts_updated_at on public.merchant_accounts;
create trigger trg_merchant_accounts_updated_at
    before update on public.merchant_accounts
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- REÇUS
-- ---------------------------------------------------------------------------
create table if not exists public.receipts (
    id                uuid primary key default gen_random_uuid(),
    organization_id   uuid not null references public.organizations (id) on delete cascade,
    donation_id       uuid not null references public.donations (id) on delete cascade,
    receipt_number    text not null,
    amount_minor      bigint not null check (amount_minor > 0),
    currency          char(3) not null,
    issued_at         timestamptz,
    delivered_via     text,
    delivery_status   text not null default 'pending'
                      check (delivery_status in ('pending', 'sent', 'failed', 'not_required')),
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    constraint uq_receipts_number unique (receipt_number),
    constraint uq_receipts_donation unique (donation_id)
);

drop trigger if exists trg_receipts_updated_at on public.receipts;
create trigger trg_receipts_updated_at
    before update on public.receipts
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- NOTIFICATIONS
-- ---------------------------------------------------------------------------
create table if not exists public.notifications (
    id               uuid primary key default gen_random_uuid(),
    organization_id  uuid not null references public.organizations (id) on delete cascade,
    donation_id      uuid references public.donations (id) on delete set null,
    channel          text not null check (channel in ('email', 'sms', 'whatsapp')),
    destination      text not null,
    template         text not null,
    status           text not null default 'queued'
                     check (status in ('queued', 'sent', 'failed', 'skipped')),
    attempts         integer not null default 0,
    last_error       text,
    sent_at          timestamptz,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create index if not exists ix_notifications_queued on public.notifications (created_at)
    where status = 'queued';

drop trigger if exists trg_notifications_updated_at on public.notifications;
create trigger trg_notifications_updated_at
    before update on public.notifications
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- JOURNAL D'AUDIT
-- ---------------------------------------------------------------------------
create table if not exists public.audit_logs (
    id               uuid primary key default gen_random_uuid(),
    organization_id  uuid references public.organizations (id) on delete cascade,
    actor_id         uuid,
    action           text not null,
    entity_type      text,
    entity_id        text,
    payload          jsonb,
    created_at       timestamptz not null default now()
);

create index if not exists ix_audit_logs_org_created
    on public.audit_logs (organization_id, created_at desc);

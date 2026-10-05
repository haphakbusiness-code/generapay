-- ===========================================================================
-- GeneraPay — Migration 0003 : Row Level Security (isolation multi-tenant)
-- ===========================================================================
-- La RLS est le DERNIER rempart : même si une requête applicative oublie son
-- filtre `organization_id`, PostgreSQL refuse de renvoyer les données d'une
-- autre organisation. C'est ce qui permet de dormir la nuit.
--
-- Deux rôles clients sont concernés (fournis par Supabase) :
--   * anon          : le donateur anonyme sur la page de don ;
--   * authenticated : un utilisateur connecté (membre d'une organisation).
--
-- Le backend FastAPI, lui, se connecte avec un rôle technique et applique le
-- filtrage par organisation dans le code. Ne commitez JAMAIS la clé
-- `service_role` ailleurs que dans les secrets du serveur : elle contourne RLS.
--
-- ⚠️ À LIRE AVANT DE FORCER LA RLS
-- La RLS ne s'applique pas au propriétaire des tables. Si votre API se connecte
-- avec le rôle `postgres` (propriétaire), elle contourne RLS. En production :
--   create role generapay_api login password '...';
--   grant usage on schema public to generapay_api;
--   grant select, insert, update on all tables in schema public to generapay_api;
--   alter table public.donations force row level security;   -- etc.
-- puis faites passer le rôle applicatif par `set_config('request.jwt.claims', ...)`.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- Fonctions d'autorisation
-- ---------------------------------------------------------------------------
create or replace function public.org_role(p_organization uuid)
returns text
language sql
stable
security definer
set search_path = public
as $$
    select m.role
    from public.organization_members m
    where m.organization_id = p_organization
      and m.user_id = auth.uid()
      and m.status = 'active'
    limit 1;
$$;

create or replace function public.has_org_role(p_organization uuid, p_roles text[])
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from public.organization_members m
        where m.organization_id = p_organization
          and m.user_id = auth.uid()
          and m.status = 'active'
          and m.role = any (p_roles)
    );
$$;

comment on function public.has_org_role(uuid, text[]) is
    'Vrai si l''utilisateur connecté porte l''un des rôles demandés sur cette organisation.';

-- ---------------------------------------------------------------------------
-- Activation
-- ---------------------------------------------------------------------------
alter table public.organizations        enable row level security;
alter table public.organization_members enable row level security;
alter table public.donors               enable row level security;
alter table public.campaigns            enable row level security;
alter table public.donations            enable row level security;
alter table public.payment_transactions enable row level security;
alter table public.webhook_events       enable row level security;
alter table public.ledger_entries       enable row level security;
alter table public.payment_routes       enable row level security;
alter table public.merchant_accounts    enable row level security;
alter table public.receipts             enable row level security;
alter table public.notifications        enable row level security;
alter table public.audit_logs           enable row level security;

-- ---------------------------------------------------------------------------
-- ORGANISATIONS
-- ---------------------------------------------------------------------------
drop policy if exists organizations_select_member on public.organizations;
create policy organizations_select_member on public.organizations
    for select to authenticated
    using (public.has_org_role(id, array['owner','admin','treasurer','viewer']));

drop policy if exists organizations_write_admin on public.organizations;
create policy organizations_write_admin on public.organizations
    for update to authenticated
    using (public.has_org_role(id, array['owner','admin']))
    with check (public.has_org_role(id, array['owner','admin']));

-- ---------------------------------------------------------------------------
-- MEMBRES
-- ---------------------------------------------------------------------------
drop policy if exists members_select_member on public.organization_members;
create policy members_select_member on public.organization_members
    for select to authenticated
    using (public.has_org_role(organization_id, array['owner','admin','treasurer','viewer']));

-- Seul un owner gère les owners ; un admin gère les autres rôles.
drop policy if exists members_write_owner on public.organization_members;
create policy members_write_owner on public.organization_members
    for all to authenticated
    using (public.has_org_role(organization_id, array['owner']))
    with check (public.has_org_role(organization_id, array['owner']));

-- ---------------------------------------------------------------------------
-- DONATEURS (données personnelles : accès restreint)
-- ---------------------------------------------------------------------------
drop policy if exists donors_select_finance on public.donors;
create policy donors_select_finance on public.donors
    for select to authenticated
    using (public.has_org_role(organization_id, array['owner','admin','treasurer']));

drop policy if exists donors_write_admin on public.donors;
create policy donors_write_admin on public.donors
    for all to authenticated
    using (public.has_org_role(organization_id, array['owner','admin']))
    with check (public.has_org_role(organization_id, array['owner','admin']));

-- ---------------------------------------------------------------------------
-- CAMPAGNES
-- ---------------------------------------------------------------------------
drop policy if exists campaigns_select_member on public.campaigns;
create policy campaigns_select_member on public.campaigns
    for select to authenticated
    using (public.has_org_role(organization_id, array['owner','admin','treasurer','viewer']));

drop policy if exists campaigns_write_admin on public.campaigns;
create policy campaigns_write_admin on public.campaigns
    for all to authenticated
    using (public.has_org_role(organization_id, array['owner','admin']))
    with check (public.has_org_role(organization_id, array['owner','admin']));

-- ---------------------------------------------------------------------------
-- DONS
-- ---------------------------------------------------------------------------
-- Un viewer peut consulter les dons (lecture seule) : c'est de la visibilité,
-- pas de la gestion financière.
drop policy if exists donations_select_member on public.donations;
create policy donations_select_member on public.donations
    for select to authenticated
    using (public.has_org_role(organization_id, array['owner','admin','treasurer','viewer']));

-- Aucune politique d'INSERT pour `authenticated` ni `anon` :
-- un don est toujours créé par le backend (rôle technique), après validation
-- du montant côté serveur. Autoriser l'insertion directe depuis le navigateur
-- permettrait de fabriquer des dons fictifs.

-- ---------------------------------------------------------------------------
-- TRANSACTIONS DE PAIEMENT
-- ---------------------------------------------------------------------------
drop policy if exists pmt_select_finance on public.payment_transactions;
create policy pmt_select_finance on public.payment_transactions
    for select to authenticated
    using (public.has_org_role(organization_id, array['owner','admin','treasurer']));

-- ---------------------------------------------------------------------------
-- GRAND LIVRE : lecture pour la finance, ÉCRITURE INTERDITE à tous
-- ---------------------------------------------------------------------------
drop policy if exists ledger_select_finance on public.ledger_entries;
create policy ledger_select_finance on public.ledger_entries
    for select to authenticated
    using (public.has_org_role(organization_id, array['owner','admin','treasurer']));

-- Aucune politique insert/update/delete : la comptabilité n'est modifiable que
-- par le rôle technique, et uniquement par ajout d'écritures compensatrices.

-- ---------------------------------------------------------------------------
-- ÉVÉNEMENTS WEBHOOK : journal sensible, aucun accès client
-- ---------------------------------------------------------------------------
-- Volontairement AUCUNE politique : même un owner ne lit pas les webhooks bruts
-- depuis le navigateur. Passer par l'API backend si nécessaire.

-- ---------------------------------------------------------------------------
-- ROUTAGE & COMPTES MARCHANDS
-- ---------------------------------------------------------------------------
drop policy if exists routes_select_admin on public.payment_routes;
create policy routes_select_admin on public.payment_routes
    for select to authenticated
    using (
        organization_id is null
        or public.has_org_role(organization_id, array['owner','admin'])
    );

drop policy if exists routes_write_owner on public.payment_routes;
create policy routes_write_owner on public.payment_routes
    for all to authenticated
    using (
        organization_id is not null
        and public.has_org_role(organization_id, array['owner'])
    )
    with check (
        organization_id is not null
        and public.has_org_role(organization_id, array['owner'])
    );

drop policy if exists merchant_select_owner on public.merchant_accounts;
create policy merchant_select_owner on public.merchant_accounts
    for select to authenticated
    using (public.has_org_role(organization_id, array['owner','admin']));

-- ---------------------------------------------------------------------------
-- REÇUS & NOTIFICATIONS
-- ---------------------------------------------------------------------------
drop policy if exists receipts_select_member on public.receipts;
create policy receipts_select_member on public.receipts
    for select to authenticated
    using (public.has_org_role(organization_id, array['owner','admin','treasurer','viewer']));

drop policy if exists notifications_select_admin on public.notifications;
create policy notifications_select_admin on public.notifications
    for select to authenticated
    using (public.has_org_role(organization_id, array['owner','admin']));

-- ---------------------------------------------------------------------------
-- AUDIT : réservé aux propriétaires
-- ---------------------------------------------------------------------------
drop policy if exists audit_select_owner on public.audit_logs;
create policy audit_select_owner on public.audit_logs
    for select to authenticated
    using (
        organization_id is not null
        and public.has_org_role(organization_id, array['owner'])
    );

-- ---------------------------------------------------------------------------
-- Révocations par défaut (défense en profondeur)
-- ---------------------------------------------------------------------------
revoke all on all tables in schema public from public;

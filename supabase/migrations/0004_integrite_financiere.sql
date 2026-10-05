-- ===========================================================================
-- GeneraPay — Migration 0004 : intégrité financière imposée par la base
-- ===========================================================================
-- Ces triggers sont la traduction SQL des règles non négociables de AGENTS.md.
-- Leur intérêt : ils protègent contre TOUT chemin d'écriture, y compris une
-- requête SQL tapée à la main, un script mal écrit, ou un bug applicatif.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. Le grand livre est IMMUBLE (§11)
--    Une correction passe par une écriture compensatrice, jamais par un UPDATE.
-- ---------------------------------------------------------------------------
create or replace function public.reject_ledger_mutation()
returns trigger
language plpgsql
as $$
begin
    raise exception
        'ledger_entries est immuable : % interdit. Utilisez une écriture compensatrice.',
        tg_op;
end;
$$;

drop trigger if exists trg_ledger_no_update on public.ledger_entries;
create trigger trg_ledger_no_update
    before update on public.ledger_entries
    for each row execute function public.reject_ledger_mutation();

drop trigger if exists trg_ledger_no_delete on public.ledger_entries;
create trigger trg_ledger_no_delete
    before delete on public.ledger_entries
    for each row execute function public.reject_ledger_mutation();

-- Double verrou : même un rôle privilégié ne peut pas modifier le livre.
revoke update, delete on public.ledger_entries from public;

-- ---------------------------------------------------------------------------
-- 2. Un paiement SUCCESS ne redevient jamais autre chose (§8)
-- ---------------------------------------------------------------------------
create or replace function public.reject_payment_status_regression()
returns trigger
language plpgsql
as $$
begin
    if old.status = 'success' and new.status <> 'success' then
        raise exception
            'Transition interdite : success -> %. Un succès ne s''annule pas en place.',
            new.status;
    end if;
    return new;
end;
$$;

drop trigger if exists trg_pmt_no_status_regression on public.payment_transactions;
create trigger trg_pmt_no_status_regression
    before update on public.payment_transactions
    for each row execute function public.reject_payment_status_regression();

drop trigger if exists trg_donations_no_status_regression on public.donations;
create trigger trg_donations_no_status_regression
    before update on public.donations
    for each row execute function public.reject_payment_status_regression();

-- ---------------------------------------------------------------------------
-- 3. Le montant et la devise d'un don ne se modifient jamais après création
--    (sinon le rapprochement avec le relevé de l'agrégateur devient impossible)
-- ---------------------------------------------------------------------------
create or replace function public.reject_donation_amount_change()
returns trigger
language plpgsql
as $$
begin
    if new.amount_minor <> old.amount_minor or new.currency <> old.currency then
        raise exception
            'Le montant d''un don est immuable (ancien : % %, nouveau : % %).',
            old.amount_minor, old.currency, new.amount_minor, new.currency;
    end if;
    return new;
end;
$$;

drop trigger if exists trg_donations_amount_immutable on public.donations;
create trigger trg_donations_amount_immutable
    before update on public.donations
    for each row execute function public.reject_donation_amount_change();

-- ---------------------------------------------------------------------------
-- 4. Une écriture comptable doit être dans la devise de son don
-- ---------------------------------------------------------------------------
create or replace function public.check_ledger_currency_matches_donation()
returns trigger
language plpgsql
as $$
declare
    v_currency char(3);
begin
    if new.donation_id is null then
        return new;
    end if;

    select currency into v_currency
    from public.donations
    where id = new.donation_id;

    if v_currency is not null and v_currency <> new.currency then
        raise exception
            'Devise incohérente : écriture en %, don en %.', new.currency, v_currency;
    end if;

    return new;
end;
$$;

drop trigger if exists trg_ledger_currency_check on public.ledger_entries;
create trigger trg_ledger_currency_check
    before insert on public.ledger_entries
    for each row execute function public.check_ledger_currency_matches_donation();

-- ---------------------------------------------------------------------------
-- 5. Vue de rapprochement : total des dons vs total du grand livre
--    Un écart non nul signale un bug à investiguer immédiatement.
-- ---------------------------------------------------------------------------
create or replace view public.v_reconciliation_par_devise as
select
    d.organization_id,
    d.currency,
    count(distinct d.id)                                        filter (where d.status = 'success') as dons_reussis,
    coalesce(sum(d.amount_minor) filter (where d.status = 'success'), 0) as dons_bruts,
    coalesce(sum(l.amount_minor) filter (where l.entry_type = 'donation'), 0) as livre_bruts,
    coalesce(sum(l.amount_minor) filter (where l.entry_type in ('provider_fee','platform_fee')), 0) as frais,
    coalesce(sum(l.amount_minor), 0)                            as net_organisation
from public.donations d
left join public.ledger_entries l on l.donation_id = d.id
group by d.organization_id, d.currency;

comment on view public.v_reconciliation_par_devise is
    'Contrôle quotidien : dons_bruts doit être égal à livre_bruts.';

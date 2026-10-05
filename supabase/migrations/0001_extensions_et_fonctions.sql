-- ===========================================================================
-- GeneraPay — Migration 0001 : extensions et fonctions utilitaires
-- ===========================================================================
-- Cible : PostgreSQL (Supabase).
-- Ces fichiers sont la SOURCE DE VÉRITÉ du schéma de production.
-- Ne modifiez jamais le schéma à la main : ajoutez une migration.
--
-- Chaque migration est idempotente (`if not exists`) afin de pouvoir être
-- rejouée sans casse lors d'un déploiement.
-- ===========================================================================

create extension if not exists pgcrypto;   -- gen_random_uuid()
create extension if not exists pg_trgm;    -- recherche floue sur les noms de donateurs

-- ---------------------------------------------------------------------------
-- Horodatage `updated_at` automatique.
-- Le faire en base (et pas seulement dans l'ORM) garantit qu'aucun chemin
-- d'écriture ne peut oublier de mettre à jour la date.
-- ---------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

comment on function public.set_updated_at() is
    'Maintient updated_at à jour, quel que soit le chemin d''écriture.';

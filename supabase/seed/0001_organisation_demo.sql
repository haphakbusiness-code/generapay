-- ===========================================================================
-- GeneraPay — Jeu de données de démonstration
-- ===========================================================================
-- ⚠️ À exécuter UNIQUEMENT sur un projet Supabase de développement.
-- En production, les organisations s'inscrivent via l'application.
-- ===========================================================================

-- Organisation pilote -----------------------------------------------------------------
insert into public.organizations (id, name, slug, country_code, default_currency, status,
                                  support_email, support_phone)
values (
    '11111111-1111-1111-1111-111111111111',
    'Église Pilote GeneraPay',
    'eglise-pilote',
    'CD',
    'USD',
    'active',
    'tresorier@eglise-pilote.example',
    '+243000000000'
)
on conflict (slug) do nothing;

-- Routes de paiement par défaut (tout vers le mock tant que FlexPaie n'est pas actif) --
insert into public.payment_routes (organization_id, country_code, currency, payment_method,
                                   provider_code, priority, is_active)
values
    (null, 'CD', 'CDF', 'mobile_money', 'mock', 10, true),
    (null, 'CD', 'USD', 'mobile_money', 'mock', 10, true),
    (null, 'CD', 'USD', 'card',         'mock', 10, true),
    (null, 'CD', 'EUR', 'card',         'mock', 20, true),
    (null, null, null,  null,           'mock', 999, true)
on conflict do nothing;

-- Compte marchand FlexPaie : statut réel à ce jour ------------------------------------
insert into public.merchant_accounts (organization_id, provider_code, merchant_ref,
                                      settlement_mode, status, currencies, notes)
values (
    '11111111-1111-1111-1111-111111111111',
    'flexpaie',
    null,
    'unconfirmed',
    'pending_kyc',
    '["USD","CDF"]'::jsonb,
    'Dossier à déposer sur www.flexpaie.com (RCCM, IDNAT, NIF, pièce d''identité). '
    'Question bloquante : le règlement va-t-il directement sur le compte de l''organisation ?'
)
on conflict (organization_id, provider_code) do nothing;

-- Campagne d'exemple -------------------------------------------------------------------
insert into public.campaigns (organization_id, slug, title, description,
                              goal_amount_minor, currency, status)
values (
    '11111111-1111-1111-1111-111111111111',
    'construction-temple',
    'Construction du temple',
    'Campagne de collecte pour la construction du nouveau temple.',
    5000000,   -- 50 000.00 USD
    'USD',
    'active'
)
on conflict (organization_id, slug) do nothing;

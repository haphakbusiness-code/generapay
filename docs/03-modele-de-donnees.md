# Modèle de données

13 tables, toutes versionnées dans `supabase/migrations/`. Le modèle ORM
(`api/app/models.py`) est **vérifié automatiquement** contre ces migrations
par `tests/api/test_migrations_et_modeles.py` : une colonne ajoutée dans le
code sans migration fait échouer les tests.

---

## Vue d'ensemble

```
organizations ─┬─> organization_members      (qui a quel rôle)
               ├─> donors                    (fichier donateur)
               ├─> campaigns                 (collectes fléchées)
               ├─> donations ─┬─> payment_transactions ─┬─> ledger_entries
               │              │                         └─> webhook_events
               │              └─> receipts
               ├─> merchant_accounts         (compte marchand par agrégateur)
               ├─> payment_routes            (quel agrégateur pour quoi)
               ├─> notifications
               └─> audit_logs
```

---

## Les tables, une par une

### `organizations` — le tenant
La racine. `slug` sert d'URL publique (`/eglise-pilote`). `status` permet de
suspendre une organisation sans supprimer ses données.

### `organization_members` — identité ≠ appartenance
`user_id` pointe vers `auth.users` (Supabase) **sans clé étrangère** : deux
systèmes distincts. Un même utilisateur peut appartenir à plusieurs
organisations avec des rôles différents — c'est le cas d'un trésorier qui
officie dans deux paroisses. Unicité sur `(organization_id, user_id)`.

### `donors` — le fichier donateur
Recherche par e-mail, puis par téléphone, **toujours bornée par
`organization_id`**. Index unique partiel : les donateurs anonymes (e-mail
`NULL`) coexistent sans collision. `is_anonymous` permet le don anonyme, exigé
par AGENTS.md §27.

### `campaigns` — collectes fléchées
`goal_amount_minor` + `currency`, statut `draft/active/closed/archived`.
Une campagne fermée reste consultable : l'historique ne disparaît pas.

### `donations` — l'intention du donateur
Le cœur du modèle. Points importants :

* `reference` (`GP-RVA5FN`) : lisible au téléphone par un donateur, contrairement
  à un UUID. Alphabet sans `0/O/1/I` pour éviter les confusions.
* `amount_minor` + `currency` : jamais de float, jamais de conversion.
* `idempotency_key` : index unique **partiel** — deux POST identiques ne créent
  qu'un don, mais un don sans clé reste possible.
* `metadata` (JSONB) : contexte de debugging (IP, source). À ne jamais utiliser
  pour des données métier.
* Un don peut avoir **plusieurs** `payment_transactions` (échec puis réessai).

### `payment_transactions` — une tentative chez un agrégateur
Séparée du don, parce que la vie d'un paiement est plus agitée que celle d'un
don. Conserve `provider_status_raw` (le statut brut de l'agrégateur),
`failure_code`, `failure_reason`, `provider_response` (JSONB), et
`expires_at` utilisé par la réconciliation.

Index unique partiel sur `(provider_code, provider_transaction_id)` : **premier
verrou** contre le double encaissement.

### `webhook_events` — le journal brut
Le corps du webhook est conservé **intégralement**. Trois raisons :
prouver l'idempotence, diagnostiquer un litige avec l'agrégateur, rejouer un
événement après correction d'un bug.

Un webhook non authentifié est aussi journalisé, avec un identifiant dérivé de
l'empreinte SHA-256 du corps : déterministe, donc une attaque par inondation ne
remplit pas la table.

### `ledger_entries` — le grand livre (immuable)
`amount_minor` **signé** : positif pour ce qui entre dans la caisse de
l'organisation, négatif pour les frais et remboursements. Aucune colonne
`updated_at` : une écriture ne se modifie pas. Pas de politique RLS
d'écriture : seule l'API technique peut en créer.

### `payment_routes` — le routage
`organization_id` nul = règle plateforme ; renseigné = règle propre à une
organisation. `country_code`, `currency`, `payment_method` nuls = joker.
Changer d'agrégateur = modifier une ligne, pas redéployer.

### `merchant_accounts` — la question juridique matérialisée
`settlement_mode` dit explicitement où va l'argent :
`direct_to_organization` / `platform_account` / `unconfirmed`.
`status` suit le dossier KYC (`pending_kyc` → `active`).
C'est la table à regarder pour savoir si une organisation peut réellement
encaisser.

### `receipts` — les reçus
Unicité sur `donation_id` : un don = un reçu. `delivery_status` trace l'envoi
(e-mail, puis SMS/WhatsApp).

### `notifications` — file d'envoi
`status`, `attempts`, `last_error` : un envoi échoué se voit et se rejoue, il
ne disparaît pas silencieusement.

### `audit_logs` — qui a fait quoi
`actor_id`, `action`, `entity_type`, `entity_id`, `payload` JSONB. Indispensable
le jour où un trésorier signale une modification qu'il n'a pas faite.

---

## Les contraintes qui protègent l'argent

| Contrainte | Effet |
|---|---|
| `check (amount_minor > 0)` sur `donations` | Un don nul ou négatif est impossible |
| `check (fee_minor >= 0)` | Une commission négative est impossible |
| Trigger `trg_ledger_no_update` / `no_delete` | Le grand livre est immuable, même en SQL direct |
| Trigger `trg_pmt_no_status_regression` | `success` → autre chose : refusé par la base |
| Trigger `trg_donations_amount_immutable` | Le montant d'un don ne change jamais |
| Trigger `trg_ledger_currency_check` | Une écriture doit être dans la devise du don |
| Index unique `(provider_code, provider_transaction_id)` | Pas de doublon de transaction |
| Index unique `(payment_transaction_id, entry_type)` | Pas de doublon d'écriture comptable |
| Index unique `(organization_id, idempotency_key)` | Pas de doublon de don |

Ces garde-fous sont **volontairement redondants** avec la logique applicative.
La logique Python est la première ligne ; la base est la dernière. Elles
doivent dire la même chose, et si un jour elles divergent, c'est la base qui
gagne — et un test échoue.

---

## La vue de rapprochement

```sql
select * from public.v_reconciliation_par_devise;

 organization_id | currency | dons_reussis | dons_bruts | livre_bruts | frais | net_organisation
```

`dons_bruts` doit **toujours** être égal à `livre_bruts`. Un écart signifie
qu'un paiement a été marqué réussi sans écriture comptable : à investiguer
immédiatement. À consulter chaque jour pendant le pilote.

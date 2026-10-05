# Guide développeur

## 1. Installer et lancer

```bash
cd generapay

# Environnement Python isolé
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.txt

# Configuration (optionnel : les valeurs par défaut fonctionnent en local)
cp .env.example .env

# Démarrer l'API
.venv/bin/python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000
```

Ouvrez ensuite :

* `http://localhost:8000/docs` — l'API entière, documentée et testable
* `http://localhost:8000/health` — la sonde de vie

Au démarrage en mode développement, l'API crée les tables SQLite et sème
l'organisation de démonstration `eglise-pilote` avec ses routes de paiement.

## 2. Tester

```bash
.venv/bin/python -m pytest              # tout (88 tests)
.venv/bin/python -m pytest -k webhook   # un sous-ensemble
.venv/bin/python -m pytest -x           # s'arrêter au premier échec
```

Aucun serveur PostgreSQL n'est nécessaire : les tests tournent sur SQLite.
Ce qui est testé, c'est la logique financière — elle est identique sur les
deux moteurs. La RLS, elle, est propre à PostgreSQL et se vérifie sur un
projet Supabase de développement.

### Ce que les tests couvrent

| Fichier | Ce qui est protégé |
|---|---|
| `test_money.py` | unités mineures, ISO 4217, refus des float, CDF |
| `test_ledger_et_frais.py` | calcul des 2,5 %, arrondi, plan comptable |
| `test_machine_a_etats.py` | transitions autorisées et interdites |
| `test_flux_paiement_complet.py` | le parcours complet, en HTTP réel |
| `test_routage_paiement.py` | choix de l'agrégateur, capacités réelles |
| `test_reconciliation.py` | récupération, expiration, idempotence du job |
| `test_adaptateur_flexpaie.py` | fail-closed, statuts, configuration |
| `test_migrations_et_modeles.py` | non-divergence ORM ↔ SQL |

## 3. Manipuler le système à la main

Les endpoints de bac à sable (désactivables via
`GENERAPAY_ALLOW_TESTING_ENDPOINTS=false`) permettent de rejouer un parcours
complet sans agrégateur réel.

```bash
B=http://localhost:8000

# 1. Créer un don
curl -s -X POST $B/api/v1/public/organizations/eglise-pilote/donations \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: essai-1' \
  -d '{"amount":"10.00","currency":"USD","contribution_type":"tithe",
       "payment_method":"mobile_money","donor":{"phone":"+243810000000"}}'
# -> {"reference":"GP-RVA5FN","status":"pending", ...}

# 2. Simuler la confirmation du donateur (webhook signé, chemin réel)
curl -s -X POST $B/api/v1/testing/mock/transactions/MOCK-GP-RVA5FN/outcome \
  -H 'Content-Type: application/json' \
  -d '{"outcome":"success","fee_minor":25}'
# -> {"webhook_outcome":"processed","action":"succeeded","ledger_entries_created":2}

# 3. Vérifier l'état vu par le donateur
curl -s $B/api/v1/public/donations/GP-RVA5FN

# 4. Lancer une réconciliation
curl -s -X POST $B/api/v1/testing/reconcile
```

Pour simuler un **montant falsifié** (et voir le contrôle fonctionner) :

```bash
curl -s -X POST $B/api/v1/testing/mock/transactions/MOCK-GP-XXXXXX/outcome \
  -H 'Content-Type: application/json' \
  -d '{"outcome":"success","amount_minor":1000000}'
# -> {"action":"amount_mismatch"}  et aucune écriture comptable
```

## 4. Étendre le système

### Ajouter un agrégateur

1. Créer `api/app/payments/mon_agregateur.py` en implémentant les 4 méthodes
   de `PaymentProvider` (`initiate`, `fetch_transaction`, `verify_webhook`,
   `parse_webhook`).
2. Déclarer ses capacités **réelles** dans `capabilities` — pays, devises,
   moyens de paiement confirmés par contrat, pas supposés.
3. L'enregistrer dans `build_default_registry()` (`payments/router.py`).
4. Ajouter une ligne dans `payment_routes`.
5. Écrire les tests : signature invalide refusée, statut inconnu → `pending`,
   doublon de webhook sans effet.

Règle : **fail-closed**. Si vous ne savez pas authentifier un webhook, refusez-le.

### Ajouter une devise

1. Une ligne dans `SUPPORTED_CURRENCIES` (`api/app/money.py`) avec
   `exponent` (ISO 4217) et `display_decimals` (affichage réel).
2. L'ajouter au `Literal[...]` du schéma `DonationCreateRequest`.
3. Ajouter la route de paiement correspondante.

C'est tout : le reste du code est agnostique.

### Ajouter un type de contribution

La colonne est du texte : ajoutez la valeur à la contrainte `check` dans une
nouvelle migration, et à `ContributionType`. Aucune restructuration.

### Ajouter une migration

```
supabase/migrations/0005_<description>.sql
```

* Toujours idempotente (`if not exists`, `drop trigger if exists`).
* Jamais de modification manuelle du schéma de production.
* Ajouter les colonnes correspondantes dans `api/app/models.py`, sinon
  `test_migrations_et_modeles.py` échoue.

## 5. Conventions de code

* **Argent** : uniquement via `money.py`. Un `float` dans un chemin financier
  est un bug, pas un style.
* **Statuts** : passer par les `StrEnum` de `domain/enums.py`, jamais par des
  chaînes en dur.
* **Commentaires** : ils expliquent le *pourquoi*, pas le *comment*. Un
  commentaire utile raconte le piège évité.
* **Erreurs** : lever des exceptions métier explicites ; la couche HTTP les
  traduit en codes de réponse.
* **Secrets** : variables d'environnement uniquement. Jamais dans le code,
  jamais dans le frontend.

## 6. Dépannage

| Symptôme | Cause probable |
|---|---|
| `422 — Aucune route de paiement` | Aucune ligne `payment_routes` ne couvre ce pays/devise/méthode |
| `502 — FlexPaie n'est pas configuré` | Normal tant que les accès sandbox ne sont pas renseignés |
| Webhook `rejected` | Signature invalide ou absente — vérifier le secret |
| Webhook `ignored` (transaction inconnue) | La référence ne correspond à aucune transaction : webhook orphelin ou mauvaise référence |
| Don bloqué en `pending` | Le webhook n'est pas arrivé : lancer `/api/v1/testing/reconcile` |
| `already_final` | Événement tardif ignoré — comportement **normal** et souhaité |

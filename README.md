# HAPHAK GeneraPay

**Plateforme multi-organisations de collecte de dons et d'offrandes**

GeneraPay permet aux églises, ministères, ONG et organisations communautaires de
collecter, suivre, réconcilier et rapporter leurs contributions numériques —
dans plusieurs pays, plusieurs devises (USD, CDF, EUR) et plusieurs moyens de
paiement (Mobile Money, cartes).

> **GeneraPay ne déplace pas d'argent.** L'argent va du donateur à
> l'organisation via un agrégateur agréé (FlexPaie en RDC). GeneraPay est la
> couche logicielle : la page de don, la preuve, la comptabilité, les reçus,
> les tableaux de bord.

---

## 📚 Par où commencer

| Document | Contenu |
|---|---|
| [`docs/00-lisez-moi-dabord.md`](docs/00-lisez-moi-dabord.md) | La vue d'ensemble, les 4 règles qui protègent l'argent, le parcours d'un don |
| [`docs/01-plan-integration-flexpaie.md`](docs/01-plan-integration-flexpaie.md) | Analyse de la réponse FlexPaie, les 14 questions à leur poser, le calendrier |
| [`docs/02-architecture-et-flux.md`](docs/02-architecture-et-flux.md) | Couches, routage, webhooks, idempotence, grand livre, isolation |
| [`docs/03-modele-de-donnees.md`](docs/03-modele-de-donnees.md) | Les 13 tables et leur raison d'être |
| [`docs/04-guide-developpeur.md`](docs/04-guide-developpeur.md) | Installer, tester, étendre, dépanner |
| [`docs/05-conformite-et-risques.md`](docs/05-conformite-et-risques.md) | Juridique, sécurité, les 10 pièges coûteux |
| [`docs/06-feuille-de-route.md`](docs/06-feuille-de-route.md) | Les 9 étapes, avec critères d'achèvement |
| [`AGENTS.md`](AGENTS.md) | Les règles non négociables du projet |

---

## 🚀 Démarrage rapide

```bash
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.txt
.venv/bin/python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000
```

Puis ouvrez **http://localhost:8000/docs** — l'API entière est documentée et
testable depuis le navigateur. Une organisation de démonstration
(`eglise-pilote`) est créée automatiquement.

```bash
.venv/bin/python -m pytest          # 88 tests, aucune base externe requise
```

### Un don complet en trois commandes

```bash
B=http://localhost:8000

# 1. Le donateur crée son don
curl -s -X POST $B/api/v1/public/organizations/eglise-pilote/donations \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: essai-1' \
  -d '{"amount":"10.00","currency":"USD","contribution_type":"tithe",
       "payment_method":"mobile_money","donor":{"phone":"+243810000000"}}'
# -> {"reference":"GP-RVA5FN","status":"pending", ...}

# 2. Le donateur confirme sur son téléphone (webhook signé, chemin de production)
curl -s -X POST $B/api/v1/testing/mock/transactions/MOCK-GP-RVA5FN/outcome \
  -H 'Content-Type: application/json' -d '{"outcome":"success","fee_minor":25}'
# -> {"action":"succeeded","ledger_entries_created":2}

# 3. Le donateur consulte l'état de son don
curl -s $B/api/v1/public/donations/GP-RVA5FN
# -> {"status":"success", ...}
```

---

## 🏗️ État du projet

| # | Étape | État |
|---|---|---|
| 1 | Fondations : dépôt, configuration, sonde de vie | ✅ |
| 2 | Base de données : 4 migrations, 13 tables, RLS, triggers d'intégrité | ✅ |
| 3 | Moteur de paiement : abstraction, mock, webhooks, idempotence, grand livre, réconciliation | ✅ |
| 4 | Authentification Supabase + rôles | ⬜ |
| 5 | Page publique de don (Next.js) | ⬜ |
| 6 | Tableau de bord organisation | ⬜ |
| 7 | Reçus (e-mail, puis SMS/WhatsApp) | ⬜ |
| 8 | FlexPaie réel (sandbox → production) | ⬜ bloqué sur leur documentation |
| 9 | Pilote avec 1 à 3 organisations | ⬜ |

---

## 📁 Structure

```
generapay/
├── api/                    Backend FastAPI (Python)
│   └── app/
│       ├── money.py        Unités mineures + ISO 4217 (jamais de float)
│       ├── models.py       Les 13 tables
│       ├── domain/         Machine à états, plan comptable, énumérations
│       ├── payments/       Abstraction, MockProvider, FlexpaieProvider, routeur
│       ├── services/       Dons, webhooks, cœur financier, réconciliation
│       └── api/            Endpoints HTTP
├── web/                    Frontend Next.js (à venir — étape 5)
├── supabase/
│   ├── migrations/         Source de vérité du schéma PostgreSQL
│   └── seed/               Données de démonstration
├── tests/api/              88 tests automatisés
└── docs/                   Documentation
```

---

## 🔒 Les quatre règles non négociables

1. **Jamais de `float` pour l'argent** — unités mineures entières + devise ISO 4217.
2. **On ne croit jamais le navigateur** — un paiement n'est confirmé qu'après
   vérification serveur auprès de l'agrégateur.
3. **Un état final ne se corrige pas** — `success`, `failed`, `expired` sont terminaux.
4. **Le grand livre est immuable** — une correction passe par une écriture
   compensatrice, imposée par trigger PostgreSQL.

Le détail, avec les raisons : [`docs/00-lisez-moi-dabord.md`](docs/00-lisez-moi-dabord.md).

---

## 🧭 Principes

Sécurité · Intégrité des données · Simplicité · Scalabilité · Testabilité ·
Indépendance vis-à-vis des prestataires · Mobile-first · Responsabilité
financière.

## Propriété

**HAPHAK** — HAPHAK GeneraPay est un produit technologique HAPHAK.

---

**Conçu pour les organisations. Pensé pour le don à l'échelle mondiale.**

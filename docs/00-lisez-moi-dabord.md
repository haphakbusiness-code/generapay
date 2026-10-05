# GeneraPay — Lisez-moi d'abord

> Ce document s'adresse à vous : un développeur qui connaît le code, mais pas
> encore les systèmes de paiement. Il explique **pourquoi** le système est
> construit comme il l'est, avant d'expliquer comment il fonctionne.
>
> Lecture conseillée dans l'ordre :
> 1. `00-lisez-moi-dabord.md` (ce fichier) — la vue d'ensemble
> 2. `01-plan-integration-flexpaie.md` — ce que l'agrégateur a confirmé, et ce qui bloque
> 3. `02-architecture-et-flux.md` — comment circule l'information
> 4. `03-modele-de-donnees.md` — les tables et leur raison d'être
> 5. `04-guide-developpeur.md` — lancer, tester, étendre
> 6. `05-conformite-et-risques.md` — le juridique, les pièges coûteux
> 7. `06-feuille-de-route.md` — les étapes restantes, dans l'ordre

---

## 1. Ce que vous construisez réellement

Ce n'est **pas** une application de paiement. C'est un **système comptable
multi-organisations** qui se trouve être déclenché par des paiements.

La différence change tout :

| Une app de paiement | Un système comptable de dons |
|---|---|
| « Le paiement a réussi » | « Combien l'église a-t-elle réellement reçu, en quelle devise, et peux-je le prouver ? » |
| Un bug = un utilisateur mécontent | Un bug = un écart entre le relevé bancaire et la comptabilité |
| On peut rejouer une opération | On ne peut jamais « corriger » l'histoire financière |

C'est pour cela que ce dépôt contient autant de garde-fous apparemment
disproportionnés pour un MVP. Ils ne le sont pas : ce sont précisément eux qui
éviteront la première crise de confiance avec une église.

### Les trois acteurs

```
   L'ORGANISATION            GENERAPAY                    L'AGRÉGATEUR
   (église, ONG…)        (ce que vous construisez)         (FlexPaie, puis d'autres)
   ────────────────      ─────────────────────────       ──────────────────────────
   reçoit l'argent   <--  enregistre, prouve, rapporte  -->  déplace réellement l'argent
```

Point essentiel, à ne jamais oublier : **GeneraPay ne déplace pas d'argent**.
L'argent va du téléphone du donateur vers le compte de l'organisation, via
l'agrégateur. GeneraPay est la couche logicielle : la page de don, la preuve,
la comptabilité, les reçus, les tableaux de bord.

C'est aussi ce qui vous protège juridiquement : dès l'instant où l'argent
transite par un compte HAPHAK, vous devenez de fait un établissement de monnaie
électronique, avec les obligations qui vont avec (voir `05-conformite-et-risques.md`).

---

## 2. Pourquoi « multi-tenant » dès le premier jour

Vous avez demandé que d'autres églises puissent utiliser la plateforme. Cela
impose une décision d'architecture **avant** la première ligne de code, pas après.

Chaque donnée appartient à une organisation, et porte donc `organization_id` :

```
donations ──┐
donors ─────┼──> organization_id ──> organizations
campaigns ──┘
```

Une plateforme construite pour une seule église, puis « ouverte » aux autres,
exige de réécrire toutes les requêtes, tous les écrans, tous les exports — et
de prier pour n'avoir rien oublié. L'oubli typique, c'est la page
« liste des donateurs » qui affiche les donateurs de toutes les églises.

Ici, l'isolation est appliquée à **trois niveaux** :

1. **Dans le code** : chaque requête est bornée par `organization_id` ;
2. **Dans la base** : la Row Level Security PostgreSQL refuse la donnée d'une
   autre organisation même si le code se trompe
   (`supabase/migrations/0003_row_level_security.sql`) ;
3. **Dans les rôles** : `owner`, `admin`, `treasurer`, `viewer` — un `viewer`
   voit les totaux, il ne gère pas la trésorerie.

---

## 3. Les quatre règles qui protègent l'argent

Tout le reste du code découle de ces quatre règles.

### Règle 1 — Jamais de `float` pour l'argent

```python
>>> 0.1 + 0.2
0.30000000000000004
```

Sur un don, cette imprécision se reporte dans le grand livre et finit par
produire un écart de rapprochement impossible à expliquer.

La solution : on stocke des **unités mineures entières**.

```
10.00 USD  ->  amount_minor = 1000,  currency = "USD"
5000   CDF ->  amount_minor = 500000, currency = "CDF"   (ISO 4217 : 2 décimales)
```

`api/app/money.py` est la seule porte d'entrée. Il refuse un `float`, refuse
une devise inconnue, refuse un montant négatif, et refuse une précision que la
devise ne peut pas représenter (`10.005` USD).

> ⚠️ **Le piège CDF.** L'ISO 4217 donne 2 décimales au franc congolais, donc
> 5 000 FC = 500 000 unités mineures en base. Mais à l'**affichage**, on écrit
> `5000 FC`, jamais `5000,00 FC`. Le module sépare donc `exponent` (stockage)
> de `display_decimals` (affichage).
>
> Et surtout : **il faudra demander à FlexPaie dans quelle unité leur API
> attend le montant** (francs entiers ou centimes). Si l'on envoie 500 000 là
> où ils attendent 5 000, le donateur est débité 100 fois trop. C'est la
> question la plus urgente de l'intégration.

### Règle 2 — On ne croit jamais le navigateur

Le seul endroit où un paiement devient « réussi », c'est après avoir
**re-interrogé l'API de l'agrégateur** depuis le serveur.

Un attaquant qui devine l'URL de votre webhook peut y envoyer
`{"status":"success","amount":1000000}`. Si vous le croyez, vous venez de
créditer un don d'un million. C'est pourquoi :

* le webhook doit être **signé** (HMAC vérifié côté serveur) ;
* même signé, on **ré-interroge** l'agrégateur (`fetch_transaction`) ;
* si le montant réel ≠ montant attendu → échec, aucune écriture comptable.

### Règle 3 — Un état final ne se corrige pas

```
PENDING ──> SUCCESS ──> écritures au grand livre + reçu
   ├──> FAILED
   └──> EXPIRED
```

`SUCCESS`, `FAILED`, `EXPIRED` sont **terminaux**. Un webhook « failed » qui
arrive deux minutes après le succès est ignoré, pas appliqué. Sans cette
machine à états, c'est le dernier webhook reçu qui gagne — et un agrégateur
renvoie très souvent ses webhooks en double et dans le désordre.

### Règle 4 — Le grand livre est immuable

Une écriture comptable ne se modifie jamais, ne se supprime jamais. Une
erreur se corrige par une **écriture compensatrice** (comme en comptabilité
réelle). C'est imposé par un trigger PostgreSQL : même un `UPDATE` tapé à la
main en base échoue.

---

## 4. Le parcours d'un don, en vrai

Voici exactement ce qui se passe quand un fidèle donne 10 USD par M-Pesa.
Ce parcours est **entièrement testé** (`tests/api/test_flux_paiement_complet.py`).

```
 1. Le donateur ouvre            GET  /api/v1/public/organizations/eglise-pilote
    la page de don                   -> nom, logo, devises acceptées, campagnes

 2. Il choisit 10 USD,           POST /api/v1/public/organizations/eglise-pilote/donations
    dîme, M-Pesa,                    en-tête : Idempotency-Key: <clé du navigateur>
    et valide                        -> donation PENDING + payment_transaction PENDING
                                     -> référence GP-RVA5FN, échéance +15 min

 3. Le routeur a choisi          payment_routes : CD + USD + mobile_money -> flexpaie
    l'agrégateur                  (aujourd'hui : mock, car FlexPaie n'est pas actif)

 4. L'agrégateur envoie le       Le donateur reçoit l'invite USSD sur son téléphone
    prompt au donateur            et compose son code PIN

 5. L'agrégateur notifie         POST /api/v1/payments/webhooks/flexpaie
    GeneraPay (webhook)            1. signature vérifiée     -> sinon REFUS (400)
                                   2. événement journalisé   -> webhook_events
                                   3. déjà traité ?          -> réponse "duplicate", stop
                                   4. transaction retrouvée
                                   5. on RE-INTERROGE l'agrégateur
                                   6. montant vérifié
                                   7. machine à états : pending -> success
                                   8. écritures au grand livre (atomique)

 6. La page du donateur          GET  /api/v1/public/donations/GP-RVA5FN
    affiche "Merci"                  -> status: success

 7. (étape 7 du plan)            Reçu envoyé par e-mail / SMS
```

Et si le webhook n'arrive jamais ? C'est le rôle de la **réconciliation** :
un job périodique reprend tous les paiements `PENDING`, redemande leur état à
l'agrégateur, et expire ceux dont le délai est dépassé. Aucun paiement ne reste
bloqué indéfiniment.

---

## 5. Ce qui existe déjà dans ce dépôt

```
generapay/
├── api/                          Backend FastAPI (Python)
│   └── app/
│       ├── money.py              Règles monétaires (unités mineures, ISO 4217)
│       ├── models.py             13 tables (ORM SQLAlchemy)
│       ├── db_types.py           Types compatibles PostgreSQL + SQLite
│       ├── config.py             Configuration par variables d'environnement
│       ├── domain/
│       │   ├── enums.py          Statuts, rôles, types d'écriture
│       │   ├── state_machine.py  Transitions autorisées
│       │   └── ledger.py         Plan comptable d'un don réussi, calcul des frais
│       ├── payments/
│       │   ├── base.py           Le contrat « PaymentProvider »
│       │   ├── mock.py           Agrégateur fictif mais signé (démo + tests)
│       │   ├── flexpaie.py       Adaptateur FlexPaie (ébauche, fail-closed)
│       │   └── router.py         Choix du prestataire (pays/devise/méthode)
│       ├── services/
│       │   ├── donations.py      Créer un don + lancer l'encaissement
│       │   ├── webhooks.py       Traiter un webhook (idempotent)
│       │   ├── transaction_flow.py  LE cœur financier
│       │   └── reconciliation.py Rattraper les paiements en attente
│       ├── api/                  Les endpoints HTTP
│       └── main.py               Assemblage
│
├── supabase/
│   ├── migrations/               4 migrations SQL (source de vérité PostgreSQL)
│   └── seed/                     Données de démonstration
│
├── tests/api/                    88 tests automatisés
└── docs/                         Ces documents
```

### L'essayer en 3 minutes

```bash
cd generapay
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.txt
.venv/bin/python -m uvicorn app.main:app --app-dir api --host 0.0.0.0 --port 8000
```

Puis ouvrez `http://localhost:8000/docs` : toute l'API est documentée et
testable depuis le navigateur. L'organisation de démonstration
(`eglise-pilote`) et les routes de paiement sont créées automatiquement au
démarrage.

### Lancer les tests

```bash
.venv/bin/python -m pytest          # 88 tests, aucune base externe requise
```

---

## 6. Ce qu'il reste à faire

Résumé brut ; le détail est dans `06-feuille-de-route.md`.

| # | Étape | État |
|---|---|---|
| 1 | Fondations : dépôt, architecture, configuration, santé | ✅ fait |
| 2 | Base de données : migrations, tenant, RLS, seed | ✅ fait |
| 3 | Moteur de paiement : abstraction, mock, webhooks, idempotence, grand livre, réconciliation | ✅ fait |
| 4 | Authentification Supabase + rôles | ⬜ à faire |
| 5 | Page publique de don (Next.js) | ⬜ à faire |
| 6 | Tableau de bord organisation | ⬜ à faire |
| 7 | Reçus (e-mail Resend, puis SMS/WhatsApp) | ⬜ à faire |
| 8 | **FlexPaie réel** : sandbox, adaptateur, signature, vérification | ⬜ bloqué sur la documentation FlexPaie |
| 9 | Pilote avec 1 à 3 églises | ⬜ à faire |

L'étape 8 est bloquée par des éléments que **seul FlexPaie peut fournir** :
la documentation technique, les accès sandbox, et surtout la réponse à la
question du reversement des fonds. Tout est listé dans
`01-plan-integration-flexpaie.md`, prêt à leur être envoyé.

---

## 7. Le vocabulaire, pour ne plus se perdre

| Terme | Sens concret ici |
|---|---|
| **Tenant** | Une organisation cliente (une église). Tout est isolé par tenant. |
| **Agrégateur / PSP** | L'entreprise qui déplace réellement l'argent (FlexPaie). |
| **PayIn** | Encaissement : de l'argent entre. |
| **PayOut** | Décaissement : de l'argent sort (remboursement, reversement). |
| **Webhook** | Notification poussée par l'agrégateur vers notre serveur. |
| **Idempotence** | Rejouer la même opération ne produit pas d'effet supplémentaire. |
| **Unités mineures** | Le cent : 10.00 USD = 1000. Toujours entier. |
| **Grand livre (ledger)** | Le journal comptable immuable des mouvements. |
| **Rapprochement (réconciliation)** | Vérifier que nos chiffres = ceux de la banque/de l'agrégateur. |
| **KYC** | « Know Your Customer » : les pièces d'identité exigées par l'agrégateur. |
| **RLS** | Row Level Security : filtrage des lignes directement par PostgreSQL. |
| **Sandbox** | Environnement de test de l'agrégateur, avec de l'argent fictif. |

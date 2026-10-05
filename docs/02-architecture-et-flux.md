# Architecture et flux

## 1. Les trois couches

```
┌──────────────────────────────────────────────────────────────┐
│  web/            Next.js — pages publiques + tableau de bord │
│                  Ne contient AUCUNE logique financière       │
└───────────────────────────────┬──────────────────────────────┘
                                │ HTTPS (JSON)
┌───────────────────────────────▼──────────────────────────────┐
│  api/            FastAPI — Python                            │
│                                                              │
│   api/        HTTP : validation, formats, codes d'erreur     │
│   services/   MÉTIER : dons, webhooks, comptabilité          │
│   models.py   DONNÉES : les 13 tables                        │
│                                                              │
│   ⚠️ Les règles financières vivent dans services/ : elles     │
│      doivent rester vraies quel que soit le canal d'entrée    │
│      (web, mobile, job de nuit, script de support).          │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│  supabase/       PostgreSQL + Auth + Row Level Security       │
└──────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────▼────────────┐
                    │  AGRÉGATEURS           │
                    │  MockProvider (dev)    │
                    │  FlexpaieProvider      │
                    │  (puis un PSP pour EUR)│
                    └────────────────────────┘
```

### Pourquoi séparer `api/` de `services/` ?

Parce qu'un webhook, une requête HTTP et un job de réconciliation doivent
produire **exactement le même résultat comptable**. Si la logique était écrite
dans les routes HTTP, la réconciliation en réécrirait une version légèrement
différente — et un jour, l'état d'un don dépendrait du chemin par lequel
l'information est arrivée.

Ici, les deux chemins appellent la même fonction :
`services/transaction_flow.apply_provider_state()`.

---

## 2. Le routage des paiements

Le routeur répond à une question : *pour ce pays, cette devise et ce moyen de
paiement, quel agrégateur utilise-t-on ?*

La réponse vient de la table `payment_routes`, pas du code. Changer
d'agrégateur ne demande donc **pas de redéploiement**.

Chaque règle reçoit un score de spécificité :

```
organisation dédiée   +4
pays exact            +3
devise exacte         +2
moyen de paiement     +1
```

À score égal, la priorité numérique la plus basse gagne. Une règle entièrement
vide (`NULL` partout) sert de filet de secours.

**Double sécurité** : même si une règle pointe vers un prestataire, on revérifie
ses capacités déclarées (`provider.supports(...)`). Une erreur humaine dans la
table ne peut donc pas produire un paiement que l'agrégateur ne sait pas
traiter — c'est testé (`test_les_capacites_reelles_du_prestataire_priment_sur_la_table`).

---

## 3. L'abstraction `PaymentProvider`

Tout agrégateur doit savoir faire quatre choses :

```python
class PaymentProvider(ABC):
    def initiate(self, request) -> InitiationResult          # lancer l'encaissement
    def fetch_transaction(self, id) -> ProviderTransaction   # redemander le statut
    def verify_webhook(self, body, headers) -> None          # prouver l'origine
    def parse_webhook(self, body, headers) -> WebhookEnvelope  # traduire
```

C'est le contrat minimal. Rien dans `services/` ne connaît FlexPaie : le code
métier manipule des `PaymentStatus`, des `Money`, des `WebhookEnvelope`.

Pour ajouter un agrégateur, on écrit **un fichier**, on l'enregistre dans
`build_default_registry()`, et on ajoute une ligne dans `payment_routes`.
Rien d'autre.

---

## 4. Le traitement d'un webhook, étape par étape

`api/app/services/webhooks.py` — l'ordre n'est pas décoratif.

```
 1. verify_webhook()          Signature HMAC + fenêtre anti-rejeu de 5 min.
                              Échec -> 400, événement tracé, AUCUN traitement.

 2. Journalisation            webhook_events : corps brut intégral, unique sur
                              (provider_code, provider_event_id).
                              C'est la pièce à conviction en cas de litige.

 3. Déjà traité ?             processed_at non nul -> réponse "duplicate", 200.
                              Aucun effet de bord. C'est l'idempotence.

 4. Transaction retrouvée ?   Inconnue -> 200 "ignored", erreur journalisée,
                              l'événement reste non traité pour un renvoi futur.

 5. fetch_transaction()       On RE-INTERROGE l'agrégateur. Le webhook n'est
                              qu'un déclencheur, jamais une preuve.
                              Erreur réseau -> 502, l'agrégateur renverra.

 6. apply_provider_state()    Contrôle du montant, machine à états, écritures
                              comptables. Le tout dans UNE transaction SQL :
                              statut + grand livre sont atomiques.

 7. Marquer traité            processed_at = now()
```

### Les codes de réponse HTTP pilotent les renvois

| Code | Message à l'agrégateur | Quand |
|---|---|---|
| 200 | « Pris en compte, n'insiste pas » | traité, dupliqué, ou ignoré proprement |
| 400 | « Ta requête est invalide » | signature refusée |
| 502 | « Réessaie plus tard » | notre vérification a échoué |

---

## 5. L'idempotence, à trois étages

Un même événement peut arriver plusieurs fois : réseau, renvoi automatique,
double clic du donateur. Trois verrous distincts :

```
1. Côté client        Idempotency-Key (en-tête HTTP)
                      -> index unique (organization_id, idempotency_key)
                      -> deux clics = un seul don

2. Côté webhook       index unique (provider_code, provider_event_id)
                      -> le second passage répond "duplicate" et s'arrête

3. Côté comptabilité  index unique (payment_transaction_id, entry_type)
                      -> même si les deux premiers verrous sautaient,
                         une écriture ne peut pas être doublée
```

Le troisième verrou est celui qui compte : c'est le dernier, et il protège
directement l'argent.

---

## 6. Le grand livre

Chaque don réussi génère des écritures **signées** :

```
Don de 10.00 USD, commission agrégateur 2,5 %

| entry_type   | amount_minor | currency |  signification        |
|--------------|--------------|----------|-----------------------|
| donation     |       +1000  | USD      | brut collecté         |
| provider_fee |        -25   | USD      | commission FlexPaie   |
| platform_fee |          0   | (absent si 0 bp)                 |
                                          net organisation = 975
```

Propriétés garanties :

* **immuable** — trigger PostgreSQL qui refuse `UPDATE` et `DELETE` ;
* **une seule fois** — contrainte unique par transaction et par type ;
* **traçable** — chaque écriture pointe vers le don et la transaction ;
* **cohérent** — trigger vérifiant que la devise de l'écriture = celle du don ;
* **rapprochable** — vue `v_reconciliation_par_devise` : si `dons_bruts`
  diffère de `livre_bruts`, il y a un bug à investiguer immédiatement.

Une erreur ne se corrige pas : on ajoute une écriture compensatrice
(`refund`), comme en comptabilité réelle.

---

## 7. La réconciliation

Un paiement peut rester en `PENDING` : webhook perdu, donateur qui abandonne,
webhook arrivé avant la fin de notre écriture en base.

`services/reconciliation.py` :

```
pour chaque transaction PENDING :
    état = prestataire.fetch_transaction(id)
    si état final      -> appliquer (même fonction que le webhook)
    sinon si expirée   -> EXPIRED
    sinon              -> laisser en attente
```

Au MVP, un simple appel périodique suffit (endpoint `/api/v1/testing/reconcile`
aujourd'hui, tâche planifiée ensuite). Quand le volume l'exigera, on passera
sur une file de tâches — sans changer la logique, qui est déjà isolée.

---

## 8. Multi-tenant : les trois niveaux d'isolation

```
NIVEAU 1 — le code
    Toute requête est bornée par organization_id.
    Ex. find_or_create_donor(session, organization_id, ...) : la recherche
    d'un donateur par e-mail ne déborde jamais sur une autre église.

NIVEAU 2 — la base (RLS)
    create policy donations_select_member on public.donations
        for select to authenticated
        using (public.has_org_role(organization_id,
              array['owner','admin','treasurer','viewer']));
    Même si le niveau 1 se trompe, PostgreSQL refuse la ligne.

NIVEAU 3 — les rôles
    owner      : tout, y compris la gestion des membres
    admin      : configuration, campagnes, membres (hors owners)
    treasurer  : lecture des données financières, donateurs, grand livre
    viewer     : lecture des dons et des totaux uniquement
```

Point subtil : **aucune politique RLS n'autorise `anon` ou `authenticated` à
insérer un don**. Les dons sont toujours créés par le backend avec un rôle
technique, après validation serveur du montant. Autoriser l'insertion directe
depuis le navigateur permettrait de fabriquer des dons fictifs.

> ⚠️ À savoir : la RLS ne s'applique pas au **propriétaire** des tables. Si
> l'API se connecte avec le rôle `postgres`, elle contourne la RLS. En
> production, créez un rôle dédié `generapay_api` (non propriétaire) et, pour
> les tables sensibles, `force row level security`. La procédure est décrite
> en tête de `supabase/migrations/0003_row_level_security.sql`.

---

## 9. Ce qui est volontairement absent (et pourquoi)

| Absent | Pourquoi |
|---|---|
| Portefeuille GeneraPay | Détenir les fonds des églises change le cadre juridique. Pas au MVP. |
| Conversion de devises automatique | Le montant et la devise d'origine sont sacrés. Un taux de change introduit un risque comptable. |
| File de messages (RabbitMQ/SQS) | Un planificateur suffit au volume du pilote. La logique est déjà isolée pour permettre la bascule. |
| Microservices | Un seul service bien découpé. La complexité distribuée n'apporte rien à ce stade. |
| IA | Elle n'a aucun rôle dans la chaîne financière. Uniquement, plus tard, pour du reporting. |

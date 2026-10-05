# Feuille de route

Neuf étapes, dans l'ordre. Chaque étape a un **critère d'achèvement** : si vous
ne pouvez pas le démontrer, l'étape n'est pas finie.

Principe directeur : on ne construit jamais l'étape suivante sur une étape
bancale. Dans un système financier, une fondation approximative se paie
toujours plus tard, avec intérêts.

---

## ✅ Étape 1 — Fondations

**Fait.** Dépôt, structure (`api/`, `web/`, `supabase/`, `tests/`, `docs/`),
configuration par variables d'environnement, sonde de vie `/health`,
`.gitignore`, `.env.example`.

*Critère atteint* : `GET /health` répond `{"status":"ok","database":true}`.

---

## ✅ Étape 2 — Base de données

**Fait.** 4 migrations SQL (extensions, 13 tables, RLS sur les 13 tables,
triggers d'intégrité financière), jeu de seed, modèle ORM vérifié
automatiquement contre les migrations.

*Critère atteint* : `test_migrations_et_modeles.py` passe ; la RLS couvre les
13 tables.

---

## ✅ Étape 3 — Moteur de paiement

**Fait.** Abstraction `PaymentProvider`, MockProvider signé, adaptateur
FlexPaie (fail-closed), routeur, création de don, webhooks idempotents,
vérification serveur, machine à états, grand livre, réconciliation.

*Critère atteint* : 88 tests, dont le parcours complet en HTTP réel
(don → webhook signé → succès → 2 écritures comptables), le doublon de
webhook, le montant falsifié, la signature invalide, l'échec tardif.

---

## ⬜ Étape 4 — Authentification et rôles

**Objectif** : un trésorier se connecte et ne voit que son église.

À faire :

1. Créer le projet Supabase, récupérer `SUPABASE_URL` et la clé `service_role`.
2. Implémenter la vérification du JWT Supabase dans une dépendance FastAPI
   (`get_current_user`).
3. Ajouter `get_current_membership(organization_id)` qui applique les rôles.
4. Endpoints d'administration :
   * `GET /api/v1/organizations` — mes organisations
   * `GET/PATCH /api/v1/organizations/{id}` — profil
   * `GET/POST/DELETE /api/v1/organizations/{id}/members` — gestion des rôles
5. Tests : un `viewer` ne peut pas modifier ; un membre de l'église A ne voit
   pas les données de l'église B.

*Critère d'achèvement* : deux utilisateurs, deux organisations. Chacun ne voit
que la sienne, vérifié par un test automatisé.

---

## ⬜ Étape 5 — Page publique de don (Next.js)

**Objectif** : un fidèle donne en moins de 30 secondes, sur son téléphone.

À faire :

1. Initialiser `web/` (Next.js + TypeScript + Tailwind).
2. Page `/[slug]` : identité de l'organisation, choix du type de contribution,
   montant, devise, moyen de paiement.
3. Montants suggérés (5 / 10 / 25 / 50) + montant libre — réduit la friction.
4. Génération d'une `Idempotency-Key` côté client et stockage dans
   `sessionStorage` : un double clic ne crée pas deux dons.
5. Écran d'attente avec **interrogation** de
   `GET /api/v1/public/donations/{reference}` toutes les 3 secondes.
6. Écran de remerciement, et écran d'échec avec un message clair.
7. **Mobile-first** : la grande majorité des dons vient d'un téléphone,
   souvent sur un réseau lent.

*Critère d'achèvement* : un don complet réussi depuis un téléphone, en
production de développement, sans ouvrir les outils de développement.

---

## ⬜ Étape 6 — Tableau de bord

**Objectif** : le trésorier sait où en est sa collecte en 10 secondes.

À faire :

1. `GET /api/v1/organizations/{id}/dashboard` — totaux par devise, par période,
   par type, statuts (réussi / en attente / échoué).
2. `GET /api/v1/organizations/{id}/donations` — liste paginée, filtres
   (période, type, devise, statut), recherche par référence.
3. `GET /api/v1/organizations/{id}/ledger` — le grand livre.
4. Export CSV (le trésorier veut toujours un export).
5. Rapprochement : afficher `v_reconciliation_par_devise` et signaler tout écart.

⚠️ Chaque requête doit être bornée par l'organisation de l'utilisateur, et les
totaux doivent être calculés **par devise**, jamais agrégés entre devises.
Un total « 1 500 » qui mélange USD et CDF est une faute professionnelle.

*Critère d'achèvement* : les totaux du tableau de bord correspondent au grand
livre, au centime près, pour chaque devise.

---

## ⬜ Étape 7 — Reçus

**Objectif** : chaque don réussi produit un reçu, automatiquement.

À faire :

1. Générer le reçu dans `apply_provider_state()` au passage à `SUCCESS`
   (numéro via `generate_receipt_number`, déjà écrit).
2. Envoi e-mail via Resend, avec modèle sobre : organisation, montant, devise,
   date, numéro de reçu, référence du don.
3. File `notifications` avec tentatives et erreurs — un envoi échoué se rejoue.
4. Plus tard : SMS et WhatsApp (fortement pertinents en RDC).

*Critère d'achèvement* : un don réussi produit un reçu en base **et** un
e-mail, et un don échoué n'en produit aucun.

---

## ⬜ Étape 8 — FlexPaie en réel  ⚠️ bloqué sur leur documentation

**Objectif** : de vrais francs, de vrais dollars, sur la sandbox d'abord.

Prérequis (voir `01-plan-integration-flexpaie.md`) :

* [ ] Compte enregistré sur www.flexpaie.com
* [ ] Documentation technique reçue
* [ ] Accès sandbox reçus
* [ ] Réponses aux questions 5 à 10 (endpoints, auth, **unités**, statuts,
      idempotence, signature)

Puis :

1. Renseigner `GENERAPAY_FLEXPAIE_BASE_URL`, `_API_KEY`,
   `_SIGNATURE_SCHEME`, `_WEBHOOK_SECRET`.
2. Ajuster les cinq points marqués `⚠️ NON VÉRIFIÉ` dans
   `api/app/payments/flexpaie.py`.
3. Ajouter les routes `CD + USD/CDF -> flexpaie` en base.
4. Tester en sandbox, **dans cet ordre** :
   succès → échec → expiration → webhook dupliqué → signature invalide →
   montant erroné → webhook perdu puis réconciliation.
5. Vérifier le **rapprochement** entre nos écritures et le relevé sandbox.
6. Demander à FlexPaie la vérification technique de l'intégration.

*Critère d'achèvement* : un paiement sandbox réel aboutit, avec la signature
vérifiée, et notre grand livre correspond au relevé FlexPaie.

---

## ⬜ Étape 9 — Pilote

**Objectif** : prouver le système en vrai, sans risque.

1. Choisir **1 à 3 organisations**, volontaires et techniquement à l'aise.
2. Faire le KYC métier de chacune (voir `05-conformite-et-risques.md` §2).
3. Activer leur compte marchand (`merchant_accounts.status = 'active'`).
4. Fixer des **plafonds** bas pour les deux premières semaines.
5. Former le trésorier : consulter, exporter, réconcilier.
6. Suivi **quotidien** des 4 requêtes de `05-conformite-et-risques.md` §6.
7. Journal de bord : chaque incident noté, chaque correctif tracé.
8. Après 4 semaines sans écart de rapprochement : ouverture progressive.

*Critère d'achèvement* : 4 semaines de fonctionnement, zéro écart de
rapprochement, zéro incident de sécurité.

---

## Après le MVP

| Version | Contenu | Condition |
|---|---|---|
| V2 | Campagnes publiques, QR codes, cartes, second PSP pour l'euro | Pilote validé |
| V3 | Dons récurrents, SMS/WhatsApp, facturation SaaS | Base d'organisations active |
| V4 | Marque blanche, domaines personnalisés, API publique | Demande client réelle |
| V5 | Assistant IA sur les rapports | Uniquement en lecture, jamais sur la chaîne financière |

**Règle pour l'IA** (AGENTS.md §28) : elle ne confirme jamais un paiement, ne
modifie jamais le grand livre, et toute réponse chiffrée doit provenir d'une
requête vérifiée en base. Une IA qui invente un montant dans un rapport
financier détruit la confiance en une seule phrase.

---

## Ce qu'il faut faire cette semaine

Dans l'ordre, et rien d'autre ne presse :

1. **S'enregistrer sur www.flexpaie.com** et préparer le dossier
   (RCCM, IDNAT, NIF, pièce d'identité).
2. **Envoyer les 14 questions** de `01-plan-integration-flexpaie.md` §4.
3. **Accepter la réunion technique** et imposer l'ordre du jour proposé.
4. Pendant ce temps : développer l'**étape 4** (authentification) et
   l'**étape 5** (page de don) sur le MockProvider.

Le code avance pendant que la conformité suit son cours. C'est le seul moyen
de ne pas perdre un mois à attendre.

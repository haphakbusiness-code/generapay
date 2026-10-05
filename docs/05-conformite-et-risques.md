# Conformité, sécurité et risques

> ⚠️ **Avertissement** : ce document recense les risques et les questions à
> poser aux bonnes personnes. Il ne constitue **pas** un avis juridique.
> Les règles applicables en RDC (et dans chaque pays visé) doivent être
> validées par un conseil juridique local et par le service conformité de
> vos agrégateurs. Rien ici ne doit être considéré comme une certitude
> réglementaire.

---

## 1. Le risque n°1 : détenir l'argent des autres

**Le principe que GeneraPay respecte** : l'argent va du donateur à
l'organisation, via l'agrégateur. GeneraPay ne le touche pas.

Dès qu'un fonds appartenant à une église transite par un compte HAPHAK — même
quelques heures — la situation change de nature : gestion de fonds pour compte
de tiers, obligations de connaissance client, éventuellement agrément.

**À faire :**

1. Poser la question à FlexPaie (questions 1 et 4 de
   `01-plan-integration-flexpaie.md`) : sous-comptes ou reversement direct ?
2. Faire relire le modèle par un conseil juridique avant le pilote.
3. Tant que la réponse n'est pas claire, privilégier le modèle où **chaque
   organisation possède son propre compte marchand**, ses identifiants étant
   stockés côté serveur, chiffrés, par organisation.

Le champ `merchant_accounts.settlement_mode` existe précisément pour rendre
cette décision visible et vérifiable, ligne par ligne.

---

## 2. Connaître ses organisations (KYC « métier »)

L'agrégateur va vous demander comment vous identifiez vos clients. Préparez la
réponse avant qu'on vous la pose. Procédure minimale recommandée, à activer
avant qu'une organisation puisse encaisser :

- [ ] Statuts ou acte de création de l'organisation
- [ ] Identité du responsable légal
- [ ] Compte bancaire / Mobile Money **au nom de l'organisation**
      (jamais au nom d'une personne physique)
- [ ] Vérification humaine avant activation (`merchant_accounts.status = 'active'`)
- [ ] Journalisation de la validation dans `audit_logs`
- [ ] Procédure de suspension rapide (`organizations.status = 'suspended'`)

Sans ce dispositif, la plateforme devient un canal anonyme — exactement ce que
redoute un service conformité.

---

## 3. Données personnelles

Les données manipulées sont sensibles par nature : identité du donateur,
téléphone, e-mail, **historique de dons** (qui révèle une appartenance
religieuse et des convictions).

Règles appliquées et à appliquer :

* **Minimisation** : seul ce qui est nécessaire au reçu et au suivi est collecté.
* **Don anonyme** : `donors.is_anonymous` et `donations.is_anonymous` permettent
  de donner sans être identifié publiquement.
* **Cloisonnement** : un donateur n'apparaît que dans le fichier de
  l'organisation à laquelle il a donné (RLS + requêtes bornées).
* **Accès restreint** : les données donateurs ne sont visibles que par
  `owner`, `admin`, `treasurer` — pas par `viewer`.
* **Aucune exposition publique** : les endpoints publics ne renvoient jamais
  de nom, d'e-mail ou de téléphone.
* **À prévoir** : politique de confidentialité, durée de conservation,
  procédure d'effacement, registre des traitements.

---

## 4. Sécurité technique — l'état réel

### Déjà en place

| Mesure | Où |
|---|---|
| Vérification de signature des webhooks (HMAC + fenêtre anti-rejeu 5 min) | `payments/mock.py`, `payments/flexpaie.py` |
| Fail-closed si le schéma de signature est inconnu | `payments/flexpaie.py` |
| Vérification serveur systématique auprès de l'agrégateur | `services/webhooks.py` |
| Idempotence à trois étages (client, webhook, comptabilité) | contraintes uniques + code |
| Machine à états stricte | `domain/state_machine.py` + trigger SQL |
| Grand livre immuable | trigger SQL + `revoke update, delete` |
| Row Level Security sur les 13 tables | `migrations/0003` |
| Rôles à privilège minimum | `domain/enums.py` + politiques RLS |
| Secrets hors du code | `.env` + `.gitignore` |
| Endpoints de test désactivables | `GENERAPAY_ALLOW_TESTING_ENDPOINTS` |
| Journalisation des webhooks non authentifiés | `services/webhooks.py` |

### À faire avant la production

- [ ] **HTTPS obligatoire** et redirection HTTP → HTTPS
- [ ] **Rôle de base dédié** pour l'API (`generapay_api`), non propriétaire des
      tables, avec `force row level security` sur les tables sensibles
- [ ] **Chiffrement des identifiants marchands** (`merchant_accounts`) au repos
- [ ] **Limitation de débit** sur les endpoints publics (un don par IP et par
      minute, par exemple) — critique : ces endpoints sont ouverts à tous
- [ ] **Restriction d'accès aux webhooks** : liste blanche d'IP de l'agrégateur
      si FlexPaie la propose
- [ ] **Sauvegardes** PostgreSQL testées (une sauvegarde jamais restaurée
      n'est pas une sauvegarde)
- [ ] **Supervision** : alertes sur les paiements bloqués en `pending`, sur
      l'écart `dons_bruts` ≠ `livre_bruts`, sur les webhooks rejetés
- [ ] **CORS restreint** aux domaines réels (aujourd'hui `*` en développement)
- [ ] **Audit de sécurité** avant le pilote, puis annuel

---

## 5. Les pièges qui coûtent cher

Classés par fréquence observée dans les systèmes de paiement.

### Piège 1 — L'unité du montant
L'agrégateur attend des francs entiers, vous envoyez des centimes : le
donateur est débité 100 fois trop. **Question 7 de la liste FlexPaie.**
Un test d'intégration en sandbox avec un petit montant réel est obligatoire
avant tout passage en production.

### Piège 2 — Croire le webhook
Un webhook non authentifié est une porte ouverte. On vérifie la signature,
puis on **re-interroge** l'agrégateur.

### Piège 3 — Le webhook dupliqué
Sans contrainte unique, deux webhooks = deux écritures comptables = le double
dans le rapport du trésorier. Trois verrous sont en place.

### Piège 4 — Le statut mal interprété
Un statut inconnu interprété comme « succès » crée de l'argent fictif.
Ici, tout statut inconnu reste `pending` — et la réconciliation tranchera.

### Piège 5 — Le float
Voir `docs/00-lisez-moi-dabord.md`. Aucun `float` ne touche l'argent.

### Piège 6 — La conversion de devise silencieuse
Convertir un don en CDF vers l'USD « pour le rapport » et écraser la valeur
d'origine détruit la traçabilité. Le montant et la devise d'origine sont
immuables (trigger SQL). Les conversions éventuelles sont **indicatives** et
affichées séparément.

### Piège 7 — L'arrondi des frais
Arrondir une commission vers le bas fait apparaître un net supérieur à la
réalité. Ici, arrondi **au centime supérieur**.

### Piège 8 — Oublier les frais de retrait
FlexPaie annonce 2,5 %, mais les frais de retrait dépendent des opérateurs.
Le coût réel affiché aux églises doit inclure les deux, sinon la première
réconciliation sera douloureuse.

### Piège 9 — Le paiement bloqué en attente
Sans réconciliation, des dizaines de dons restent `pending` et personne ne
sait s'ils ont abouti. Le job existe ; il faut le planifier.

### Piège 10 — Corriger l'histoire
Modifier une écriture passée « pour que ça tombe juste » détruit la confiance
et rend tout rapprochement impossible. Toujours une écriture compensatrice.

---

## 6. Ce qu'il faut surveiller chaque jour pendant le pilote

```sql
-- 1. Écart entre dons et grand livre (doit être vide)
select * from public.v_reconciliation_par_devise
where dons_bruts <> livre_bruts;

-- 2. Paiements bloqués en attente depuis plus d'une heure
select count(*) from public.payment_transactions
where status = 'pending' and created_at < now() - interval '1 hour';

-- 3. Webhooks rejetés ou non traités
select provider_code, count(*) from public.webhook_events
where processed_at is null and created_at > now() - interval '1 day'
group by provider_code;

-- 4. Échecs par code (pour détecter une panne d'opérateur)
select failure_code, count(*) from public.payment_transactions
where status = 'failed' and created_at > now() - interval '1 day'
group by failure_code;
```

Un pilote se lance avec des **montants limités**, une ou deux organisations,
et un suivi quotidien. Pas avec trente églises le premier jour.

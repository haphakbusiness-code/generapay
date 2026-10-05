# Plan d'intégration FlexPaie

> Analyse de la réponse officielle de FlexPaie à HAPHAK, point par point, avec
> ce qui est **confirmé**, ce qui reste **inconnu**, et ce qui **bloque**.
>
> Règle appliquée ici (AGENTS.md §26) : on ne présente jamais une capacité
> supposée comme un fait. Tout ce qui n'est pas écrit par FlexPaie est marqué
> « À CONFIRMER ».

---

## 1. Ce que FlexPaie a confirmé par écrit

| Sujet | Réponse FlexPaie | Conséquence pour nous |
|---|---|---|
| Accès API | Enregistrement marchand sur www.flexpaie.com | À faire maintenant : c'est le point d'entrée de tout le reste |
| Sandbox | Oui, environnement de test disponible | On peut développer l'adaptateur avant la production |
| Documentation | Fournie aux marchands **approuvés** | ⚠️ La doc arrive **après** validation du dossier — voir §5 |
| Ouverture de compte | RCCM, IDNAT, NIF ou statuts, pièce d'identité du représentant légal | Dossier à préparer (voir §6) |
| KYC sectoriel | Exigences communiquées après enregistrement | Prévoir un second tour de pièces |
| Frais d'accès API | **100 USD** | À clarifier : une fois, ou par compte marchand ? (voir §3) |
| Commission | **2,5 %** sur Mobile Money et Visa/Mastercard | À intégrer au calcul de frais — déjà codé (250 points de base) |
| Frais de retrait | Dépendent des opérateurs / banques | ⚠️ Coût réel incomplet : il manque ce barème |
| Devises | **USD et CDF uniquement** | ⚠️ **L'euro n'est pas couvert** — voir §2 |
| Moyens de paiement | Mobile Money, Visa, Mastercard | Conforme au besoin |
| Webhooks | Mentionnés dans la documentation | Le schéma exact est inconnu pour l'instant |
| Partenariat | Ouvert, réunion proposée | **À accepter** : c'est là que se règle la question des fonds |
| Passage en production | KYC + vérification technique + tests sandbox + activation | Prévoir plusieurs semaines, pas quelques jours |

---

## 2. Le point bloquant n°1 : l'euro

FlexPaie ne traite que **USD et CDF**. Vous voulez collecter en **USD, CDF et EUR**.

Ce n'est pas un détail : l'euro vise précisément le cas d'usage le plus
rentable pour une église congolaise, **la diaspora** (France, Belgique,
Allemagne) qui donne par carte bancaire.

### Pourquoi ce n'est pas grave architecturalement

Le système est déjà conçu pour plusieurs agrégateurs. Le routeur
(`api/app/payments/router.py`) décide en fonction du pays, de la devise et du
moyen de paiement, via la table `payment_routes` :

```
CD + CDF + mobile_money  ->  flexpaie
CD + USD + mobile_money  ->  flexpaie
FR + EUR + card          ->  stripe        (à intégrer plus tard)
```

Ajouter l'euro plus tard = **un fichier d'adaptateur + une ligne en base**.
Aucune réécriture. C'est exactement le but de l'abstraction `PaymentProvider`.

### Les options réalistes pour l'euro

À évaluer, aucune n'est encore vérifiée :

1. **PSP international** (Stripe, Adyen, Mangopay, PayPal…) — le plus simple
   techniquement, mais la plupart exigent une entité juridique dans un pays
   supporté. À vérifier au cas par cas.
2. **Rester en USD pour la diaspora** — la plupart des cartes internationales
   acceptent un paiement en USD ; la conversion se fait côté banque du
   donateur. C'est souvent la solution la plus rapide à mettre en œuvre.
3. **Partenaire porteur** — une structure partenaire encaisse l'euro et
   reverse. Ajoute un intermédiaire et des frais.

**Recommandation** : lancer le MVP sur USD + CDF (FlexPaie), et traiter l'euro
comme une étape distincte, après le pilote. Ne pas retarder le lancement pour
l'euro.

---

## 3. Le point bloquant n°2 : où va l'argent ?

C'est **la** question à poser, avant toute autre.

Leur e-mail parle d'**un** « compte marchand », avec les documents de
**votre** entreprise (RCCM, IDNAT, NIF). Rien n'est dit sur :

* l'existence de **sous-comptes** par organisation ;
* un **reversement direct** vers le compte bancaire de chaque église ;
* le **partage** d'un paiement (split settlement).

Or c'est décisif :

* si l'argent des églises arrive sur un compte **HAPHAK**, puis est reversé,
  HAPHAK détient des fonds pour compte de tiers. Cela change radicalement le
  cadre juridique et les obligations (agrément, conformité, lutte anti-blanchiment,
  garanties). **À faire valider par un conseil juridique et par la conformité
  de FlexPaie — ne pas présumer de la réponse.**
* si chaque église a **son propre compte marchand FlexPaie**, HAPHAK ne touche
  jamais les fonds : c'est propre, et c'est compatible avec le MVP.

### Ce que le code prévoit déjà

La table `merchant_accounts` est conçue pour les deux modèles, avec un champ
explicite :

```sql
settlement_mode text check (settlement_mode in
    ('direct_to_organization',   -- l'agrégateur paie l'église directement  ✅ cible
     'platform_account',         -- l'argent passe par HAPHAK              ⚠️ à éviter
     'unconfirmed'))             -- état actuel : la question n'est pas tranchée
```

La ligne de seed de l'organisation de démonstration est volontairement à
`unconfirmed` / `pending_kyc` : le code dit la vérité sur l'état du dossier.

**Recommandation pour le MVP** : modèle « chaque église ouvre son propre compte
marchand », ses identifiants étant stockés côté serveur, par organisation.
GeneraPay reste un logiciel. Si FlexPaie propose des sous-comptes, on bascule
sans changer le modèle de données.

---

## 4. Les 14 questions à envoyer à FlexPaie

Copiez-collez cette liste dans votre prochain e-mail. Elle est ordonnée :
les 4 premières sont bloquantes.

**Fonds et contrat**
1. Proposez-vous des **sous-comptes** ou un **reversement direct** vers le
   compte bancaire de chaque organisation cliente ? Ou l'intégralité des
   encaissements arrive-t-elle sur le compte marchand unique de HAPHAK ?
2. Les **100 USD** d'accès API sont-ils uniques pour HAPHAK, ou dus **par
   compte marchand** ouvert ?
3. Quel est le **barème des frais de retrait / de règlement** appliqué par
   chaque opérateur Mobile Money et par les banques partenaires ?
4. Quel est le **délai de règlement** (J+0, J+1, J+n) et le mode de mise à
   disposition des fonds ?

**Technique — indispensable pour coder**
5. URL de base de la **sandbox** et chemins exacts des endpoints
   PayIn, PayOut, statut de transaction.
6. **Schéma d'authentification** : clé API simple, Bearer token, OAuth2,
   signature de requête ? Durée de vie et renouvellement des jetons ?
7. **Unité des montants** : francs/dollars entiers, décimales, ou unités
   mineures (centimes) ? Format attendu pour le CDF en particulier.
8. **Liste exacte des statuts** de transaction renvoyés par l'API et par les
   webhooks, avec leur signification.
9. **Idempotence** : pouvons-nous transmettre notre propre référence
   (`GP-XXXXXX`) pour qu'une requête rejouée ne double pas le débit ?
10. **Schéma de signature des webhooks** : algorithme (HMAC-SHA256 ?),
    entête utilisé, données signées (corps brut ? corps + horodatage ?),
    et gestion du secret.
11. **Politique de renvoi** des webhooks en cas de non-réponse (nombre de
    tentatives, intervalles, durée totale).
12. Existe-t-il un **fichier ou une API de règlement journalier**
    (settlement report) pour le rapprochement comptable ?
13. Quels **numéros de test** (MSISDN) et scénarios sont disponibles en
    sandbox (succès, échec, solde insuffisant, expiration, doublon) ?
14. **Limites** : plafond par transaction, plafond journalier, débit par
    minute, et éventuelle liste blanche d'adresses IP.

---

## 5. Le calendrier réaliste

```
 SEMAINE 1 ── Enregistrement sur www.flexpaie.com
              Préparation du dossier (RCCM, IDNAT, NIF, pièce d'identité)
              Envoi des 14 questions ci-dessus
              Acceptation de la réunion technique (ordre du jour ci-dessous)

 SEMAINE 2 ── Réunion technique FlexPaie
              Réception documentation + accès sandbox (si possible avant
              la validation KYC complète — à demander explicitement)

 SEMAINE 3 ── Finalisation de l'adaptateur FlexpaieProvider
              (endpoints, unités, statuts, signature)
              Tests sandbox : succès, échec, expiration, doublon, montant faux

 SEMAINE 4 ── Développement de l'interface (page de don, tableau de bord)
              pendant que le dossier KYC suit son cours

 SEMAINE 5+ ── Validation conformité FlexPaie
               Vérification de l'intégration par leurs équipes
               Activation du compte marchand
               Pilote avec 1 à 3 églises, en montant limité
```

Comptez **4 à 8 semaines** entre l'inscription et le premier don réel. Ce
délai vient de la conformité, pas du code : le code sera prêt bien avant.
C'est précisément pour cela qu'on développe sur le MockProvider en attendant.

### Ordre du jour à proposer pour la réunion technique

1. Modèle multi-organisations : sous-comptes ou reversement direct ? (30 min)
2. Démonstration du besoin : GeneraPay est un logiciel, pas un établissement
   de paiement ; nous ne voulons pas détenir les fonds des églises. (10 min)
3. Parcours technique : sandbox, signature des webhooks, idempotence. (20 min)
4. Rapprochement : format du relevé de règlement. (10 min)
5. Tarification multi-comptes et volume. (10 min)

---

## 6. Dossier d'ouverture — checklist

À réunir avant l'inscription :

- [ ] **RCCM** (Registre du Commerce et du Crédit Mobilier)
- [ ] **IDNAT** (numéro d'identification nationale)
- [ ] **NIF** (numéro d'identification fiscale) ou statuts de l'entreprise
- [ ] **Pièce d'identité** du représentant légal
- [ ] Coordonnées bancaires de l'entreprise
- [ ] Description de l'activité (prévoir la mention « plateforme logicielle de
      collecte de dons pour des organisations tierces » — la conformité posera
      la question, autant y répondre clairement dès le départ)
- [ ] Site web ou présentation (un domaine `generapay…` crédibilise le dossier)

Puis, selon leur retour : les pièces KYC sectorielles complémentaires.

> 💡 Conseil d'expérience : la conformité d'un agrégateur tique presque
> toujours sur les plateformes **multi-organisations**, parce que le risque de
> blanchiment y est plus élevé. Anticipez la question : préparez une note d'une
> page décrivant comment vous identifiez chaque église cliente (statuts,
> responsable, compte bancaire au nom de l'organisation, vérification humaine
> avant activation). Cela accélère le dossier de plusieurs semaines.

---

## 7. Ce que le code fait déjà, et ce qu'il refuse de faire

### Déjà prêt

* Le modèle de données complet, y compris `merchant_accounts` et
  `payment_routes` pour le multi-agrégateurs.
* Le routeur qui choisit le prestataire selon pays / devise / moyen de paiement.
* Le calcul des frais en **points de base**, avec `flexpaie_fee_bps = 250`
  (les 2,5 % annoncés), arrondi au centime supérieur.
* Le cycle complet : initiation, webhook signé, vérification serveur,
  machine à états, grand livre, réconciliation.
* Le MockProvider, qui imite un agrégateur réaliste (signature HMAC, fenêtre
  anti-rejeu de 5 minutes, statuts interrogeables).

### Volontairement bloqué

`api/app/payments/flexpaie.py` applique le principe **fail-closed** :

```python
if scheme == "unverified":
    raise WebhookVerificationError(
        "Schéma de signature FlexPaie non confirmé. Webhook refusé."
    )
```

Tant que le schéma de signature n'est pas documenté, **aucun webhook FlexPaie
n'est accepté**. Un paiement restera en attente (et sera rattrapé par la
réconciliation) plutôt que d'être crédité sur la foi d'une notification non
authentifiée. Ce comportement est verrouillé par les tests
(`tests/api/test_adaptateur_flexpaie.py`).

De même, l'adaptateur refuse de faire le moindre appel réseau tant que
`GENERAPAY_FLEXPAIE_BASE_URL` et `GENERAPAY_FLEXPAIE_API_KEY` ne sont pas
renseignés.

### À compléter dès réception de la documentation

Les endroits exacts sont signalés dans le code par `⚠️ NON VÉRIFIÉ` :

| Fichier | Ce qu'il faudra ajuster |
|---|---|
| `payments/flexpaie.py` → `initiate()` | chemin de l'endpoint, noms des champs, **unité du montant** |
| `payments/flexpaie.py` → `_auth_headers()` | Bearer token ou entête propriétaire |
| `payments/flexpaie.py` → `_map_status()` | liste exacte des statuts |
| `payments/flexpaie.py` → `verify_webhook()` | schéma de signature réel |
| `payments/flexpaie.py` → `parse_webhook()` | structure de l'événement |

C'est quelques heures de travail une fois la documentation en main — à
condition que les réponses aux questions 5 à 10 aient été obtenues.

---

## 8. Modèle économique à trancher de votre côté

FlexPaie prélève 2,5 %. Qui les paie ?

| Option | Effet sur un don de 10 USD | Effet sur un don de 5 000 FC |
|---|---|---|
| **L'organisation absorbe** | l'église reçoit 9,75 USD | l'église reçoit 4 875 FC |
| **Le donateur paie en sus** | le donateur paie 10,25 USD, l'église reçoit 10,00 | le donateur paie 5 125 FC, l'église reçoit 5 000 FC |
| **Partagé** | à paramétrer | à paramétrer |

Le code gère déjà les deux premières : le calcul de frais vit dans
`api/app/domain/ledger.py`, et la commission plateforme (`platform_fee_bps`)
est un paramètre aujourd'hui à **0**.

Il faudra ajouter, par organisation, un réglage `fee_mode`
(`absorbed` / `added_to_donor`). Ce n'est pas encore implémenté : c'est une
décision commerciale qui vous appartient, à prendre avant le pilote.

> N'oubliez pas d'ajouter au calcul les **frais de retrait** évoqués par
> FlexPaie (question 3) : le coût réel supporté par l'église est
> `2,5 % + frais de retrait`, pas 2,5 %.

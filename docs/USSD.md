# Canal USSD — WASH-SENTINEL (V2)

Signalement de panne depuis un feature phone, sans data, via menus USSD
sessionnés en français. Le signalement validé suit le même pipeline que
le canal SMS : `MeshBundle` (`origin ussd:<empreinte>`) + triage IA
standard avec `source = 'ussd'`.

Fichiers : `backend/app/Http/Controllers/Api/WashUssdController.php`,
routes `POST`/`GET /api/v1/mesh/ussd` dans `backend/routes/api.php`,
extensions USSD dans `backend/app/Services/MeshSmsParser.php`,
tests `backend/tests/Feature/WashUssdTest.php`.

## 1. Format passerelle (style Africa's Talking)

Chaque interaction utilisateur génère un appel vers la passerelle, qui le
relaye au backend. Requête (form-encoded ou JSON, throttle 60/min) :

| Champ         | Obligatoire | Description                                    |
|---------------|-------------|------------------------------------------------|
| `sessionId`   | oui         | Id unique de session fourni par la passerelle  |
| `serviceCode` | non         | Code USSD composé (ex. `*123#`), informatif   |
| `phoneNumber` | oui         | Numéro appelant, **jamais persisté** (voir §5) |
| `text`        | non (`""` au premier appel) | Saisies cumulées séparées par `*` |

Réponse : `200` + `Content-Type: text/plain`, corps préfixé :

- `CON <message>` → poursuivre (la passerelle affiche `<message>`) ;
- `END <message>` → terminer (la passerelle affiche `<message>` et raccroche).

Exemple d'échange (`text` cumulatif, seule la **dernière** saisie après le
dernier `*` est interprétée ; l'état vit en cache Laravel, TTL 10 min) :

```
      Téléphone                 Passerelle                Backend
          |                         |                         |
          |--- compose *123# ------>|                         |
          |                         |--- text="" ------------>|
          |                         |<-- CON Bienvenue... ----|
          |<-- affiche menu --------|                         |
          |--- 1 ------------------>|                         |
          |                         |--- text="1" ----------->|
          |                         |<-- CON code ecole... ---|
          |--- DOU-BON-001 -------------->|                         |
          |                         |--- text="1*DOU-BON-001" ----->|
          |                         |<-- CON Type de panne... |
          |--- ... ---------------->|                         |
          |                         |--- text="1*DOU-BON-001*1*2*..*1"
          |                         |<-- END Merci! Ticket... |
```

## 2. Diagramme des menus

```
ACCUEIL (text="")
  "Bienvenue WASH-SENTINEL / 1. Signaler une panne / 0. Quitter"
   ├─ 1 ──> CODE ECOLE ──> saisie libre, ex. DOU-BON-001 (validé : school existe)
   │           ├─ 0 ──> END "Session terminee."
   │           ├─ code inconnu ──> CON "inconnu, reessayez" (max 3 essais, puis END)
   │           └─ code OK ──> TYPE PANNE
   │                 "1. Pompe/forage / 2. Latrine / 3. Eau/qualite / 4. Hygiene / 0. Annuler"
   │                 (accepte aussi P/L/E/H et mots-clés SMS : POMPE, LATRINE, EAU, SAVON…)
   │                 ├─ 0 ──> END (annulation, rien créé)
   │                 ├─ choix invalide ──> CON "Choix invalide" + menu (session conservée)
   │                 └─ 1-4 ──> URGENCE
   │                       "1. Normale / 2. Urgente (pas d'eau / risque sante) / 0. Annuler"
   │                       └─ 1-2 ──> DESCRIPTION
   │                             "Breve description (max 100 car.) / 9. Passer / 0. Annuler"
   │                             └─ texte|9 ──> CONFIRMATION
   │                                   "Ecole / Type / Urgence / Desc / 1. Confirmer / 0. Annuler"
   │                                   ├─ 1 ──> crée l'incident ──> END "Merci! Ticket: <ref>"
   │                                   └─ 0 ──> END "Signalement annule."
   └─ 0 ──> END "Session terminee."
```

Comportements transverses :

- `0` annule à toute étape (rien n'est créé, session oubliée) ;
- choix invalide aux étapes `type` / `urgence` / `confirmation` : le menu
  est réaffiché en `CON`, sans perdre la session ;
- code école : insensible à la casse et aux tirets (`dou-bon-001` OK) ;
- description : 100 caractères max, balises HTML supprimées ;
- quota journalier par appelant (même réglage que le SMS,
  `services.mesh.sms_quota_per_sender`, défaut 10) ;
- dédup : même appelant + même message normalisé sur 24 h → `END`
  « Signalement deja recu » avec le ticket existant ;
- idempotence : rejeu passerelle (même `sessionId` après succès) → même
  ticket, un seul incident (marqueur 24 h en cache).

## 3. Exemples curl (vérifiés contre la suite de tests)

Base locale : `http://localhost` (Laravel, port 80 — le port 8000 est
celui du moteur IA, voir `compose.yaml`).

```bash
# 1. Accueil (premier appel, text vide)
curl -s -X POST http://localhost/api/v1/mesh/ussd \
  -d sessionId=demo-001 -d serviceCode='*123#' \
  -d phoneNumber=+237600000001 -d text=''
# → CON Bienvenue WASH-SENTINEL / 1. Signaler une panne / 0. Quitter

# 2. Choisir "Signaler"
curl -s -X POST http://localhost/api/v1/mesh/ussd \
  -d sessionId=demo-001 -d serviceCode='*123#' \
  -d phoneNumber=+237600000001 -d text='1'
# → CON Entrez le code ecole (ex: DOU-BON-001): / 0. Annuler

# 3. Code école (doit exister en base, ex. DOU-BON-001)
curl -s -X POST http://localhost/api/v1/mesh/ussd \
  -d sessionId=demo-001 -d serviceCode='*123#' \
  -d phoneNumber=+237600000001 -d text='1*DOU-BON-001'
# → CON Type de panne: / 1. Pompe/forage / 2. Latrine / ...

# 4. Type = Pompe/forage, puis urgence = Urgente
curl -s -X POST http://localhost/api/v1/mesh/ussd \
  -d sessionId=demo-001 -d serviceCode='*123#' \
  -d phoneNumber=+237600000001 -d text='1*DOU-BON-001*1'
# → CON Urgence: / 1. Normale / 2. Urgente ...

curl -s -X POST http://localhost/api/v1/mesh/ussd \
  -d sessionId=demo-001 -d serviceCode='*123#' \
  -d phoneNumber=+237600000001 -d text='1*DOU-BON-001*1*2'
# → CON Breve description (max 100 car.): / 9. Passer / 0. Annuler

# 5. Description courte (ou 9 pour passer)
curl -s -X POST http://localhost/api/v1/mesh/ussd \
  -d sessionId=demo-001 -d serviceCode='*123#' \
  -d phoneNumber=+237600000001 -d text='1*DOU-BON-001*1*2*POMPE CASSEE'
# → CON Confirmer? / Ecole: DOU-BON-001 / Type: panne pompe/forage / ...

# 6. Confirmation → incident créé
curl -s -X POST http://localhost/api/v1/mesh/ussd \
  -d sessionId=demo-001 -d serviceCode='*123#' \
  -d phoneNumber=+237600000001 -d text='1*DOU-BON-001*1*2*POMPE CASSEE*1'
# → END Merci! Signalement enregistre. Ticket: <ref>

# Sondage GET pour tests manuels (mêmes paramètres en query string)
curl -s 'http://localhost/api/v1/mesh/ussd?sessionId=demo-002&serviceCode=*123%23&phoneNumber=+237600000001&text='
# → CON Bienvenue WASH-SENTINEL ...
```

## 4. Limites connues

- `*123#` fictif : aucun code opérateur provisionné. Le `serviceCode` est
  informatif (fourni par la passerelle) — à remplacer par le vrai code
  lors du raccordement opérateur.
- `*` interdit dans la description : ce caractère étant le séparateur de
  `text`, seule la partie après le dernier `*` est lue.
- Pas de navigation « retour » (`#`/back) : seule l'annulation (`0`) est
  proposée ; une erreur de frappe au code école se corrige par réessai.
- Session de 10 min : passé le TTL, l'état est perdu et la requête
  suivante est traitée comme un nouvel appel (retour à l'accueil,
  l'utilisateur recommence) — cas rare, la passerelle enchaîne les
  écrans en quelques secondes.
- Écrans courts : menus sans accents (GSM 7-bit), ≤ 160 caractères par
  écran quand l'école/description le permet ; la confirmation peut
  dépasser avec un nom d'école long (2 segments USSD).
- Pas de secret partagé ni allowlist : contrairement au SMS (`secret`
  SMSSync), l'authentification repose sur la passerelle/opérateur
  (restreindre si besoin par IP côté reverse-proxy) ; throttle 60/min
  appliqué comme le SMS.
- Un seul signalement par session ; le quota par appelant est mutualisé
  avec le réglage SMS (`MESH_SMS_QUOTA_PER_SENDER`).

## 5. Vie privée

- Le `phoneNumber` n'est persisté nulle part : ni dans `mesh_bundles`
  (ni `origin_node_id`, ni `payload`, ni `message`), ni dans
  `reports`/`incidents`, ni en cache, ni dans les logs.
- Seule une empreinte `sha256(phoneNumber)` tronquée à 16 caractères
  (préfixée `ussd:`) sert d'identifiant d'origine pour le quota
  journalier et la dédup 24 h — non réversible.

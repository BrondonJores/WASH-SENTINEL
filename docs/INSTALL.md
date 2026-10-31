# WASH Relai — installer l'app terrain

L'app terrain est la page **`/m`** : publique (sans login), offline-first,
installable. Trois formats selon l'appareil.

| Appareil | Format | Relai mesh | Obtention |
|---|---|---|---|
| iPhone | PWA « WASH Relai » (écran d'accueil) | saisie + QR + upload (pas de fond) | §1 |
| Android | PWA ou APK natif | complet (Nearby + BLE + SMS) | §1 / §3 |
| PC (Linux/Win/Mac) | binaire `wash-relai` | saisie + QR + upload | §2 |

## 1. iPhone — PWA (recommandé)

1. Ouvrir Safari sur `https://<serveur>/m` **une fois en ligne**
   (précharge l'app : ~20 fichiers, ~2 Mo).
2. Partage → **Sur l'écran d'accueil** → Ajouter.
3. L'icône « WASH Relai » démarre plein écran, **même en mode avion**.

Sur Android/desktop (Chromium), pas besoin du menu : l'app affiche elle-même
un bouton **Installer** (prompt in-app sur `beforeinstallprompt`, voir
`frontend/src/lib/install-prompt.ts`). Sur iPhone, Safari ne propose aucun
prompt système : l'app affiche à la place une carte d'aide **Ajouter à
l'écran d'accueil** (Partage → Sur l'écran d'accueil → Ajouter), masquable
(« Compris », mémorisé en local).

> iOS interdit le relai Bluetooth en arrière-plan : l'iPhone **crée** des
> signalements, les **transfère en QR** (affiché ou photo importée) et les
> **uploade** dès qu'il capte. Le relai automatique de poche à poche,
> c'est Android.

## 2. PC — binaire desktop

Précompilé en CI (artefact `wash-relai-desktop`) ou en local (requiert
réseau : `build.sh` lance `neu update`, qui télécharge les binaires +
le client Neutralino) :

```bash
cd desktop && npm install && bash build.sh
# → dist/wash-relai/wash-relai-linux_x64 (ou -win_x64.exe, -mac_*)
# + dist/wash-relai-release.zip (les 3 OS)
```

Double-cliquer : la fenêtre ouvre directement `/m` (URL Neutralino
`/index.html#/m`, cf. `desktop/neutralino.config.json`), offline inclus
(service worker + file locale). Transférer un bundle : afficher le QR
à l'écran ou importer une photo de QR.

## 3. Android — APK natif

Compilé en CI (artefact `wash-relai-apk`, job `android`) :

```bash
cd mesh/android
gradle wrapper              # une fois : génère gradlew (jar non versionné)
./gradlew :app:assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk
```

L'APK relaie en tâche de fond : Nearby Connections (primaire), BLE GATT
(secours sans Play Services), passerelle SMS. Détails (prérequis JDK/SDK,
`gradle.properties`, clés) : `mesh/android/README.md`.

## 4. Comment l'offline marche (les 3 formats)

1. Le formulaire écrit dans une **file locale** (localStorage Android/iPhone/PC).
2. Sans réseau : bouton **QR** → le voisin scanne (caméra ou photo).
3. Dès qu'un porteur capte : **upload** vers `/api/v1/mesh/bundles`
   (dédup par `bundle_id`, accusés anti-doublons).
4. Secours ultime : **SMS** pré-rempli (ex. `WASH DOU-BON-001 P` —
   `DOU-BON-001` = école seedée de démo, voir `WashDemoSeeder`) vers le
   numéro passerelle (`VITE_SMS_GATEWAY_NUMBER` dans `frontend/.env` ;
   vide = secours SMS masqué dans l'app), ou **USSD** (`*384*…#`, menus
   guidés, voir `docs/USSD.md`) depuis n'importe quel téléphone 2G.

## 5. Limites honnêtes

- Première install = une visite en ligne (incompressible, c'est le web).
- iPhone/PC ne relaient pas en fond (OS) : ils créent, portent, uploadent.
- Photos/vocal : stockés chiffrés (E2E) dans la file quand la clé serveur
  est joignable, sinon en clair (l'app l'indique) ; envoyés en fragments
  à la reconnexion — pas de QR pour les médias (trop gros).

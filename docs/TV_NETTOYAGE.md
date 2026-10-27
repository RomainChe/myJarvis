# TV sans pub : plan de nettoyage

Demandé le 2026-10-27. Objectif : une Google TV (Continental Edison) sans publicité ni logiciel inutile, avec
l'accueil JARVIS à la place de l'accueil Google TV, sans perdre ce qui marche déjà (APK `android-tv/`,
interface `tv/`, liaison au Core, Bowd/OpenFlix, Tailscale, pilotage par Home Assistant).
S'appuie sur la Phase 7, piste 6 de docs/ROADMAP.md : ce plan en est l'étape (d), élargie au nettoyage.

## Principes (non négociables)
- **Tout est réversible.** On désactive (`pm disable-user --user 0`), on ne désinstalle pas. Retour arrière :
  `adb shell pm enable <paquet>`. Le launcher Google TV reste installé (repli décidé en Phase 7).
- **Liste noire explicite, revue avant application.** Aucun paquet n'est touché « par motif » : chaque paquet
  désactivé est listé avec sa raison dans `scripts/tv_paquets.json`, relu par le propriétaire.
- **Liste protégée.** Jamais désactivés : services Google Play (`com.google.android.gms`), Play Store,
  WebView, assistant de configuration, service Android TV Remote (`com.google.android.tv.remote.service`,
  utilisé par Home Assistant), Chromecast intégré (`com.google.android.apps.mediashell`), Tailscale,
  JARVIS (`fr.jarvis.tv`) et les applis des tuiles (`Apps.java` : Netflix, YouTube, Prime Video, Disney+,
  Spotify, Plex, SmartTube, Twitch).
- **ADB coupé à la fin.** Débogage réseau désactivé et autorisations révoquées (TV partagée, cf. README APK).
- Dépôt public : la liste des paquets n'est pas une donnée personnelle ; aucune IP de TV dans les fichiers.

## Étapes

### 1. Gains immédiats, sans ADB (propriétaire, 10 min)
- Google TV : *Paramètres > Comptes et connexion > (compte) > Mode applis uniquement* : retire les
  recommandations et bannières sponsorisées de l'accueil Google TV (officiel, réversible).
- *Paramètres > Confidentialité > Annonces* : supprimer l'identifiant publicitaire et refuser la
  personnalisation ; *Utilisation et diagnostics* : désactivé.
- Désinstaller normalement (Play Store) les applis préinstallées non utilisées qui le permettent.

### 2. Inventaire (Claude + propriétaire)
- `scripts/tv_debloat.py liste` : `adb shell pm list packages` (+ `-d` pour les déjà désactivés), version
  d'Android TV, launcher par défaut ; écrit l'inventaire dans un fichier local hors Git.
- Classer chaque paquet : **pub/suggestions** (ex. `com.google.android.tvrecommendations`, chaînes et
  « Découvrir » du launcher), **constructeur** (applis Continental Edison et partenaires préinstallés),
  **télémétrie**, **à garder**. Résultat : `scripts/tv_paquets.json` (paquet, catégorie, raison).

### 3. Désactivation par ADB (script, réversible)
- `scripts/tv_debloat.py appliquer` : à blanc par défaut (affiche ce qui serait fait), `--oui` pour agir ;
  refuse tout paquet de la liste protégée, même s'il est dans la liste noire ; journalise chaque paquet
  (avant/après) dans un fichier local.
- `scripts/tv_debloat.py annuler` : `pm enable` sur toute la liste (retour à l'état d'origine).
- Tests `tests/test_tv_debloat.py` (adb simulé) : cas nominal, paquet protégé refusé, entrée invalide
  (nom de paquet hors `[A-Za-z0-9._]`), mode à blanc sans effet, annulation.
- Essai sur la TV par lots (pub d'abord, puis constructeur), avec redémarrage et vérification des tuiles,
  de Home Assistant (allumage, volume) et de « JARVIS en ligne » entre chaque lot.

### 4. Accueil JARVIS par défaut (étape (d) de la ROADMAP)
- **Prérequis bloquant** : compteur de plantages au démarrage dans `MainActivity` (après N échecs rapprochés,
  bascule durable vers l'accueil Google TV ou les réglages, sans boucle). Le repli `fallback()` vise déjà
  les réglages si le launcher Google est désactivé.
- Rendre JARVIS accueil par défaut : choisir JARVIS à la touche Accueil, puis
  `pm disable-user --user 0 com.google.android.apps.tv.launcherx` (méthode la plus répandue ; à comparer
  avec un service d'accessibilité qui intercepte la touche Accueil, plus intrusif). Retour : `pm enable`.
- Vérifier : touche Accueil, démarrage à froid, sortie de veille, réglages et sources atteignables depuis
  JARVIS, tuile « Accueil Google TV » (grisée ou retirée si le launcher est désactivé).
- Revue Sécurité (§5 du CLAUDE.md : clôt une étape de la ROADMAP).

### 5. Filtrage DNS des pubs restantes (dans les applis, les sites)
Décision du propriétaire attendue, deux options :
- **A. DNS privé public** (rapide) : `adb shell settings put global private_dns_mode hostname` puis
  `settings put global private_dns_specifier dns.adguard-dns.com`. Rien à héberger, mais les requêtes DNS
  de la TV partent chez AdGuard (cloud). Retour : `private_dns_mode off`.
- **B. AdGuard Home sur le mini-PC** (local, cohérent avec la règle « local d'abord ») : conteneur Docker,
  déclaré comme serveur DNS de Tailscale (avec renvoi de `ts.net` vers `100.100.100.100`), statistiques
  lisibles par JARVIS (outil N0 plus tard). Nouvelle intégration réseau : revue Sécurité obligatoire.
- Dans les deux cas, **à tester en premier** : que le nom `*.ts.net` du Core se résout toujours (sinon
  « JARVIS hors ligne »), et que Netflix, YouTube/SmartTube, Bowd et OpenFlix marchent (listes blanches au
  besoin). SmartTube reste la réponse aux pubs YouTube (le DNS ne les bloque pas).

### 6. Clôture
- Débogage USB/réseau désactivé, *Révoquer les autorisations de débogage* ; clé `tv` n°9 révoquée
  (`python -m jarvis device revoke`), en attente depuis l'étape (c).
- Docs : `android-tv/README.md` (procédure de nettoyage et d'annulation), docs/ROADMAP.md (état),
  docs/HISTORIQUE.md (détail), journal du skill `tv-remote-ui` si un problème de télécommande apparaît.

## Tâches

| # | Tâche | Qui | Dépend de |
|---|-------|-----|-----------|
| T1 | Mode applis uniquement, identifiant publicitaire, diagnostics (étape 1) | Propriétaire | — |
| T2 | Activer ADB, `adb connect` depuis le PC | Propriétaire | — |
| T3 | `scripts/tv_debloat.py liste` + tests | Claude | — |
| T4 | Inventaire réel et `scripts/tv_paquets.json` classé, relu | Claude + propriétaire | T2, T3 |
| T5 | `appliquer` / `annuler` (à blanc par défaut, liste protégée) + tests | Claude | T3 |
| T6 | Désactivation par lots sur la TV, vérifications entre lots | Propriétaire (guidé) | T4, T5 |
| T7 | Compteur de plantages au démarrage (`MainActivity`) + essai | Claude | — |
| T8 | JARVIS accueil par défaut, launcher Google désactivé, vérifications | Propriétaire (guidé) | T6, T7 |
| T9 | Revue Sécurité de l'étape (d) (T3–T8) | Sécurité | T8 |
| T10 | Choix DNS (A ou B) | Propriétaire | — |
| T11 | Mise en place du DNS choisi + test `ts.net` et applis | Claude + propriétaire | T10 |
| T12 | Couper ADB, révoquer la clé `tv` n°9, docs à jour | Propriétaire + Claude | T8, T11 |

Ordre conseillé : T1, T2 et T10 tout de suite ; T3, T5 et T7 en parallèle côté code ; puis T4, T6, T8.

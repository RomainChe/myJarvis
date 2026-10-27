# TV sans pub : plan de nettoyage

Demandé le 2026-10-27, d'après la vidéo TikTok @meetmargin sur **cleanyourtv** (github.com/Gathin23/cleanyourtv,
licence MIT, relu au commit `c5f9cd4`). Objectif : une Google TV (Continental Edison) sans publicité ni logiciel
inutile, avec l'accueil JARVIS à la place de l'accueil Google TV, sans perdre ce qui marche déjà (APK
`android-tv/`, interface `tv/`, liaison au Core, Bowd/OpenFlix, Tailscale, pilotage par Home Assistant).
C'est l'étape (d) de la Phase 7, piste 6 (docs/ROADMAP.md), élargie au nettoyage.

## Ce que fait la vidéo (et ce qu'on en garde)
| Vidéo / cleanyourtv | Chez nous |
|---|---|
| 1. Options développeur (7 appuis sur *Build*), débogage USB + réseau | Identique (déjà fait une fois pour l'APK). |
| 2. PC sur le même Wi-Fi, Claude Code reçoit `PROMPT.md` + le modèle de TV | Identique, mais on suit **notre** plan ; `PROMPT.md` sert de référence, pas d'instructions. |
| 3. Sauvegarde (paquets, réglages, `getprop`) + script d'annulation `tools/restore.sh` | Identique, avec leurs outils `disable.ps1` / `restore.ps1` (Windows). |
| 4. Claude demande les applis utilisées, puis désactive pub, pistage, applis inutiles (`pm disable-user`, rien de désinstallé) | Identique ; liste écrite pour cette TV (absente de leurs 336 modèles). |
| 5. Nouveau launcher natif, défini comme accueil | **Remplacé par l'accueil JARVIS** (APK déjà fait, liaison au Core, Bowd/OpenFlix). |
| 6. DNS anti-pub en option (DNS privé AdGuard public) | **AdGuard Home sur le mini-PC** (choix du propriétaire, 2026-10-27). |
| 7. Débogage coupé à la fin | Identique, avec vérification que le port 5555 refuse. |
| Bonus : TVWizard (Claude pilote la TV à la voix) | Déjà couvert par JARVIS (voix, scènes, Home Assistant). |
| Les pubs dans YouTube restent | SmartTube (déjà une tuile). |

## Principes (non négociables)
- **Tout est réversible** : `pm disable-user --user 0`, jamais de désinstallation ; `restore.ps1` réactive tout.
  Le launcher Google TV reste installé (repli décidé en Phase 7).
- **Liste relue avant application** : chaque paquet désactivé a sa raison dans `android-tv/debloat.txt`.
- **Jamais désactivés** : services Google Play, Play Store, WebView, clavier, services d'entrée HDMI/tuner et
  menu Sources, appairage télécommande/Bluetooth, service Android TV Remote
  (`com.google.android.tv.remote.service`, utilisé par Home Assistant), Chromecast intégré
  (`com.google.android.apps.mediashell`) si utilisé, Tailscale, JARVIS (`fr.jarvis.tv`), les applis des tuiles
  (`Apps.java`), et les paquets cœur d'Android listés par cleanyourtv (`permissioncontroller`,
  `packageinstaller`, `ext.services`, `providers.*`, `systemui`, `settings`, `tv.settings`…), qu'un Mi TV Stick
  n'a pas survécu.
- **Pièges Google TV relevés par cleanyourtv** :
  - l'assistant de configuration (`com.google.android.tungsten.setupwraith`) reprend la touche Accueil quand le
    launcher Google est désactivé ; le désactiver **efface le Wi-Fi enregistré pendant la 1re configuration**
    (TV hors réseau, ADB perdu). Vérifier `dumpsys wifi | grep -o 'cname=[^ ]*'` avant ; au besoin oublier puis
    rejoindre le Wi-Fi dans les Réglages ;
  - `cmd package set-home-activity` peut répondre `Success` sans rien changer : confirmer avec
    `dumpsys activity activities | grep mFocusedApp` ;
  - le launcher Google gère aussi les **boutons de la télécommande** (Netflix, YouTube, Sources, Réglages) :
    après sa désactivation, les essayer un par un ;
  - attendre ~15 s (ou `adb shell sync`) avant de redémarrer, puis comparer `pm list packages -d` : certains
    firmwares réactivent des paquets à chaque démarrage ;
  - ne jamais lancer un paquet « factory », « fac », « AT » pour voir ce qu'il fait.
- **ADB fermé à la fin** (TV partagée) ; dépôt public : aucune IP de TV dans les fichiers.

## Étapes

### 1. Gains immédiats, sans ADB (propriétaire, 10 min)
- *Paramètres > Comptes et connexion > (compte) > Mode applis uniquement* : plus de bannières sponsorisées.
- *Confidentialité > Annonces* : supprimer l'identifiant publicitaire ; *Utilisation et diagnostics* : désactivé.

### 2. Préparation (Claude + propriétaire)
- PC : cloner cleanyourtv au commit relu, `python -m venv tools/venv`, `pip install -r tools/requirements.txt` ;
  relire `disable.ps1`, `restore.ps1`, `tv.py`, `check.py` avant de les lancer (code tiers avec accès ADB).
- TV : débogage USB et réseau activés, `adb connect`, accepter l'invite.
- Sauvegarde : liste des paquets, paquets déjà désactivés, `getprop`, réglages (`settings list global|secure|system`)
  dans un dossier local hors Git. Noter la version d'Android TV et `ro.build.version.sdk`.

### 3. Inventaire et liste (Claude + propriétaire)
- Classer chaque paquet : pistage constructeur, pub et recommandations (`tvrecommendations`, chaînes du launcher),
  services en double, applis préinstallées, applis de streaming. `dumpsys package` pour tout nom obscur.
- Point de départ (paquets Google désactivés par la plupart des listes cleanyourtv) : `feedback`, `play.games`,
  `youtube.tvmusic`, `tvrecommendations`, `tv.bugreportsender`, `partnersetup`, `videos`, `onetimeinitializer`,
  `backdrop` ; `katniss` (Assistant) et Chromecast seulement si le propriétaire ne s'en sert pas.
- Résultat : `android-tv/debloat.txt` (format cleanyourtv : un paquet par ligne, `#` pour la raison), relu.

### 4. Désactivation par lots (propriétaire guidé)
- `disable.ps1 android-tv/debloat.txt`, lot par lot (pistage, puis pub, puis préinstallées) ; un `pm` par appel.
- Entre chaque lot : redémarrage (après `sync`), tuiles JARVIS, Home Assistant (allumage, volume), « JARVIS en ligne ».
- Annulation : `restore.ps1 android-tv/debloat.txt`.
- Contribution possible : proposer la liste à cleanyourtv (modèle Continental Edison absent).

### 5. Accueil JARVIS par défaut (étape (d))
- **Bloquant** : compteur de plantages au démarrage dans `MainActivity` (après N échecs rapprochés, bascule
  durable vers les réglages, sans boucle ; `fallback()` vise déjà les réglages si le launcher Google est coupé).
- `cmd package set-home-activity fr.jarvis.tv/.MainActivity`, vérification `mFocusedApp`, puis
  `pm disable-user --user 0 com.google.android.apps.tv.launcherx` ; setupwraith selon le piège ci-dessus.
- Boutons de la télécommande : essayer Netflix, YouTube, Sources, Réglages, Accueil ; ceux qui ne répondent plus
  sont repris par JARVIS (service d'accessibilité limité à ces touches, à comparer, cf. ROADMAP (d)).
- Vérifier aussi : démarrage à froid, sortie de veille, réglages et sources atteignables depuis JARVIS, tuile
  « Accueil Google TV » retirée quand le launcher est coupé.
- Revue Sécurité (clôt une étape de la ROADMAP).

### 6. AdGuard Home sur le mini-PC (choix du propriétaire)
- Conteneur Docker sur le mini-PC ; interface d'administration joignable seulement par Tailscale ; identifiants
  dans les identifiants systemd chiffrés (`jarvis/core/secrets.py`).
- **Fait (2026-10-27, T10)** : `/srv/adguard/docker-compose.yml`, `network_mode: host` (la redirection de ports
  Docker était bloquée par `ufw`, politique « routed » à `deny`). Assistant d'installation : administration sur
  l'IP Tailscale seulement (port 80), DNS sur toutes les interfaces (port 53) ; `ufw` n'ouvre le 53 qu'à Tailscale et
  au réseau local. Amonts DoH Quad9 + Cloudflare en parallèle. L'ACL Tailscale ne laisse passer que le 22 et le 8123 :
  l'administration se consulte par tunnel SSH (`ssh -N -L 8081:<ip-tailscale>:80 jarvis@<minipc>`).
- Distribution (**option retenue**) : la TV n'a pas Tailscale. Son DNS est réglé à la main (IP statique, DNS 1 = mini-PC,
  DNS 2 vide : Android mélange les deux serveurs, un DNS de secours laisserait passer des pubs). L'IP de la TV est
  réservée dans la Bbox (« Rendre statique » dans Mes appareils). Vérifié : requêtes de la TV dans le journal AdGuard ;
  YouTube, Netflix, Prime Video, Disney+ fonctionnent. Annulation : TV en DHCP automatique.
  **Pas de DNS privé** sur la TV : il contournerait AdGuard Home. Variante maison entière : option 6 du DHCP de la
  Bbox (Réglages avancés > DHCP), non retenue : mini-PC éteint = plus d'Internet pour toute la maison.
- Mini-PC éteint : la TV n'a plus de DNS. Sonde de santé prévue (IDEES.md #36).
- Tests : Core joignable (« JARVIS en ligne »), Netflix, Prime Video, Disney+, SmartTube, Bowd, OpenFlix ; listes
  blanches au besoin.
- JARVIS (plus tard) : outil N0 « statistiques AdGuard » et N1 « pause du blocage 5 min » (comme l'add-on
  ad-blocking de cleanyourtv). Nouvelle intégration réseau : revue Sécurité.

### 7. Clôture
- Débogage USB et réseau coupés, autorisations révoquées, redémarrage, `tools/adb-closed.py <ip>` doit dire
  « connexion refusée ». Clé `tv` n°9 révoquée (`python -m jarvis device revoke`).
- Docs : `android-tv/README.md` (nettoyage et annulation), ROADMAP (état), HISTORIQUE (détail), journal du skill
  `tv-remote-ui` si un souci de télécommande apparaît.

## Tâches

| # | Tâche | Qui | Dépend de |
|---|-------|-----|-----------|
| T1 | Mode applis uniquement, identifiant publicitaire, diagnostics | Propriétaire | — |
| T2 | Cloner cleanyourtv (commit relu), venv, relecture des scripts | Claude | — |
| T3 | Activer ADB sur la TV, `adb connect`, sauvegarde complète | Propriétaire + Claude | T2 |
| T4 | Inventaire classé, `android-tv/debloat.txt` relu | Claude + propriétaire | T3 |
| T5 | Désactivation par lots, vérifications entre lots | Propriétaire (guidé) | T4 |
| T6 | Compteur de plantages au démarrage (`MainActivity`) + essai | Claude | — |
| T7 | JARVIS accueil par défaut, launcher Google coupé, setupwraith, boutons télécommande | Propriétaire (guidé) | T5, T6 |
| T8 | Reprise des boutons télécommande orphelins (si besoin) | Claude | T7 |
| T9 | Revue Sécurité de l'étape (d) | Sécurité | T7, T8 |
| T10 | AdGuard Home (Docker, mini-PC), DNS Tailscale, 2e serveur | Claude + propriétaire | — |
| T11 | Tests DNS : Core, applis, sites ; revue Sécurité | Claude + Sécurité | T10 |
| T12 | Outils JARVIS AdGuard (N0 stats, N1 pause) | Claude | T11 |
| T13 | Couper ADB, vérifier le port 5555, révoquer la clé `tv` n°9, docs à jour | Propriétaire + Claude | T7, T11 |

Ordre conseillé : T1 tout de suite ; T2, T6 et T10 en parallèle ; puis T3, T4, T5, T7.

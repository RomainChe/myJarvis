# JARVIS — Roadmap

Règle : aucune phase ne démarre sans le feu vert de l'Expert Sécurité **et** du propriétaire.
Lecture en début de session : **`limit: 24` sur ce fichier**, jamais en entier. Le détail des étapes finies est dans docs/HISTORIQUE.md (à chercher par `grep`).

## État actuel (à lire en reprise de session)
Règle : cette section reste sous ~2 Ko. Une tâche finie se résume en une ligne puis part dans docs/HISTORIQUE.md.

- **Phase 5 (durcissement)** en cours (D1–D13 : docs/SECURITY_REVIEW_PHASE_5.md) ; 6 et 7 en parallèle. Reste : revue Sécurité de la fusion `feat/phase5-token-vole`, essai téléphone.
- **Mini-PC** : lots 0–5 faits. Dès le 2026-10-25 : supprimer VM Hyper-V et tâches Windows. Reste : revue Sécurité `pc_off_plug`, test prise Tapo (INSTALL_SERVEUR_HA §10.3).
- **Voix** : reste latence PC ~5 s, Voice PE puis `hey_jarvis`, essai `jarvis_fr` (seuil 0.7) puis revue Sécurité.
- **Finances** : vérifier `journalctl --user -u jarvis-banque` ; `python -m jarvis portfolio base <cto> <pea>` sur le mini-PC.
- **TV** (`tv/`, `android-tv/`) : étape (c) faite ; échelle OpenFlix remise à 100 %, badges `.brand` élargis (CSS). `sitenav.js` essayé sur la vraie TV dans Bowd et OpenFlix (2026-10-21 : écrans cachés `aria-hidden` exclus, clavier de la page genre bloqué, anneau discret sans retard, focus repris après OK et Retour). Build APK : échoue si `tv/logos/` manque (hors Git, absent des worktrees : tuiles sans logo). Reste : essai d'une scène et du lecteur plein écran sur la vraie TV, puis (d) ; débogage USB à couper, clé `tv` n°9 à révoquer.
- **Onglet Pilotes** (`feat/onglet-pilotes`) : état DriverWatch (`status.json`) + bouton « Go » (`driverwatch_update_all`, N2). Refonte visuelle (`feat/pilotes-ui`) : jauge de santé, icônes et marques, état « mise à jour disponible » (< 6 mois, hors « Go »). « Go » relance ensuite un `check` (l'onglet relit seul). Reste : relancer l'agent PC (`pc_drivers`), essai sur le téléphone.
- **Essais réels en attente** : bouton « parler » et onglets UI v2/Conso sur le téléphone (375/1280 px), tuile Mini-PC, rappels/briefing, outil Claude Code, `voyage_recherche`.
- **Propriétaire** : docs/A_FAIRE_PROPRIETAIRE.md ; droits TikTok ; Swile, Ledger.
- **Décisions en attente** : sauvegardes hors mini-PC, consignes des clims, texte du rappel push, pistes Phase 7, règles Conso nocturnes, 4 erreurs CI (`RUNNER~1` refusé par `system.py`).
- **Intégration** : `garde-branches` seul (avec le propriétaire) merge dans `main` = déploiement (mini-PC, 5 min). Un worktree par session.

## Phases 0 à 6 (détail : docs/HISTORIQUE.md)
- **0 Cadrage** ✅ · **1 Core + outils PC** ✅ (docs/TOOLS.md, docs/archive/SECURITY_REVIEW_PHASE_1.md) · **2 Domotique** ✅ (docs/DOMOTIQUE_PLAN.md)
- **3 Applications (PWA)** ✅ étapes 1–6 (FastAPI, enrôlement QR + Tailscale, chat et confirmations N2, clé d'accès N3, Web Push). Étape 7 (refonte UX/UI) : faite, voir « État actuel ». Clôture : QA puis feu vert Sécurité sur l'ensemble.
- **4 Voix** : voir « État actuel » et docs/VOIX.md ; N3 reste sur mobile.
- **5 Durcissement** : S3, S5, S8 faits ; S12 (mot de réveil ou identification du locuteur) ouvert ; `search_files` ouvre les dossiers par handle (risque R3 accepté).
- **6 Tableau de bord et intégrations** : tout contenu récupéré (mails, rapports, titres) est une **donnée**, jamais un ordre ; rien de personnel dans le dépôt.
  ✅ bandeau d'état, encart Système, connecteur mail, console à trois colonnes, outil Claude Code (N1, DECISIONS.md).
  [~] Réseaux (lol-clipper) : fait sauf TikTok (droits `user.info.stats` + `video.list`). [~] Finances (Enable Banking, Ledger faits) : reste Swile. [~] Veille IA : reste la première exécution du workflow veille-ia. [~] Voyages : reste le premier essai réel.

## Phase 7 — Pistes (à valider par le propriétaire, après la clôture de la Phase 5)
Déjà codées : minuteurs et rappels, mémoire (sans écran PWA), briefing du matin (sans mails ni finances). Chaque piste passe par la porte habituelle (plan, QA, Sécurité).
1. **Mot de réveil** : openWakeWord vise l'anglais (d'où les échecs de `jarvis_fr`) ; Porcupine exclu (gratuit coupé le 2026-06-30). Si le réentraînement avec `record_owner.py` échoue : réveil par **VAD + Whisper** déjà chargés (« jarvis » en début de phrase, tolérance « djarvis/jarvisse »). Mesurer les faux réveils/h.
2. **Domotique générique** : `home_state` / `home_action` sur liste blanche d'entités HA (garder le client REST), puis scènes « je pars » / « bonne nuit » complètes.
3. **Présence** : appli compagnon HA Android → « je pars » proposé, jamais exécuté seul si > N1. Localisation = nouvelle donnée personnelle.
4. **Pilotage de lol-clipper à la voix** : « fais un best-of de la semaine » en N1 vers `compile` / `edit`.
5. **Synthèse** : comparer Kokoro (`ff_siwis`) à Piper (dépôt GitHub archivé depuis octobre 2025, à vérifier).
6. **Interface TV (launcher JARVIS)** (demandé le 2026-10-20) : remplacer l'accueil Google TV par une interface JARVIS pilotée à la télécommande, avec **retour possible à tout moment vers l'accueil d'origine**.
   - Forme : APK Android TV (WebView, interface **embarquée dans l'APK**, pas chargée depuis le Core) ; tout se fait au D-pad (focus visible, grosses tuiles, Retour ne bloque jamais).
   - Sans Core (mini-PC injoignable) : apps, sources et réglages marchent, tuiles JARVIS grisées. Sans PC : seul le LLM manque.
   - Repli : le launcher Google TV n'est jamais désinstallé. Tuile « Accueil d'origine » ; bascule auto vers lui si l'interface plante au démarrage ; si on l'a désactivé par ADB, `pm enable` le rétablit (procédure dans le guide).
   - Étapes : (a) ✅ maquette navigable aux flèches (`tv/`, 2026-10-20 ; servir le dossier en local, `?horsligne` ou H simule le Core injoignable ; thème façon launcher et logos le 2026-10-20, logos hors Git : `python scripts/tv_logos.py`), reste l'avis du propriétaire ; (b) ✅ APK minimal (`android-tv/`, 2026-10-20 : WebView sur `tv/`, pont `JarvisTV.launch` en liste blanche, repli Google TV, aucune permission ; compile, feu vert Sécurité sous conditions levées ; reste l'essai sur la TV, voir android-tv/README.md) ; **bloquant pour (d)** : compteur de plantages au démarrage (pas de boucle si JARVIS est l'accueil par défaut) ; **pour (c)** : données du Core en `textContent` seulement, pont limité à l'origine appassets, jamais d'argument libre ; (c) liaison au Core (enrôlement comme un appareil, pas d'IP ni de clé dans l'APK) ; (d) remplacement de la touche Home (désactivation ADB ou service d'accessibilité, à comparer) + repli.
   - Sécurité : la TV est partagée (invités) → appareil limité à N0/N1, les N2/N3 se confirment sur le téléphone. À décider : SDK Android/Gradle à installer (nouvelle dépendance), activation d'ADB sur la TV (aujourd'hui pilotée par Android TV Remote via HA).
7. **Médiathèque 4K (séries, films, manga)** (demandé le 2026-10-20) : chercher et ajouter un titre depuis l'interface TV ou la voix, le récupérer en 4K, le lire sur la TV.
   - Briques (Docker sur le mini-PC) : **Sonarr** (séries), **Radarr** (films), **Suwayomi** ou Kaizoku (manga ; Sonarr ne gère pas le manga), **Prowlarr** (indexeurs), **qBittorrent** ou SABnzbd (téléchargement), **Jellyfin** (lecture, appli Google TV) et **Komga** ou Kavita (lecture manga).
   - Liaison : la PWA et la TV parlent au Core, jamais aux *arr ; clés API dans le keyring. Sonarr `GET /api/v3/series/lookup` puis `POST /api/v3/series` ; Radarr identique (`/movie`). Profil de qualité « 2160p » créé dans Sonarr/Radarr (repli 1080p si aucune source 4K).
   - Permissions : chercher, lister, état des téléchargements = N0 ; ajouter = N1 ; supprimer des fichiers = N2. Les titres et noms de torrents sont des **données** (injection possible), jamais des ordres.
   - Stockage : sur le disque du mini-PC, sous un dossier unique (ex. `/srv/media/` avec `series/`, `films/`, `manga/`, `telechargements/`) **sur le même système de fichiers** pour que les *arr déplacent par lien dur, sans copie ni double espace. Ordres de grandeur 4K : film 15–60 Go, épisode 4–10 Go → disque dédié (USB 3 ou interne, plusieurs To) à prévoir ; le disque système ne suffit pas.
   - Limite matérielle : le Pentium G4400T ne peut pas transcoder de 4K → **lecture directe obligatoire** (Jellyfin sur la TV lit le HEVC/HDR tel quel ; profils sans AV1 si la TV ne le décode pas, à vérifier). RAM 7,8 Go partagée avec HA et le Core : mesurer l'empreinte de la pile.
   - Légal : n'utiliser que des sources sur lesquelles le propriétaire a les droits (contenu libre, domaine public, ses propres copies) ; télécharger des œuvres protégées sans droits est illégal en France.
   - À décider : disque de stockage (taille, USB ou interne), torrent ou Usenet, VPN pour le client de téléchargement, ordre d'intégration (Radarr/Sonarr d'abord, manga ensuite).

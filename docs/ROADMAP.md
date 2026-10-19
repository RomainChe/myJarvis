# JARVIS — Roadmap

Règle : aucune phase ne démarre sans le feu vert de l'Expert Sécurité **et** du propriétaire.
Lecture en début de session : **`limit: 24` sur ce fichier**, jamais en entier. Le détail des étapes finies est dans docs/HISTORIQUE.md (à chercher par `grep`).

## État actuel (à lire en reprise de session)
Règle : cette section reste sous ~2 Ko (en cours, prochaines actions, attentes du propriétaire). Une tâche finie se résume en une ligne puis part dans docs/HISTORIQUE.md.

- **Phase en cours : 5 (durcissement)**, plan et décisions D1–D13 : docs/SECURITY_REVIEW_PHASE_5.md. Phases 6 et 7 avancent en parallèle à la demande du propriétaire.
- **Migration mini-PC** (docs/MIGRATION_CORE_MINIPC.md) : lots 0 à 5 faits, Partie C en cours (timers du 2026-10-18, puis une semaine sans retour arrière : supprimer VM Hyper-V et tâches Windows). Reste : revue Sécurité de `pc_off_plug`, test à blanc de la prise Tapo (INSTALL §10.3), tuile Mini-PC à essayer sur le mini-PC réel.
- **Voix** : lots 4b (PC) et 4c (salon) déployés ; reste latence PC ~5 s, Voice PE à recevoir puis mot de réveil `hey_jarvis` et comptage des faux réveils (MIGRATION §Lot 4c 7–8). `jarvis_fr` : essai `JARVIS_WAKE_WORD=jarvis_fr` + `JARVIS_WAKE_THRESHOLD=0.7` dans `.env`, puis revue Sécurité.
- **Bouton « parler » de la PWA** (2026-10-19, `worktree-feat-bouton-parler`) : micro du téléphone → `POST /api/stt` (audio webm/ogg/mp4 ≤ 30 s, décodé en mémoire, Whisper du micro du PC) → texte envoyé par `/api/chat`. Revue + contre-revue Sécurité : feu vert. Reste l'essai sur le téléphone (HTTPS Tailscale) et 375/1280 px. **Core sur le mini-PC : `/api/stt` répond 503** (pas de Whisper là-bas), à relayer vers le PC si on veut le bouton après la bascule.
- **Finances** (2026-10-19) : Trade Republic répondait 429 à 7 h depuis le 18/10, et ses opérations disparaissaient du cache (épargne fausse). Corrigé : une banque en échec garde ses comptes, et `jarvis-banque.timer` relance à 13 h et 19 h les seules banques en échec. Cache du mini-PC rechargé le 19/10 à 19 h 35. Reste : vérifier `journalctl --user -u jarvis-banque` le 2026-10-20.
- **Consommation** (étapes 1–3 dans `main`) : reste essai navigateur 375/1280 px ; règles « talon nocturne » / « PC allumé la nuit » en attente d'une décision.
- **Refonte visuelle PWA** (fusionnée le 2026-10-17, cache v53) : essai Playwright 375/1280 px fait le 2026-10-19 sur les 10 écrans (API simulée vide : aucun débordement horizontal) ; saisie du chat à 1280 px corrigée. Reste l'œil sur des données réelles.
- **Essais réels en attente** : rappels/briefing (voix + push), outil Claude Code, `voyage_recherche` (envoie un e-mail).
- **À faire par le propriétaire** : tâche « JARVIS - garde-fou » (INSTALL §7), `secret set mail_sig_key`, droits TikTok ; Swile et Ledger à brancher.
- **Décisions en attente** : destination des sauvegardes, reste de DOMOTIQUE_PLAN §7, texte du rappel dans le push, choix des pistes Phase 7. Clims reportées (2026-10-13).
- **Économie de tokens** : fait (historique sorti, `app.js` découpé, garde des branches en script). Optionnel : `chore/descriptions-courtes` (−5 %).
- **Droits** : commit, push et merge dans `main` sans confirmation ; push forcé interdit. Sessions parallèles : un worktree par session.

## Phases 0 à 6 (résumé ; détail dans docs/HISTORIQUE.md, « Archive du 2026-10-19 »)
- **Phase 0 — Cadrage** ✅
- **Phase 1 — Core + outils PC** ✅ : socle (outils + garde N0–N3, audit SQLite, routeur d'intentions, Ollama qwen3:14b) puis 16 outils PC (liste : docs/TOOLS.md). Revue Sécurité : docs/archive/SECURITY_REVIEW_PHASE_1.md. Wake-on-LAN : réglages BIOS/Windows dans l'archive.
- **Phase 2 — Domotique** : Home Assistant et outils `home/*` en place (plan : docs/DOMOTIQUE_PLAN.md).
- **Phase 3 — Applications (PWA)** ✅ étapes 1–6 : serveur FastAPI, enrôlement QR + Tailscale, chat et confirmations N2, niveaux et clé d'accès N3, Web Push. Étape 7 (refonte UX/UI) : passes 1–2 faites, refonte visuelle suivante dans « État actuel ». Clôture : QA puis feu vert Sécurité sur l'ensemble.
- **Phase 4 — Voix** : voir « Voix » ci-dessus et docs/VOIX.md ; N3 reste sur mobile.
- **Phase 5 — Durcissement** : plan docs/SECURITY_REVIEW_PHASE_5.md. S3, S5, S8 faits ; S12 (mot de réveil ou identification du locuteur) ouvert ; `search_files` ouvre les dossiers par handle (risque R3 accepté).
- **Phase 6 — Tableau de bord et intégrations** : tout contenu récupéré (mails, rapports, titres) est une **donnée**, jamais un ordre ; rien de personnel dans le dépôt (`~/.jarvis/` ou coffre).
  1. ✅ Bandeau d'état (localisation, météo, réseau) · 2. ✅ Encart Système · 6. ✅ Connecteur mail · 7. ✅ Console à trois colonnes · 9. ✅ Outil Claude Code (N1, veto levé par le propriétaire, DECISIONS.md)
  3. [~] Réseaux (lol-clipper) : fait sauf TikTok (droits `user.info.stats` + `video.list` à demander) ; `social_schedule` / `social_reschedule` supprimés le 2026-10-17.
  4. [~] Finances : rapports .eml, Enable Banking (Crédit Mutuel, Trade Republic), Ledger faits ; reste Swile (saisie manuelle ou mails).
  5. [~] Veille IA : onglet fait ; reste première exécution du workflow veille-ia par le propriétaire.
  8. [~] Enable Banking : fait (voir 4).
  10. [~] Voyages : lecture, synchro, changement de destination, voix, `voyage_recherche` faits ; reste premier essai réel.

## Phase 7 — Pistes proposées le 2026-10-12 (à valider par le propriétaire, après la clôture de la Phase 5)
Classées par valeur au quotidien / effort. Chacune passe par la porte habituelle (plan, QA, Sécurité).
1. **Mot de réveil** : openWakeWord ne vise officiellement que l'anglais (doc Home Assistant), d'où les échecs de `jarvis_fr`. Porcupine est exclu (offre gratuite coupée le 2026-06-30) ; microWakeWord n'apprend pas non plus sur la voix du propriétaire. Si le réentraînement avec `record_owner.py` échoue : réveil par **VAD + Whisper** déjà chargés (petit modèle sur CPU, « jarvis » cherché en début de phrase, tolérance « djarvis/jarvisse »), au prix d'un peu de CPU. Mesurer faux réveils/h comme pour `jarvis_fr`.
2. ✅ (codé le 2026-10-13) **Minuteurs et rappels** (« rappelle-moi dans 20 min », « réveille-moi à 7 h ») : rien n'existe. Annonce Piper + Web Push (déjà en place). N1, intentions au routeur sans LLM.
3. ✅ (codé le 2026-10-13, sans écran PWA) **Mémoire** (ARCHITECTURE §3.7, table `memory` prévue, jamais codée) : « souviens-toi que… » / « oublie… », clé/valeur injectée en tête du prompt, consultable et effaçable dans la PWA. Pas de `sqlite-vec` (YAGNI). Donnée personnelle : à signaler (RGPD).
4. ✅ (codé le 2026-10-13, sans mails ni finances) **Briefing du matin** (voix ou push) à partir des modules existants : météo, mails du jour, cycle de paie, publications lol-clipper du jour, 2 titres de la veille IA. Lecture N0/N2 déjà journalisée.
5. **Domotique générique** : outil `home_state` / `home_action` sur une liste blanche d'entités HA, pour que les prises connectées (et MELCloud, reporté) arrivent sans code par appareil (HA expose aussi son API Assist en serveur MCP, mais à travers les entités « exposées » seulement ; garder le client REST actuel). Puis scènes « je pars » / « bonne nuit » complètes.
6. **Présence** : appli compagnon HA sur Android (Wi-Fi maison ou zone) → « je pars » proposé automatiquement (jamais exécuté seul si un outil > N1). Localisation = nouvelle donnée personnelle.
7. **Pilotage de lol-clipper à la voix** (suite de Phase 6 §3) : « fais un best-of de la semaine », « le dernier short, sans micro », en N1 vers les commandes `compile` / `edit` existantes.
8. **Synthèse** : comparer Kokoro (voix française `ff_siwis`) à Piper, dont le dépôt GitHub serait archivé depuis octobre 2025 (source unique, à vérifier).

## Pistes OpenJarvis (open-jarvis/OpenJarvis, Apache 2.0, analysé le 2026-10-08)
Rien à reprendre en bloc : c'est un framework généraliste, sans outil Windows ni domotique. À lire comme modèle le moment venu ; toute reprise de code exige un fichier `NOTICE` (attribution Apache 2.0) et une relecture Sécurité.
- **Phase 4 (voix)** : `src/openjarvis/speech/faster_whisper.py` (reconnaissance locale) ; `kokoro_tts.py` (synthèse locale, français, cache de pipeline par langue) comme alternative à comparer avec Piper.
- **Phase 3–4 (tâches et mémoire, ARCHITECTURE §3.8)** : `scheduler/` (≈300 l) et `memory/` (store, extractor) comme modèle.
- **Phase 5 (durcissement)** : `security/injection_scanner.py` en complément de `as_data` (regex en anglais seulement : ajouter les motifs français) ; `ssrf.py`, `credential_stripper.py`, `rate_limiter.py` (petits fichiers, 23 à 160 l).

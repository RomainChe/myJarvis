# JARVIS — Roadmap

Règle : aucune phase ne démarre sans le feu vert de l'Expert Sécurité **et** du propriétaire.
Lecture en début de session : **`limit: 24` sur ce fichier**, jamais en entier. Le détail des étapes finies est dans docs/HISTORIQUE.md (à chercher par `grep`).

## État actuel (à lire en reprise de session)
Règle : cette section reste sous ~2 Ko. Une tâche finie se résume en une ligne puis part dans docs/HISTORIQUE.md.

- **Phase en cours : 5 (durcissement)**, plan et décisions D1–D13 : docs/SECURITY_REVIEW_PHASE_5.md. Phases 6 et 7 avancent en parallèle.
- **Mini-PC** (docs/MIGRATION_CORE_MINIPC.md, « Reste à faire ») : lots 0 à 5 faits. Le 2026-10-25 au plus tôt (une semaine sans retour arrière) : supprimer VM Hyper-V et tâches Windows désactivées. Reste : revue Sécurité de `pc_off_plug`, test à blanc de la prise Tapo (INSTALL_SERVEUR_HA §10.3), tuile Mini-PC à essayer.
- **Voix** : PC (4b) et salon (4c) déployés ; reste latence PC ~5 s, Voice PE à recevoir puis `hey_jarvis` et comptage des faux réveils. `jarvis_fr` : essai `JARVIS_WAKE_WORD=jarvis_fr` + `JARVIS_WAKE_THRESHOLD=0.7`, puis revue Sécurité.
- **Bouton « parler » PWA** (`/api/stt`, feu vert Sécurité) : reste l'essai sur le téléphone (HTTPS Tailscale) et 375/1280 px. Sur le mini-PC `/api/stt` répond 503 (pas de Whisper) : relayer vers le PC si voulu.
- **Finances** : relance des banques en échec à 13 h et 19 h faite ; compte d’une banque en échec marqué « non actualisé » dans l’onglet. Reste : vérifier `journalctl --user -u jarvis-banque` le 2026-10-20.
- **Consommation** : reste l'essai 375/1280 px ; règles « talon nocturne » / « PC allumé la nuit » en attente de décision.
- **Refonte UI v2** (2026-10-19, cache v58) : tous les onglets refaits, puis Dashboard/Finances retouchés (détail : docs/HISTORIQUE.md). Reste l'œil du propriétaire sur des données réelles (PC et téléphone).
- **Phase 5 étapes 1 et 9** (token volé, `feat/phase5-token-vole`, fusionnée le 2026-10-19) : D2/D6, clé d'accès pour les N2 forts (D3, Finances, retirée le 2026-10-19 par le propriétaire), token 90 j renouvelé, « révoquer tout ». Reste revue Sécurité de la fusion et essai sur le téléphone.
- **Essais réels en attente** : rappels/briefing (voix + push), outil Claude Code, `voyage_recherche` (envoie un e-mail).
- **À faire par le propriétaire** : docs/A_FAIRE_PROPRIETAIRE.md (sauvegardes hors mini-PC, `secret set mail_sig_key`, tests C5/F6/G2) ; droits TikTok ; Swile et Ledger à brancher.
- **Décisions en attente** : destination des sauvegardes, consignes des clims (reportées), texte du rappel dans le push, choix des pistes Phase 7.
- **Droits** : commit, push et merge dans `main` sans confirmation ; push forcé interdit (`main` protégée sur GitHub). Un worktree par session parallèle ; ménage : agent garde-branches « HYGIÈNE ».
- **CI** : dépendances installées ; reste 4 erreurs sur le runner (chemin temporaire court `RUNNER~1` refusé par `system.py` : contrôle du dossier utilisateur), décision du propriétaire.

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

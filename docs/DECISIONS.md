# Décisions et risques acceptés

## 2026-10-08 — Planchers de niveau abaissés de N2 à N1
- Demande du propriétaire : tous les outils peuvent être réglés en N1. `power`, `delete_file`, `move_file`, `kill_process`, `run_script` : plancher N1 (N0 reste interdit). Abaisser reste une action N3 (clé d'accès).
- Risque accepté : un outil abaissé en N1 s'exécute sans confirmation depuis la PWA ou la CLI (ex. suppression, arrêt du PC).
- Garde-fous maintenus (revue Sécurité : feu vert sous conditions, conditions remplies) : après du contenu externe, le LLM ne peut pas lancer un outil dont le niveau du registre est ≥ N2 (`llm.py`) ; à la voix, le niveau du registre s'applique toujours (`permissions.execute`, source `voix`), car le micro entend aussi la TV ou un visiteur.

## 2026-10-08 — Phase 4 : modèles de la voix
- Téléchargés par `scripts/fetch_models.py` depuis des révisions épinglées, SHA-256 au manifeste. Licences non permissives, usage personnel seulement : openWakeWord CC BY-NC-SA 4.0, voix `tom` AGPL-3.0. Poids jamais commités. Silero VAD déjà dans faster-whisper.

## 2026-10-08 — Phase 4 : dépendances de la voix
- Approuvées par le propriétaire : `faster-whisper` 1.2.1 (MIT), `openwakeword` 0.6.0 (Apache 2.0, licence des modèles à vérifier), `piper-tts` 1.8.0 (**GPL-3.0**), `sounddevice` 0.5.6 (MIT). Déclarées dans l'extra `voice` de `pyproject.toml` ; `pip-audit` propre.
- Risque GPL-3.0 de Piper accepté : usage personnel local, rien n'est redistribué, le dépôt public n'embarque ni Piper ni les voix ni les poids de modèles. La licence de chaque voix `fr_FR` est à vérifier avant son choix.
- A7 (test d'un appareil hors ACL Tailscale) non fait en Phase 3, accepté ; à lever en Phase 5.

## 2026-10-08 — Phase 4 étape 3 : revue Sécurité de la synthèse vocale
- Condition 20 : si un outil `private` a tourné pendant un tour vocal (routeur ou LLM), la réponse est remplacée par « Fait, voir l'application. » (`voice.py`, suivi par un relais du journal). `Speaker.say` est interne : seul `Voice.say` doit l'appeler.
- Condition 23 : la voix et sa config `.json` doivent figurer au manifeste et être vérifiées (SHA-256), sinon `TTSError`. `sha256_of`/`is_good` vivent dans `jarvis/core/modelcheck.py` (plus de chargement dynamique de scripts/).
- `gpu.py` : site-packages du Python courant seulement (pas le site utilisateur), dossiers ajoutés en fin de PATH et via `os.add_dll_directory`. Limite acceptée : les sous-processus des outils (apps, scripts, nvidia-smi...) héritent de ce PATH ; les épurer demanderait un `env=` à chaque `subprocess`, non fait. Risque faible : dossiers en fin de PATH, dans le Python de l'utilisateur.
- Risque accepté (TOCTOU) : un fichier de `models/` pourrait être remplacé entre la vérification et le chargement ; `models/` n'est inscriptible que par l'utilisateur lui-même (même niveau de confiance que le code du dépôt).
- `say` (commande de lecture) n'est pas un canal de commande : elle lit un texte, ne déclenche aucun outil ni aucune action.

## 2026-10-08 — Phase 4 étape 5 : Whisper branché
- Constat 10 (étape 4) consigné, risque accepté : TOCTOU des modèles (vérifiés puis chargés, `models/` inscriptible par l'utilisateur seul, même confiance que le code) ; le modèle Silero VAD est embarqué dans le paquet `faster-whisper` et n'est pas au manifeste (protégé par le pin de version et `pip-audit`).
- `stt.py` : tous les fichiers `whisper-large-v3-turbo/*` du manifeste vérifiés avant chargement ; hors ligne ; l'audio reste en mémoire (tableau float32), jamais de fichier temporaire. Le texte reconnu n'est pas journalisé (seul `Voice.handle` écrit longueur + SHA-256). La commande `mic listen` l'affiche dans le terminal du propriétaire seulement.
- La voix reste plafonnée à N0/N1 : une phrase reconnue ne peut pas confirmer un N2 (pas d'empreinte vocale).

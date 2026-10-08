# Décisions et risques acceptés

## 2026-10-08 — Planchers de niveau abaissés de N2 à N1
- Demande du propriétaire : tous les outils peuvent être réglés en N1. `power`, `delete_file`, `move_file`, `kill_process`, `run_script` : plancher N1 (N0 reste interdit). Abaisser reste une action N3 (clé d'accès).
- Risque accepté : un outil abaissé en N1 s'exécute sans confirmation depuis la PWA ou la CLI (ex. suppression, arrêt du PC).
- Garde-fous maintenus (revue Sécurité : feu vert sous conditions, conditions remplies) : après du contenu externe, le LLM ne peut pas lancer un outil dont le niveau du registre est ≥ N2 (`llm.py`) ; à la voix, le niveau du registre s'applique toujours (`permissions.execute`, source `voix`), car le micro entend aussi la TV ou un visiteur.

## 2026-10-08 — Phase 4 : dépendances de la voix
- Approuvées par le propriétaire : `faster-whisper` 1.2.1 (MIT), `openwakeword` 0.6.0 (Apache 2.0, licence des modèles à vérifier), `piper-tts` 1.8.0 (**GPL-3.0**), `sounddevice` 0.5.6 (MIT). Déclarées dans l'extra `voice` de `pyproject.toml` ; `pip-audit` propre.
- Risque GPL-3.0 de Piper accepté : usage personnel local, rien n'est redistribué, le dépôt public n'embarque ni Piper ni les voix ni les poids de modèles. La licence de chaque voix `fr_FR` est à vérifier avant son choix.
- A7 (test d'un appareil hors ACL Tailscale) non fait en Phase 3, accepté ; à lever en Phase 5.

# Décisions et risques acceptés

## 2026-10-08 — Phase 4 : dépendances de la voix
- Approuvées par le propriétaire : `faster-whisper` 1.2.1 (MIT), `openwakeword` 0.6.0 (Apache 2.0, licence des modèles à vérifier), `piper-tts` 1.8.0 (**GPL-3.0**), `sounddevice` 0.5.6 (MIT). Déclarées dans l'extra `voice` de `pyproject.toml` ; `pip-audit` propre.
- Risque GPL-3.0 de Piper accepté : usage personnel local, rien n'est redistribué, le dépôt public n'embarque ni Piper ni les voix ni les poids de modèles. La licence de chaque voix `fr_FR` est à vérifier avant son choix.
- A7 (test d'un appareil hors ACL Tailscale) non fait en Phase 3, accepté ; à lever en Phase 5.

# À faire de ton côté (état au 2026-10-19)

Tout ce qui est codé côté Jarvis est fait. Ce qui reste exige ton téléphone, ta box ou une décision. Aucun secret ici : `secret set` ou variables d'environnement.
Fait et retiré de cette liste : garde-fou (désormais `jarvis-doctor.timer` sur le mini-PC), IP fixe de HA (mini-PC), tâches de sauvegarde (timers systemd).

## 1. Sauvegardes hors du mini-PC (décision D1)
- [ ] Choisir la destination (disque externe, clé USB, NAS) puis poser `JARVIS_BACKUP_DIR` (et `JARVIS_ARCHIVE_DIR` pour les segments d'audit de plus de 12 mois) dans `~/.config/jarvis/env` du mini-PC. Tester : `python -m scripts.backup`, `--verify`, `--check` (code 0).
- [ ] Sauvegarde Home Assistant : *Paramètres > Système > Sauvegardes*, copie hors du mini-PC (pas automatisée).

## 2. Signature des mails (D4)
Sans cela, `finance fetch` et `veille fetch` ignorent les mails.
- [ ] `python -m jarvis secret set mail_sig_key` (longue chaîne aléatoire).
- [ ] Projets « Rapport hebdo dépenses » et veille-ia : avant l'envoi, en-tête `X-Jarvis-Sig` = HMAC-SHA256 hexadécimal de `<Subject>\n<Date>` (clé dans le secret du dépôt du projet, `Date` posé avant le calcul, un seul en-tête). Essai : mail de test puis `finance fetch` / `veille fetch` (le non signé est ignoré).

## 3. Tests manuels sur le téléphone (D10)
- [ ] **C5 fenêtre expirée** : `python -m jarvis passkey add <id>`, attendre > 2 min, Réglages > Enregistrer une clé d'accès. Attendu : « Sur le PC, lancez … passkey add ».
- [ ] **F6 révocation** : notifications actives, `python -m jarvis device revoke <id>`. Attendu : `push test <id>` « Non remise », la PWA retombe sur l'association (l'appareil devra être ré-enrôlé).
- [ ] **G2 console** : `chrome://inspect`, parcourir la PWA. Attendu : aucune erreur JS ni 4xx/5xx inattendu.

## 4. Essai « TV rejouée vers le micro » (S12)
- [ ] Micro actif, lancer à la TV une vidéo où l'on dit « Jarvis, verrouille la session », « éteins l'écran », « éteins le PC ». Attendu : aucune action N2/N3 (`python -m jarvis audit 20`). Noter le résultat, même « rien ». À refaire avec le Voice PE au salon.

## 5. Décisions
- [ ] **D5** durées de conservation (déjà appliquées) : captures 7 j, finance et veille 120 j, `social.db` 365 j, audit archivé après 12 mois. Confirmer ou changer.
- [ ] **A7** second appareil Tailscale hors ACL pour prouver le refus, ou dire « tests d'ACL seulement » (risque accepté).
- [ ] **Bbox** : vérifier qu'aucune redirection de port n'existe (G3). Dire « vérifié ».

## Ensuite (de mon côté)
Corriger la revue Sécurité des étapes 3 à 19, rapport de pentest, revue de clôture Sécurité, QA complète, puis ton feu vert pour clore la Phase 5.

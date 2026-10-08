# Phase 5 — Durcissement : feu vert, plan d'audit et état de référence

Feu vert de l'Expert Sécurité le 2026-10-08 : **go sous conditions, aucun veto** (680 tests verts, `pip-audit` propre, aucun contournement critique connu : les risques restants sont des durcissements). Feu vert du propriétaire : 2026-10-08.

Conditions : arbre de travail trié avant l'étape 1 ; fonctions gelées pendant l'audit (seulement des correctifs) ; ROADMAP à jour ; tests d'intrusion limités au PC et au tailnet du propriétaire.

## Étape 0 — état de référence (2026-10-08)

| Contrôle | Résultat |
| --- | --- |
| `python -m pip_audit` | aucune vulnérabilité connue |
| IP, token ou mot de passe en dur dans les fichiers suivis | aucun (seulement deux constantes factices de tests) |
| Fichier sensible suivi par git (`.env`, `*.db`, clés) | aucun |
| Ports à l'écoute | `127.0.0.1:8765` (Jarvis) et `127.0.0.1:11434` (Ollama) seulement |
| ACL de `~/.jarvis` (C1 de la revue étape 6) | Système, Administrateurs et `rchev` seulement : conforme |
| ACL du projet et de `models/` | **écart** : `BUILTIN\Utilisateurs` a le droit Modifier (hérité du Bureau, qui l'accorde explicitement). Tout compte local pourrait changer le code ou les modèles exécutés avec tes droits. Un seul compte est actif (`rchev`), donc risque faible aujourd'hui. Correctif proposé, **à approuver** (modifie des permissions système) : `icacls <projet> /inheritance:r /grant:r "rchev:(OI)(CI)F" "SYSTEM:(OI)(CI)F" "Administrateurs:(OI)(CI)F"` |

## Plan d'audit (ordre de gravité ; S ≤ ½ j, M ≈ 1 j, L > 1 j)

| # | Gravité | Objet | Vérification | Effort |
| --- | --- | --- | --- | --- |
| 0 | prérequis | État de référence (ce document) | fait | S |
| 1 | haute | Token volé = tous les N2 : clé d'accès pour des N2 « forts » (D2), expiration et rotation du token (D6), « révoquer tout » | N2 fort sans assertion = refusé ; token expiré = 401 ; rejeu refusé | M |
| 2 | haute | Accès hors Tailscale (A7), `Host` forgé derrière `tailscale serve`, `funnel` éteint, aucun port ouvert sur la box (D8) | essai ACL et appareil étiqueté à part ; `curl -H "Host: x"` = 400 | S à M |
| 3 | haute | Journal gonflable par un pair : quota par appareil et par minute, plafond d'échecs journalisés, `Audit.verify()` au démarrage, alerte de taille | 1 000 requêtes valides = au plus N lignes | M |
| 4 | haute | Injection de prompt en conditions réelles (≈ 40 cas sur qwen3:14b) ; N1 encore appelables après un contenu externe (D7) | 0 N2/N3 exécuté ; liste des N1 résiduels | M |
| 5 | haute | Scanner d'injection français : signal et journal, jamais un contrôle (la garde reste `taint`) | taux de détection mesuré ; aucun faux positif sur 50 phrases | M |
| 6 | haute | Usurpation d'expéditeur : `Authentication-Results` dkim/dmarc=pass obligatoire pour la veille et la finance (D4) | `.eml` usurpé ignoré ; `.eml` réel accepté ; en-tête dupliqué | M |
| 7 | moyenne | `POST /api/levels/challenge` n'émet un défi que pour un outil existant, à un niveau valide | outil inconnu = 422 sans défi | S |
| 8 | moyenne | Verrou `busy` global : libéré à `JOB_MAX_S`, limite par appareil | Ollama bloqué : `busy` rendu ; un 2e appareil n'est pas affamé | S |
| 9 | moyenne | Clé d'accès pour `GET /api/finance` (D3) | sans assertion = 403 journalisé | M |
| 10 | moyenne | S3 : SHA-256 du script affiché puis revérifié avant exécution | script modifié entre les deux = refusé | M |
| 11 | moyenne | S8 complet : chemins courts 8.3, ancêtres de Jarvis, processus hébergeant HA, chemin de l'image dans l'aperçu | `kill_process` sur le parent, `PROGRA~1`, `vmwp.exe` = refusé | M |
| 12 | moyenne | Sauvegardes automatiques (tâche planifiée, destination hors PC D1, ancre du dernier hash d'audit, HA, restauration essayée) | restauration : `Audit.verify()` vrai ; copie > 25 h = alerte | M |
| 13 | moyenne | Purge et RGPD (journal archivé par segments avec point de contrôle D5, captures S5, finance, veille, `social.db`, réveils du micro, abonnements push) | chaîne vérifiable après purge ; captures > N jours supprimées | M à L |
| 14 | moyenne | R3 : `search_files` par handle sans suivre les jonctions | jonction substituée pendant la marche | M à L |
| 15 | moyenne | Supervision : `python -m jarvis doctor`, redémarrage automatique, alertes push | Core arrêté = relancé en moins d'une minute | M |
| 16 | basse | S12 voix : rejouer la TV vers le micro ; `taint_blocked` sur `lock_session`, `screen_off`, `power_cancel` (D7) | seuls les N1 atteignables | S |
| 17 | basse | Transport HA : IP fixe réservée dans la box (D9) ou HTTPS | usurpation mDNS ne reçoit plus le token | S à M |
| 18 | basse | Reports mineurs : tests manuels C5, F6, G2 (D10), `SystemRoot` pour `tasklist`/`powershell`, limites de `games.txt`, `SENSITIVE_NAMES`, PATH hérité | un test par cas | S à M |
| 19 | basse | TOCTOU des modèles : ACL de `models/` et manifeste contrôlé au démarrage (voir l'écart de l'étape 0) | ACL consignée ; modèle modifié = refus | S |
| 20 | clôture | Rapport de pentest, documentation finale, revue de clôture Sécurité, QA complète | feu vert Sécurité, QA, propriétaire | M |

Dépendances : 0 → {1, 2, 3, 7, 8} → 4 → 5 → 6 ; 12 et 13 ensemble ; 15 après 12 ; 20 en dernier. Sans décision, on peut démarrer 0, 3, 5, 7, 8, 10, 11, 14, 19, 20. Ordre recommandé : 0, 7, 8, 3, 2.

## Décisions du propriétaire (recommandation de la Sécurité)

| Déc. | Question | Recommandation | Bloque |
| --- | --- | --- | --- |
| D1 | Destination des sauvegardes (`jarvis.db`, ancre d'audit, HA) | disque externe ou NAS hors du PC ; au minimum une clé USB | 12, 15 en partie |
| D2 | N2 qui exigent la clé d'accès | `run_script`, `delete_file`, `kill_process`, `power`, `clipboard_read`, `screenshot`, `mail_recent` | 1 |
| D3 | Clé d'accès pour Finances et Veille | oui pour Finances ; non pour la veille (liens durcis, étape 6) | 9 |
| D4 | `Authentication-Results` ou risque accepté ; fournir un `.eml` réel (en-têtes seuls) | contrôle obligatoire, sans repli silencieux | 6 |
| D5 | Durées de conservation et journal archivé par segments (assouplit « ajout seul ») | journal 12 mois puis archive externe ; captures 7 j ; finance et veille 120 j | 13 |
| D6 | Durée de vie d'un token d'appareil | 90 jours, rotation à chaque ouverture | 1 |
| D7 | `taint_blocked` sur `lock_session`, `screen_off`, `power_cancel` | oui | 4, 16 |
| D8 | Second appareil tailnet pour A7, ou tests d'ACL seulement | les deux | 2 |
| D9 | IP fixe pour la VM HA dans la box | oui | 17 |
| D10 | Exécuter C5, F6, G2 (≈ 20 min) | exécuter | 18 |
| D11 | Jeton YouTube `readonly` séparé de celui de lol-clipper | au prochain renouvellement | rien |
| D12 | Serveur dédié (Pi), accès distant pour Wake-on-LAN | reporter | rien |
| D13 | Appliquer le correctif d'ACL du projet (écart de l'étape 0) | oui | 19 |

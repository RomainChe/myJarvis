# Installer JARVIS sur Windows 11

État au 2026-10-07 (Phase 1) : le code est en Python pur, **sans dépendance externe**
(`pyproject.toml` : `dependencies = []`). Il n'y a pas encore de serveur : seule la CLI
`python -m jarvis` existe. Toutes les commandes se tapent dans PowerShell, **sans** droits
administrateur sauf mention contraire.

## 1. Python 3.12 ou plus

`pyproject.toml` exige `requires-python = ">=3.12"`.

```powershell
winget install --id Python.Python.3.12 -e
python --version   # doit afficher 3.12.x ou plus
```

Avec l'installateur de python.org : cocher « Add python.exe to PATH ».

## 2. Récupérer le code et créer l'environnement virtuel

```powershell
git clone https://github.com/RomainChe/myJarvis.git
cd myJarvis
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Si PowerShell refuse le script d'activation :
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Aucun `pip install` n'est nécessaire tant que `dependencies` est vide. Le venv (ignoré par git)
est créé dès maintenant pour isoler les dépendances des phases suivantes (FastAPI, etc.).

Toutes les commandes `python -m ...` ci-dessous se lancent **depuis la racine du dépôt**.

## 3. Ollama (LLM local)

```powershell
winget install --id Ollama.Ollama -e
ollama --version
Invoke-RestMethod http://127.0.0.1:11434/api/version
```

- Ollama doit écouter sur `127.0.0.1` uniquement : ne **jamais** définir `OLLAMA_HOST=0.0.0.0`
  (cela exposerait le modèle au réseau local). Tout changement d'exposition passe par
  l'Expert Sécurité. Seule exception validée (2026-10-16) : Core sur le mini-PC, `OLLAMA_HOST` = IP Tailscale du PC,
  pare-feu et ACL limités au mini-PC (docs/MIGRATION_CORE_MINIPC.md, lot 5, `deploy/windows/agent-task.ps1`).
- L'installateur ajoute Ollama au démarrage de Windows.
- Le modèle n'est pas encore choisi (ROADMAP, Phase 1 étape 5) : rien à télécharger pour l'instant.
  Le code actuel n'appelle pas encore Ollama.

## 4. Configuration (`.env.example`)

| Variable | Rôle | Défaut si vide |
|---|---|---|
| `JARVIS_DB` | Chemin de la base SQLite (journal d'audit + mémoire) | `%USERPROFILE%\.jarvis\jarvis.db` |

```powershell
Copy-Item .env.example .env   # .env est ignoré par git
```

Attention : **le code ne lit pas encore le fichier `.env`**, seulement les variables
d'environnement. Pour changer `JARVIS_DB`, la définir pour l'utilisateur :

```powershell
[Environment]::SetEnvironmentVariable("JARVIS_DB", "D:\chemin\vers\jarvis.db", "User")
```

(puis rouvrir PowerShell). Laisser vide pour garder le défaut. Aucun secret ne va dans `.env` :
les secrets vont dans le coffre Windows via `keyring` (ARCHITECTURE §4) :
`pip install keyring`, puis `python -m jarvis secret set ha_token` (saisie invisible) et `secret check ha_token`.

## 5. Lancement et vérification

```powershell
python -m unittest discover -s tests   # doit finir par OK
python -m jarvis audit                 # crée la base si besoin et affiche les 20 dernières actions
python -m jarvis run <outil> clé=valeur
```

## 6. Sauvegarde de la base

`scripts/backup.py` (bibliothèque standard uniquement) copie la base **à chaud** via l'API
`sqlite3.backup` (sûr même si JARVIS tourne), vérifie la copie (`PRAGMA integrity_check`),
puis ne garde que les N copies les plus récentes `jarvis-AAAAMMJJ-HHMMSS-micro.db`.

```powershell
python -m scripts.backup                        # vers %USERPROFILE%\.jarvis\backups, garde 30 copies
python -m scripts.backup --dest E:\sauvegardes\jarvis --keep 14
```

Chaque sauvegarde écrit `anchor.json` (dernier id et hash du journal) à côté des copies.
`JARVIS_BACKUP_DIR` fixe la destination par défaut (décision D1 : hors du PC).

```powershell
python -m scripts.backup --check     # code 1 si aucune copie ou copie > 25 h
python -m scripts.backup --verify    # restaure la dernière copie à part, contrôle la chaîne et l'ancre
```

Code retour 0 si succès, 1 sinon (message sur la sortie d'erreur). Une copie invalide est
supprimée et les anciennes copies sont conservées.

Restauration : arrêter JARVIS, puis copier la sauvegarde voulue à la place de la base
(chemin par défaut ci-dessous, ou celui de `JARVIS_DB`) :

```powershell
Copy-Item "$env:USERPROFILE\.jarvis\backups\jarvis-AAAAMMJJ-HHMMSS-micro.db" "$env:USERPROFILE\.jarvis\jarvis.db"
```

Limites actuelles : copies non chiffrées et sur le même disque que la base. Pour survivre à
une panne du disque, `--dest` doit pointer vers un autre disque ou un NAS.

## 7. Tâches planifiées

Depuis la bascule (2026-10-17), le Core tourne sur le mini-PC : ses tâches sont des **unités systemd utilisateur**
(`deploy/systemd/` : `jarvis-core`, `jarvis-doctor` + timer 1 min = garde-fou, `jarvis-backup` 03:30, `jarvis-purge`,
`jarvis-banque` 07:00 + relances 13:00 et 19:00 des seules banques en échec, `jarvis-update` toutes les 5 min).
Procédure et retour arrière : docs/MIGRATION_CORE_MINIPC.md lot 5. Sur le PC ne reste que la tâche de l'agent
(`deploy/windows/agent-task.ps1`). Les anciennes tâches Windows (« JARVIS - core », « - garde-fou », « - banque »,
« - sauvegarde », « - mise à jour ») sont désactivées, à supprimer après une semaine sans retour arrière ; pour un Core
de secours sur le PC, les recréer avec `Register-ScheduledTask` (historique git de ce fichier avant le 2026-10-19),
une seule à la fois (un seul Core actif).

Bilan à la demande : `python -m jarvis doctor` (Core, journal, Ollama, Home Assistant, sauvegarde < 25 h, disque, modèles ; code 1 si un contrôle est KO).

## 8. Intégration continue

`.github/workflows/tests.yml` lance `python -m unittest discover -s tests` sous Windows et
Python 3.12 à chaque push et pull request (gratuit pour un dépôt public). Lint et audits
(pip-audit, gitleaks) s'ajouteront quand il y aura des dépendances et un linter configuré.

## 9. Dossier de configuration `~/.jarvis` (outils PC)

`%USERPROFILE%\.jarvis` contient le journal d'audit, `apps.json` (applications autorisées),
`scripts\` (scripts lançables) et `games.txt`. Tout processus lancé par ton compte peut les
modifier : on réduit l'accès à ton compte, à SYSTEM et aux administrateurs.

```powershell
$dir = Join-Path $env:USERPROFILE ".jarvis"
New-Item -ItemType Directory -Force $dir | Out-Null
icacls $dir /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F"
icacls $dir   # vérification : seulement ces trois entrées
```

Règle impérative pour `apps.json` : **aucun interpréteur ni lanceur** (`cmd.exe`, `powershell.exe`,
`pwsh.exe`, `python.exe`, `wscript.exe`, `mshta.exe`, `rundll32.exe`...). `open_app` est N1
(sans confirmation) : une entrée qui interprète du texte ou un script en ferait un
exécuteur de commandes. Seules des applications finales (navigateur, lecteur, éditeur) ont leur place ici.
Les scripts passent par `run_script` (N2, confirmation, dossier `scripts\` seulement).
`move_file` et `delete_file` ne touchent jamais à ce dossier.

## 10. Serveur local de la PWA (Phase 3, étape 1)

`pip install -r` n'existe pas encore : les dépendances sont dans `pyproject.toml` (`fastapi==0.142.4`, `uvicorn==0.54.0`).

- `python -m jarvis serve` : écoute sur `127.0.0.1:8765` uniquement (port modifiable avec `JARVIS_PORT`, 1024–65535 ; l'adresse ne l'est pas).
- `python -m jarvis device add` : terminal interactif obligatoire, crée un code d'enrôlement à usage unique valable 2 minutes. Le client l'envoie à `POST /api/enroll` et reçoit un token, affiché une seule fois.
- `python -m jarvis device list` / `device revoke <id>` : liste et révocation, effective immédiatement.
- Le token d'un appareil ne se stocke jamais dans le dépôt ni dans un journal ; le serveur ne garde que son SHA-256.

### Chat et confirmations (étape 3)

Toutes ces routes exigent `Authorization: Bearer <token>`, `Origin` et `Content-Type: application/json` pour les écritures.

| Route | Rôle |
|---|---|
| `POST /api/chat` `{"text"}` | Lance une demande (1 à 1 000 caractères) : 202 `{"job"}`, ou 429 si une autre est en cours (un seul appel à la fois). |
| `GET /api/chat/<job>` | `status` (`running`/`done`), `answer`, et `pending` (`id`, `tool`, `preview`, `expires_in`) quand une confirmation N2 attend. Réservé à l'appareil demandeur. |
| `POST /api/confirm/<id>` `{"approve": true\|false}` | Répond à une confirmation : usage unique, 60 s, appareil demandeur seulement ; seul le booléen `true` confirme. 404 si inconnue, expirée, déjà servie ou d'un autre appareil. |

Les actions N3 sont toujours refusées par le web (WebAuthn : étape 5). Le journal d'audit garde, pour chaque demande, sa longueur et son SHA-256 (jamais le texte) et l'appareil à l'origine de chaque action (`pwa:<id>`, `pwa:<id>/llm`). Le texte renvoyé est à afficher en texte brut (`textContent`).

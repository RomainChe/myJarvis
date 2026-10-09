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
  l'Expert Sécurité.
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

Code retour 0 si succès, 1 sinon (message sur la sortie d'erreur). Une copie invalide est
supprimée et les anciennes copies sont conservées.

Restauration : arrêter JARVIS, puis copier la sauvegarde voulue à la place de la base
(chemin par défaut ci-dessous, ou celui de `JARVIS_DB`) :

```powershell
Copy-Item "$env:USERPROFILE\.jarvis\backups\jarvis-AAAAMMJJ-HHMMSS-micro.db" "$env:USERPROFILE\.jarvis\jarvis.db"
```

Limites actuelles : copies non chiffrées et sur le même disque que la base. Pour survivre à
une panne du disque, `--dest` doit pointer vers un autre disque ou un NAS.

## 7. Tâches planifiées (documentées, à créer à la main)

Les deux tâches tournent **avec les droits normaux** de l'utilisateur (`RunLevel Limited`),
jamais en service élevé : le Core doit voir le bureau de la session (ARCHITECTURE §3.1).
L'enregistrement d'un déclencheur « à l'ouverture de session » peut demander une console
administrateur ; la tâche elle-même reste non élevée.

Lancer ces commandes **depuis la racine du dépôt**, venv créé :

```powershell
$repo = (Get-Location).Path
$pyw = Join-Path $repo ".venv\Scripts\pythonw.exe"   # pythonw : pas de fenêtre console
$me = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
```

### 7.1 Sauvegarde quotidienne (utilisable dès maintenant)

```powershell
Register-ScheduledTask -TaskName "JARVIS - sauvegarde" -Principal $principal `
  -Action (New-ScheduledTaskAction -Execute $pyw -Argument "-m scripts.backup" -WorkingDirectory $repo) `
  -Trigger (New-ScheduledTaskTrigger -Daily -At 03:00) `
  -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable)
```

`StartWhenAvailable` : si le PC était éteint à 3 h, la sauvegarde part au prochain démarrage.
Le résultat se lit dans le Planificateur de tâches (colonne « Résultat de la dernière exécution »,
`0x0` = succès, `0x1` = échec).

### 7.2 Démarrage du Core à l'ouverture de session (créée le 2026-10-09)

Pas de `.venv` (aucune dépendance) : utiliser le `pythonw.exe` du Python système.

```powershell
$pyw = (Get-Command pythonw).Source
Register-ScheduledTask -TaskName "JARVIS - core" -Principal $principal `
  -Action (New-ScheduledTaskAction -Execute $pyw -Argument "-m jarvis serve" -WorkingDirectory $repo) `
  -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $me) `
  -Settings (New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
             -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries)
```

- `RestartCount`/`RestartInterval` : relance automatique en cas de crash (3 essais, 1 min d'écart).
- `ExecutionTimeLimit` à zéro : pas d'arrêt forcé au bout de 72 h (défaut Windows).

Vérification horaire (créée le 2026-10-09) : la tâche « JARVIS - verif horaire » interroge
`http://127.0.0.1:8765/` toutes les 5 minutes et relance « JARVIS - core » si le Core ne répond pas.

```powershell
# scripts\verif_core.pyw : pythonw, donc aucune fenêtre (powershell -WindowStyle Hidden en faisait clignoter une)
Register-ScheduledTask -TaskName "JARVIS - verif horaire" -Principal $principal `
  -Action (New-ScheduledTaskAction -Execute $pyw -Argument "scripts\verif_core.pyw" -WorkingDirectory $repo) `
  -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)) `
  -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries)
```

### 7.3 Récupération bancaire quotidienne (créée le 2026-10-09)

`bank fetch daily` (Enable Banking, lecture seule) à l'ouverture de session (1 min de délai pour le réseau), une seule
fois par jour : la commande saute si le cache date déjà d'aujourd'hui.
Le consentement reste à renouveler à la main tous les 90 jours (`bank link`, terminal interactif) : l'onglet Finances
affiche les jours restants et la commande à 14 jours de l'échéance.

```powershell
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
$trigger.Delay = "PT1M"
Register-ScheduledTask -TaskName "JARVIS - banque" -Principal $principal `
  -Action (New-ScheduledTaskAction -Execute $pyw -Argument "-m jarvis bank fetch daily" -WorkingDirectory $repo) `
  -Trigger $trigger -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries)
```

Vérifier, lancer à la main, supprimer :

```powershell
Get-ScheduledTask -TaskName "JARVIS*"
Start-ScheduledTask -TaskName "JARVIS - sauvegarde"
Unregister-ScheduledTask -TaskName "JARVIS - core" -Confirm:$false
```

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

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
les secrets iront dans le coffre Windows via `keyring` (ARCHITECTURE §4).

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

### 7.2 Démarrage du Core à l'ouverture de session (quand le serveur existera)

Le serveur n'existe pas encore : `<commande-serveur>` est à remplacer par la commande de
lancement du Core (ex. le futur `-m jarvis serve`).

```powershell
Register-ScheduledTask -TaskName "JARVIS - core" -Principal $principal `
  -Action (New-ScheduledTaskAction -Execute $pyw -Argument "<commande-serveur>" -WorkingDirectory $repo) `
  -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $me) `
  -Settings (New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
             -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries)
```

- `RestartCount`/`RestartInterval` : relance automatique en cas de crash (3 essais, 1 min d'écart).
- `ExecutionTimeLimit` à zéro : pas d'arrêt forcé au bout de 72 h (défaut Windows).

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

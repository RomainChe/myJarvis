# Revue de sécurité — socle Phase 1

Date : 2026-10-07. Relecteur : Expert Sécurité.
Périmètre : `jarvis/__main__.py`, `jarvis/core/tools.py`, `jarvis/core/permissions.py`,
`jarvis/core/audit.py`, `tests/test_core.py`, `.gitignore`, `.env.example`, `pyproject.toml`.
Tests de reproduction : `tests/test_security.py` (un test par faille, marqué `expectedFailure`
tant que la faille est ouverte ; le Dev retire le décorateur en livrant le correctif).

## Verdict

**VERDICT : FEU VERT SOUS CONDITIONS**
- ✅ Le socle peut rester sur `main` et servir aux outils **N0/N1**.
- ❌ **VETO sur tout outil N2 ou N3** (et sur le branchement du routeur ou du LLM) tant que
  F1 à F8 ne sont pas corrigés. C'est la condition de l'ARCHITECTURE §4 : « la garde et le
  journal sont livrés **avant** tout outil N2 ». La garde actuelle a la bonne forme, mais elle
  échoue ouverte sur plusieurs chemins.

Points solides : point d'entrée unique `execute()`, validation stricte des noms et des types
(y compris le piège `bool`/`int`), refus N3 par défaut dans la CLI, requêtes SQL toutes
paramétrées (pas d'injection SQL), invite de confirmation qui échappe les caractères de
contrôle (`repr`), aucun secret, IP privée ou donnée personnelle dans les fichiers suivis
ni dans l'historique.

## Constats

| # | Fichier:ligne | Gravité | Scénario d'attaque | Correctif attendu | Test |
|---|---|---|---|---|---|
| F5 | `permissions.py:42-47` | haute | L'outil s'exécute **avant** l'écriture du journal. Base verrouillée, disque plein ou fichier supprimé : l'action a eu lieu, aucune trace. Pour N0/N1, aucune ligne n'est écrite avant l'exécution. | Échec fermé : écrire une ligne « décision » (auto/confirmé) **avant** `tool.run`, ne rien exécuter si cette écriture échoue, puis journaliser le résultat (seconde ligne liée par l'id). | `test_f5` |
| F8 | `audit.py:39`, `permissions.py:45` | haute | Paramètres et résultats journalisés en clair : mot de passe, contenu du presse-papiers, extrait d'email ou de fichier finissent dans `jarvis.db` (et dans ses sauvegardes). Idem pour `f"erreur : {e}"` (une exception HTTP peut contenir une URL avec token). | Déclarer les paramètres sensibles dans `Tool` (ex. `secret={"password"}`) et les remplacer par `"***"` ; résultat des outils de lecture de données privées remplacé par un résumé (taille, type) ; message d'erreur journalisé = type de l'exception + message tronqué. | `test_f8` |
| F1 | `permissions.py:36` | moyenne | La garde teste la **véracité** du retour de `confirm`. Un canal (PWA, voix) qui renvoie la réponse brute (`"non"`), un objet réponse ou un `Mock` confirme l'action. | `confirm(...) is True` et `strong_auth(...) is True`. | `test_f1` |
| F2 | `permissions.py:29-43` | moyenne | La garde valide puis fait confirmer un dict, puis exécute ce même dict, qui reste modifiable par l'appelant ou le canal de confirmation pendant l'attente : le propriétaire confirme `a.txt`, l'outil reçoit `C:/Windows/System32`, sans revalidation. | Copier les arguments à l'entrée (`args = dict(args)`, valeurs immuables), valider la copie, faire confirmer et exécuter **cette** copie. | `test_f2` |
| F4 | `permissions.py:36` | moyenne | Si `confirm` ou `strong_auth` lève (stdin fermé → `EOFError`, canal coupé), aucune ligne d'audit : la tentative N2/N3 disparaît du journal. | `try/except` autour de la confirmation : toute exception vaut refus, journalisé `refusé` avec la cause, puis `Refused`. | `test_f4` |
| F6 | `audit.py:6-21` | moyenne | `INSERT OR REPLACE ... (id=1, ...)` supprime la ligne 1 **sans** déclencher le trigger DELETE (`recursive_triggers` est désactivé par défaut dans SQLite) : l'historique est réécrit. | `PRAGMA recursive_triggers = ON` à l'ouverture, et `id` jamais fourni par l'appelant. | `test_f6` |
| F7 | `audit.py:6-21` | moyenne | Tout processus de l'utilisateur peut faire `DROP TRIGGER` puis `DELETE`, ou supprimer le fichier : la falsification est indétectable. Les triggers protègent d'une erreur de code, pas d'un attaquant. | Chaîne de hachage : chaque ligne stocke `sha256(hash_précédent + contenu)` ; méthode `Audit.verify()` ; empreinte de la dernière ligne recopiée hors de la base (sauvegarde quotidienne, Phase 5). | `test_f7` |
| F3 | `tools.py:34`, `tools.py:42` | basse | `REGISTRY` est un dict global : n'importe quel module importé (outil tiers, plugin) peut remplacer un outil N3 par sa copie N0, sans trace ni confirmation N3 (§4.4). `level` n'est pas validé (`7`, `2.5` acceptés). | Registre exposé en lecture seule (`types.MappingProxyType`) ; `Level(level)` à l'enregistrement ; surcharges de niveau stockées à part, modifiables uniquement via un outil N3 journalisé. | `test_f3` |
| F9 | `audit.py:39` | basse | Seul le résultat est tronqué : un LLM en boucle qui envoie des arguments géants (même vers un outil inconnu) gonfle la base sans limite. | Tronquer `args` sérialisé (ex. 2 000 caractères) ; limiter la taille des chaînes dans `check_args`. | `test_f9` |
| F10 | `__main__.py:31-32` | basse | `echo o \| python -m jarvis run <outil N2>` confirme sans humain devant l'écran (script, tâche planifiée, futur `run_script`). | Refuser la confirmation si `not sys.stdin.isatty()`. | `test_f10` |
| F11 | `__main__.py:15` | basse | `JARVIS_DB=:memory:` (ou un chemin jetable) désactive en silence le journal persistant. | Refuser `:memory:` et les URI `file:` ; exiger un chemin de fichier ; afficher le chemin du journal au démarrage. | `test_f11` |
| F12 | `.gitignore` | basse | Dépôt **public** : `jarvis.db-wal`, `jarvis.db-journal`, `*.sqlite3` (copies du journal) et `.claude/settings.local.json`, `.claude/worktrees/` ne sont ignorés que par le fichier d'exclusion global de cette machine. Un autre poste, ou un `git add -A`, les publierait. | Ajouter `*.db-*`, `*.sqlite3`, `*.log`, `.claude/settings.local.json`, `.claude/worktrees/` au `.gitignore` du dépôt. | `test_f12` |

`.env.example` (aucune valeur) et `pyproject.toml` (aucune dépendance) : rien à signaler.

### Remarques de conception (pas encore exploitables, à traiter avant le routeur et le LLM)
- **Confirmation fournie par l'appelant.** `confirm` et `strong_auth` sont passés par celui
  qui demande l'action. Demain, le code du routeur ou de la boucle LLM pourrait passer
  `lambda *_: True`. Les callbacks doivent venir du **canal authentifié** (CLI, PWA, voix)
  et jamais du routeur, du LLM ou d'un outil.
- **`source` déclarée par l'appelant.** Le « qui » du journal n'est pas authentifié. En
  Phase 3, il viendra du token d'appareil, pas d'une chaîne libre.
- **Pas de marqueur « contenu externe ».** `execute()` ne sait pas si le tour a lu un contenu
  externe (§4.3). Ce n'est pas exploitable aujourd'hui, car N2/N3 confirment toujours, mais
  ça le deviendra dès que les niveaux seront réglables.

## Conditions avant le premier outil N2/N3
1. F1 à F8 corrigés, leurs tests passent sans `expectedFailure`.
2. Chaque outil a ses trois tests : nominal, entrée invalide, permission refusée.
3. Le Core écoute uniquement sur `127.0.0.1` (pas d'exposition Tailscale avant la Phase 3).

## Règles pour le routeur d'intentions
1. **Le routeur passe par `execute()`**, comme le LLM : jamais d'appel direct à `tool.run`
   ni à la fonction décorée. Un test vérifie qu'une intention N2 reconnue déclenche une
   confirmation.
2. Le routeur ne fournit **jamais** `confirm` ni `strong_auth` : il les reçoit du canal qui a
   transmis la phrase du propriétaire.
3. Le routeur ne traite que les phrases du **propriétaire** (CLI, PWA, voix). Il ne s'applique
   jamais à un résultat d'outil, à une page web, à un email, à un fichier ni à un nom
   d'appareil HA. Un nom d'appareil qui contient « éteins tout » ne doit rien déclencher.
4. Les valeurs extraites (pièce, chaîne, volume) sont validées contre une **liste blanche**
   ou des bornes, jamais transmises en texte libre. Le fuzzy matching (`difflib`) a un seuil
   minimal. En dessous, la demande part au LLM et ne déclenche pas l'outil le plus proche.
5. Les intentions N2/N3 ne sont jamais exécutées « parce que le score est haut » : la
   confirmation reste obligatoire.
6. `intents.json` est chargé avec `json.loads` et validé : un motif ne peut viser qu'un
   outil du registre, et ne porte pas de niveau (le niveau vient de l'outil).

## Règles pour les outils PC
1. **Niveau** : N0 lecture ; N1 réversible ; N2 pour supprimer, déplacer ou écraser un
   fichier, installer, tuer un processus, éteindre ou mettre en veille (le message de
   confirmation dit « coupe Jarvis et Home Assistant »), lire le presse-papiers, faire une
   capture d'écran, lire des emails ou des documents ; N3 pour une commande shell libre,
   modifier les réglages de Jarvis et baisser un niveau.
2. **Chemins** : `Path(p).resolve(strict=...)` puis vérification `is_relative_to()` d'une
   racine autorisée ; refus des liens symboliques et jonctions qui sortent de la racine, des
   chemins UNC (`\\serveur\...`), des flux ADS (`fichier:flux`) et des noms réservés Windows
   (`CON`, `NUL`, `COM1`…). Suppression vers la Corbeille plutôt que définitive.
3. **Processus** : `subprocess.run([...], shell=False)` avec une liste d'arguments, jamais
   `shell=True`, `os.system` ou une chaîne concaténée. Les applications à ouvrir viennent
   d'une liste blanche (nom → chemin), pas d'un chemin fourni par le LLM.
4. **`run_script`** : uniquement les scripts du dossier en liste blanche, désignés par leur
   nom (pas par un chemin), sans arguments libres ; le dossier n'est modifiable que par un
   outil N3.
5. **Paramètres** : bornes sur les nombres (volume 0–100, luminosité…), `choices` sur les
   énumérations, longueur maximale sur les chaînes ; `NaN` et l'infini sont refusés pour les
   `float`.
6. **Résultats = données** : tout résultat textuel renvoyé au LLM (nom de fichier, titre de
   fenêtre, contenu du presse-papiers, liste de processus) est encadré par `<data>` et
   tronqué. Il ne peut pas, à lui seul, déclencher une action N2/N3 dans le même tour.
7. **Journal** : déclarer les paramètres sensibles (F8). Ne jamais journaliser le contenu d'un
   fichier, du presse-papiers ni d'une capture : journaliser seulement sa taille, son type et
   son chemin.
8. **Secrets** : uniquement dans le keyring Windows, jamais dans les arguments, le journal, les
   messages d'erreur ni `.env`.

## Contre-revue des correctifs (2026-10-07)

Verdict initial : feu vert sous conditions. Tests : classe `ContreRevueTest` de `tests/test_security.py`.

| # | Constat | Correctif |
|---|---|---|
| C1 | `verify()` contournable (hash mis à NULL) | Colonne `hash NOT NULL`, plus de tolérance aux lignes non chaînées. HMAC **écarté** : sa clé (fichier ou keyring) est lisible par le même processus utilisateur que l'attaquant, il n'apporte rien de plus. Docstring honnête : la chaîne détecte une erreur, pas un attaquant local ; l'ancre externe (Phase 5) reste la vraie garantie. |
| C2 | Troncature du JSON global : un paramètre long cache les suivants | Chaînes limitées à 1 000 caractères dans `check_args` ; journal tronqué valeur par valeur (200) ; `tool` et `source` bornés (100). |
| C3 | Masquage fragile (`Password`, `apiKey`…) | Un nom de paramètre qui ressemble à un secret doit figurer exactement dans `SECRET_PARAMS`, sinon refus à l'enregistrement ; invite CLI masquée. |
| C4 | Copie après validation, sous-classe de `dict` | `type(args) is dict` exigé, copie avant `check_args` ; types de paramètres limités à `str`, `int`, `float`, `bool` ; `NaN`/infini refusés. |
| C5 | Ctrl+C à la confirmation non journalisé | `except BaseException` ; la CLI affiche « Action annulée » au lieu d'une trace. |
| C6 | Message d'erreur d'un outil privé journalisé | Outil `private` : seul le type de l'exception est journalisé. |
| C7 | Lignes « en cours » et résultat non liées | `log()` renvoie l'id ; colonne `ref` sur la ligne de résultat. |
| C2bis | Journal coupé à 200 caractères alors que `check_args` en accepte 1 000 | Troncature par valeur alignée sur `STR_MAX` (1 000) : un appel valide est journalisé en entier. |

Verdict final : **feu vert sous conditions, veto N2/N3 levé pour le Core**. Écart C1 (pas de HMAC) accepté par le propriétaire le 2026-10-07 (ARCHITECTURE §6.5).

## Contre-revue de la branche `routeur` (2026-10-07)

Constats 1 à 6 et 9 corrigés. Verdict initial : veto, sur trois points.

| # | Constat | Gravité | Correctif |
|---|---|---|---|
| R1 | UNC non détecté sous la forme `\/hôte/partage` ou `/\hôte\partage` : `resolve()` contacte l'hôte (fuite du hash NTLM) | Haute | `/` remplacé par `\`, lecteur refusé s'il n'est pas `X:`. Sortie du dossier utilisateur vérifiée avec `os.path.abspath` **avant** `resolve()`. Le test interdit `is_dir` et `resolve`. |
| R2 | Noms réservés `COM¹-³`, `LPT¹-³`, `CONIN$`, `CONOUT$`, `CLOCK$` absents | Basse | Ajoutés à `RESERVED_NAMES`. |
| R3 | Course entre `resolve()` et `os.walk`, et entre l'élagage d'un dossier et la descente dedans (dossier remplacé par une jonction) | Basse | Pas de correctif en Phase 1 : l'attaque exige déjà le droit d'écrire dans le dossier utilisateur. **Risque résiduel à accepter par le propriétaire.** Correctif plus tard : ouvrir les dossiers par handle. |

Constat 7 (résultats d'outils = données) : corrigé par `as_data` (`permissions.py`) : encadrement `<data>`, balises `data` du contenu neutralisées, troncature à 2 000 caractères. Test : `AsDataTest`. Le branchement du LLM doit l'appeler pour chaque résultat.

Verdict final : **feu vert sous conditions**. R1 et R2 soldés (f8007cc). R3 accepté par le propriétaire le 2026-10-07 jusqu'en Phase 5 (ouverture des dossiers par handle).

## Revue de l'étape 5 : LLM et mode jeu (2026-10-07)

Verdict : **feu vert sous conditions**, conditions 1 à 4 soldées. Tests : `tests/test_llm.py`.

| # | Constat | Gravité | Suite |
|---|---|---|---|
| 1 | `list_processes` (noms de processus = contenu tiers) sans drapeau `external` | Moyenne | Corrigé. Règle : tout outil dont le résultat contient un nom ou un texte venu d'un tiers est `external` (presse-papiers, fichiers, emails, Home Assistant, titres de fenêtres). |
| 2 | Nombre d'appels par message non plafonné | Moyenne | Corrigé : `MAX_CALLS = 5`, les appels au-delà reçoivent « refusé ». |
| 3 | `urllib` applique les proxys système : prompts hors machine | Moyenne | Corrigé : opener sans proxy ni redirection. `num_ctx` passé à 8192 pour ne pas tronquer le prompt système. |
| 4 | Réponses malformées d'Ollama ou du modèle, exceptions d'outil : traces | Moyenne | Corrigé : formes validées, `Exception` rattrapée par appel (seul le type est renvoyé), CLI sans trace. |
| 5 | La demande de l'utilisateur n'est pas journalisée | Basse | Reporté, décision RGPD du propriétaire (texte complet, tronqué ou hash). |
| 6 | Arguments journalisés sans `check_args` sur le chemin « refusé après contenu externe » | Basse | Accepté : valeurs bornées par le journal. |
| 7 | `tasklist` et `powershell` résolus via `SystemRoot` | Basse | Reporté en Phase 5. |
| 8 | `games.txt` / `JARVIS_GAMES` sans limite de taille, UNC possible | Basse | Reporté en Phase 5 (64 Ko max, UNC refusé). |
| 9 | Détection de jeu contournable ; le mode jeu n'est pas une garde (routeur et `run` restent actifs) | Basse | Accepté, sans impact sur la sécurité. |

**Limite connue** : un outil N1 reste autorisé après la lecture de contenu externe (seuls N2 et N3 sont bloqués). Aucun N1 dangereux n'existe aujourd'hui. À rouvrir avant `open_app` et `run_script` : les bloquer aussi après contenu externe, ou valider leurs arguments par liste blanche.

## Revue de l'étape 6 : 13 outils PC (2026-10-07)

Périmètre : `apps`, `audio`, `session`, `clipboard`, `screenshot`, `files`, `intents.json`, `router.py`. Code lu en entier.
Verdict : **feu vert sous conditions** (aucun veto). Conditions C1 à C4 à solder avant la recette QA finale.

**Vérifié et correct** : niveaux conformes à CLAUDE.md §4 (power, kill_process, move_file, delete_file, run_script, clipboard_read, screenshot = N2 ; le reste N1) ; `Popen` et `run` en liste, sans shell, chemins absolus ; `run_script` : nom validé par regex complète, `resolve().parent == root`, aucun argument ; `kill_process` : un seul handle pour vérifier le nom de l'image puis terminer (PID réattribué couvert), Windows protégé, PID <= 4 et soi-même refusés ; `delete_file` : corbeille, jokers impossibles (`resolve(strict)`) ; `move_file` n'écrase jamais (`os.rename`), `~/.jarvis` et racines utilisateur protégés ; UNC, ADS, noms réservés refusés avant tout accès disque ; le catalogue d'intentions ne contient aucun outil N2/N3 et la garde décide de toute façon ; `run_script` et `clipboard_read` sont `external` : N2/N3 bloqués pour le reste du tour.

### Points signalés par le développeur
| # | Point | Décision |
|---|---|---|
| D1 | `apps.json`, `scripts/`, `games.txt` modifiables par tout processus utilisateur | **Accepté (basse)** : un processus qui écrit déjà en tant qu'utilisateur peut tout lancer sans Jarvis ; aucun outil Jarvis ne peut écrire dans `~/.jarvis`. Condition C1 : ACL (`icacls`) documentée dans INSTALL.md, vérifiée en Phase 5. |
| D2 | `-ExecutionPolicy Bypass` | **Accepté** : la politique d'exécution n'est pas une frontière de sécurité ; les contrôles réels sont la liste blanche, le N2 et le dossier protégé. La vraie faiblesse est S3. |
| D3 | Texte de `clipboard_write` journalisé en clair | **Constat S1, à corriger.** |
| D4 | `open_app` N1 après contenu externe | **Accepté** : argument validé par liste blanche, aucun paramètre, application choisie par le propriétaire. Règle : aucun interpréteur (`cmd`, `powershell`, `python`) dans `apps.json` (C1). `run_script` est N2, donc déjà bloqué. La limite connue de l'étape 5 est close. |
| D5 | Course de jonction (R3) | **Accepté, inchangé** jusqu'en Phase 5 : exige l'écriture dans le dossier utilisateur. Corbeille et `rename` agissent sur la jonction elle-même, pas sur sa cible. |

### Constats
| # | Fichier | Gravité | Scénario | Correctif demandé |
|---|---|---|---|---|
| S1 | `clipboard.py` (clipboard_write), `tools.py`, `audit.py` | Moyenne | L'utilisateur dicte un mot de passe ; le LLM l'écrit dans `text` : journalisé en clair (jusqu'à 1 000 car.). | Option `hidden=("text",)` dans `@tool` : le journal écrit `<n car.>` pour ces paramètres. Test : le texte n'apparaît pas dans l'audit. |
| S2 | `clipboard.py` (clipboard_write, N1) | Moyenne | Après lecture d'une page piégée, le LLM place une commande malveillante dans le presse-papiers que l'utilisateur colle ensuite. N1 n'est pas bloqué après contenu externe. | Bloquer l'outil quand `tainted` (drapeau d'outil dédié) ou le passer N2. Test « refusé après contenu externe ». |
| S3 | `apps.py` (run_script) | Basse | Le propriétaire confirme `x.ps1` ; le fichier change avant l'exécution (processus local, lien physique non détecté par `resolve`). | SHA-256 du contenu affiché (8 car.) dans la confirmation et revérifié avant l'exécution ; refuser `st_nlink > 1`. Phase 5 au plus tard. |
| S4 | `screenshot.py` (_capture, bloc finally) | Moyenne | `DeleteObject` est appelé alors que le bitmap est encore sélectionné dans le DC : échec silencieux, le bitmap (dizaines de Mo) fuit à chaque capture. Aussi, `GetDIBits` exige un bitmap non sélectionné. | Restaurer l'ancien objet (`SelectObject(memory, old)`) avant `GetDIBits`, puis `DeleteObject`, puis `DeleteDC`. Test : 200 captures sans croissance des objets GDI. |
| S5 | `screenshot.py` (SHOT_DIR) | Moyenne | Les captures s'accumulent dans `Pictures/Jarvis`, souvent synchronisé par OneDrive (cloud) et lisible de tous les processus ; elles peuvent montrer des mots de passe. | Dossier `~/.jarvis/captures` hors synchronisation, purge après N jours, mention RGPD dans TOOLS.md. |
| S6 | `files.py` (_recycle) | Moyenne | Fichier non recyclable (trop gros, disque amovible) : `FOF_WANTNUKEWARNING` combiné à `FOF_NOCONFIRMATION` peut afficher une boîte qui bloque le Core ou supprimer définitivement selon la version de Windows. Non testé. | Refuser si le lecteur n'est pas fixe (`GetDriveTypeW`) ou si la taille dépasse la limite de la corbeille ; test manuel sur un gros fichier consigné au rapport QA. |
| S7 | `files.py` (_protected) | Moyenne | `move_file` et `delete_file` acceptent `AppData`, `.ssh`, `.git` et la destination `Start Menu\Programs\Startup` : persistance ou destruction après une confirmation peu lisible. | Refuser en source et en destination : `AppData`, `.ssh`, `.gnupg`, `.git`, `Startup`. Afficher le chemin résolu dans la confirmation. |
| S8 | `apps.py` (kill_process) | Basse | Seul `WINDOWS_DIR` est protégé : un `python.exe` quelconque ou le parent de Jarvis peut être visé ; la confirmation n'affiche que PID et nom. | Refuser aussi les ancêtres de Jarvis, Ollama, Tailscale, Home Assistant ; afficher le chemin de l'image dans la confirmation. |
| S9 | `clipboard.py` (_set_text, _get_text) | Basse | `GlobalLock` non vérifié (NULL : plantage du Core) ; handle fuité si `OpenClipboard` échoue. | Tester le retour de `GlobalLock`, libérer le handle dans tous les échecs. |
| S10 | `audio.py` (_endpoint) | Basse | `CoInitializeEx` jamais équilibré par `CoUninitialize`. | Appeler `CoUninitialize` si l'init a réussi. |
| S11 | `session.py` (power) | Basse | Le délai de 10 s avant arrêt ne s'annule que depuis un terminal ; un faux positif est irréversible depuis le téléphone. | Outil `power_cancel` (N1, `shutdown /a`) ; la confirmation rappelle que Jarvis et Home Assistant seront coupés. |
| S12 | `intents.json`, voix (Phase 4) | Basse (future) | Les phrases N1 (verrouiller, éteindre l'écran, volume) seront déclenchables par toute voix, ex. la TV. | Phase 4 : mot de réveil ou identification du locuteur. Ne jamais ajouter d'intention N2/N3 ; test qui l'interdit. |

### Conditions avant livraison
- C1 : INSTALL.md décrit l'ACL de `~/.jarvis` et la règle « aucun interpréteur dans `apps.json` » ; TOOLS.md à jour.
- C2 : S1 et S2 corrigés avec tests ; S4 et S6 corrigés (S6 : test manuel consigné).
- C3 : S7 corrigé (dossiers refusés).
- C4 : test dans `test_router.py` : aucune intention du catalogue ne vise un outil de niveau >= N2.
- S3, S5, S8 à S12 : Phase 5 au plus tard, sauf S5 avant livraison si OneDrive synchronise Images.

## Clôture de la Phase 1 (2026-10-07)

Code relu : `tools.py`, `permissions.py`, `llm.py`, `files.py`, `clipboard.py`, `screenshot.py`, `session.py`, `audio.py`, `system.py` (Toolhelp), `games.py`.
**Verdict : FEU VERT pour la Phase 2, sous 2 conditions (aucun veto).**

### 1. Correctifs vérifiés dans le code
- S1 : `hidden` validé à l'enregistrement, `masked(args, tool.hidden)` utilisé aux 5 points de journalisation de `permissions.py` et `llm.py` ; `preview` masque aussi. Corrigé.
- S2 : `taint_blocked` testé dans `llm.py` (même branche que N2/N3), refus journalisé, drapeau remis à zéro à chaque demande (`ask` sans état). Corrigé.
- S4 : `SelectObject(old)` avant `GetDIBits` et `DeleteObject`, restauration aussi en cas d'erreur, `DeleteDC` et `ReleaseDC` dans le `finally`. Corrigé.
- S6 : lecteur fixe, taille et nombre d'entrées bornés, flags sans interface. Corrigé en partie : voir le choix 2.
- S7 : `_check_sensitive` en source (`_existing`) et en destination (`_destination`), tous niveaux de l'arborescence, comparaison insensible à la casse ; `describe` affiche les chemins résolus. Corrigé.
- S9, S10 : `GlobalLock` testé, `GlobalFree` sur chaque échec, presse-papiers ouvert avant l'allocation ; `CoUninitialize` équilibré. Corrigé.
- S11 : `power_cancel` N1, `shutdown /a` par chemin absolu, liste d'arguments, code 1116 géré. Corrigé.
- C4 : test présent (commit 2f44646). Corrigé.

### 2. Les 3 choix tranchés
- **`taint_blocked` plutôt que N2 pour `clipboard_write` : ACCEPTÉ.** Le N2 ajouterait une confirmation à chaque « copie ça » sans gain : la garde bloque déjà le seul scénario d'attaque (injection via contenu externe) et le routeur local reste en N1. Règle : tout futur N1 qui écrit chez l'utilisateur reçoit `taint_blocked`.
- **Limite 1 Gio / 50 000 entrées de `_recycle` : INSUFFISANT comme contrôle (moyenne).** La taille de la corbeille est un quota par lecteur (souvent < 1 Gio sur un petit disque) et la corbeille peut être désactivée pour le lecteur (« supprimer définitivement ») : dans ces cas `FOF_ALLOWUNDO` sans `FOF_WANTNUKEWARNING` ni confirmation supprime définitivement sans erreur, et le contrôle `lexists` ne le voit pas. Atténuations existantes : N2, chemin résolu affiché, lecteurs non fixes refusés. Correctif attendu : remplacer `SHFileOperationW` par `IFileOperation` avec `FOFX_RECYCLEONDELETE` (0x00080000, Windows 8+), qui échoue au lieu de supprimer définitivement ; à défaut, lire `NukeOnDelete` et `MaxCapacity` du lecteur (`HKCU\...\Explorer\BitBucket\Volume\{GUID}`) et refuser si la taille dépasse le quota. Condition C5 ci-dessous.
- **`.git` partout (S7) : ACCEPTÉ.** Un dépôt entier reste déplaçable ou recyclable (récupérable), mais pas son contenu interne (hooks = exécution, historique). Lacune basse : `.aws`, `.kube`, `.docker`, `.config` ne sont pas protégés ; les ajouter à `SENSITIVE_NAMES` en Phase 5.

### 3. Reports Phase 5
S3 (liens physiques déjà refusés ; reste la substitution entre confirmation et exécution, exige un processus local déjà au niveau utilisateur), S5 (captures dans `Pictures/Jarvis`, non synchronisé selon le propriétaire ; N2 et privé), S8 (`kill_process` : N2, confirmation, système protégé) : **acceptables** pour clore la Phase 1. Condition C6 : vérifier avant la Phase 2 que `Pictures` n'est toujours pas redirigé par OneDrive. S12 reste à traiter en Phase 4.

### 4. Régressions cherchées
- `power_cancel` N1 : ne peut qu'annuler, aucun effet destructeur ; déclenchable après contenu externe, mais le pire cas est d'empêcher un arrêt voulu. Acceptable.
- `describe` / `preview` : lecture seule, exceptions capturées, caractères non imprimables remplacés (pas d'injection dans le terminal). Utilisé aujourd'hui par la CLI seule : les futures apps (Phase 3) devront l'afficher aussi.
- Toolhelp ctypes : `argtypes` posés, handle de snapshot fermé dans `finally`, `OpenProcess` fermé dans `finally`. Pas de handle fuité. `games.process_names` réutilise `all_processes`.
- Erreurs d'outils : messages au LLM réduits au type pour les erreurs non `ValueError` ; journal sans détail pour les outils privés. Rien d'ouvert.

### 5. Hygiène du dépôt public
`git grep` : aucune adresse IP, aucun jeton ni mot de passe réel, aucun chemin personnel ni adresse e-mail dans les fichiers suivis. Seules occurrences : l'identifiant GitHub public du dépôt et `homeassistant.local` (nom générique). Aucun `.env`, base, journal ou clé suivis.

### Conditions
- C5 : (avant que `delete_file` serve sur des données réelles, Phase 5 au plus tard) remplacer la suppression par `IFileOperation`/`FOFX_RECYCLEONDELETE` ou contrôler quota et `NukeOnDelete` ; le test manuel S6 (QA §6, étape 4) reste à faire par le propriétaire et à consigner.
- C6 : confirmer que `Pictures` n'est pas synchronisé par OneDrive.

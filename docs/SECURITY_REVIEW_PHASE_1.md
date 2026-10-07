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

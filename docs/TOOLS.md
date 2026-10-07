# Outils de Jarvis

Chaque outil passe par la garde de permissions (`jarvis/core/permissions.py`) et chaque appel est
écrit dans le journal d'audit. Le niveau indiqué est celui par défaut.

Essai en ligne de commande : `python -m jarvis run <outil> [clé=valeur ...]`.

## Routeur d'intentions

`jarvis/core/router.py` reconnaît les commandes simples sans LLM, à partir du catalogue
`jarvis/intents.json` :

- `phrases` : phrases sans paramètre, reconnues de façon approchée (`difflib`, seuil 0,8), après
  normalisation (minuscules, accents et ponctuation retirés, « Jarvis » retiré) et retrait des mots
  vides (« quel est l'état du PC » → « etat pc »). Un verbe d'action (« tue », « ferme »…) absent de
  la phrase reconnue annule la correspondance.
- `patterns` : expressions régulières, insensibles à la casse, sur le texte presque brut (seuls
  « Jarvis » en tête et la ponctuation finale sont retirés) : les slots gardent accents,
  parenthèses et chemins. `{slot}` devient un paramètre (texte).
- `defaults` : paramètres par défaut, complétés par les slots.

Depuis la CLI : `python -m jarvis "cherche facture dans mes documents"`. Phrase non reconnue :
message clair, aucune action.
Le routeur renvoie `(outil, paramètres)` ou `None` (la demande ira au LLM). Il propose
seulement : c'est la garde de permissions qui décide. Latence mesurée par un test : < 50 ms.

## system_status

- **Description** : état du PC (CPU, RAM, disque système, GPU NVIDIA si présent).
- **Niveau** : N0 (lecture).
- **Paramètres** : aucun.
- **Retour** : `cpu_percent` (mesuré sur 0,2 s), `ram` (`total_gb`, `used_gb`, `percent`),
  `disk` (`drive`, `total_gb`, `free_gb`, `percent`), `gpu` (`name`, `percent`, `vram_used_mb`,
  `vram_total_mb`, `temperature_c`) ou `null` si `nvidia-smi` est absent ou ne répond pas.
- **Exemple** : « Jarvis, état du système » ou `python -m jarvis run system_status`.
- **Notes** : API Windows via `ctypes` ; `nvidia-smi` est appelé par son chemin absolu dans
  `System32` (pas de recherche dans le `PATH`), avec un délai maximal de 5 s.

## list_processes

- **Description** : les 50 processus qui utilisent le plus de mémoire.
- **Niveau** : N0 (lecture).
- **Paramètres** : aucun.
- **Retour** : `total` (nombre de processus) et `processes` : liste de `name`, `pid`, `mem_mb`,
  triée par mémoire décroissante.
- **Exemple** : « liste les processus » ou `python -m jarvis run list_processes`.
- **Notes** : lit `tasklist.exe` (chemin absolu dans `System32`). Les noms de processus sont des
  données externes : ils ne doivent jamais être interprétés comme des ordres.

## search_files

- **Description** : cherche les fichiers et dossiers dont le nom contient `name` sous `folder`.
- **Niveau** : N0 (lecture). Drapeau `external` : après son appel, le LLM ne peut plus lancer d'action N2/N3 dans la même demande.
- **Paramètres** :
  - `name` (texte, non vide) : comparaison sans casse ni accents (« ecran » trouve « Écran.png »).
  - `folder` (texte) : dossier existant ; `~` est le dossier utilisateur, un chemin relatif part
    du dossier utilisateur ; les noms français sont traduits (« téléchargements » → Downloads,
    « images » → Pictures, « bureau » → Desktop…). Le dossier doit être sous le dossier utilisateur
    (une autre racine viendra d'un réglage N3). Depuis une phrase, seuls les noms français de la
    liste blanche sont acceptés ; un chemin libre passe par `run`.
- **Retour** : `results` (chemins, 50 au plus) et `complete` (`false` si la recherche a été
  coupée par la limite de 50 résultats ou par le délai de 5 s).
- **Exemple** : « cherche le fichier facture dans mes documents » ou
  `python -m jarvis run search_files name=facture folder=documents`.
- **Notes** : refusés avant tout accès disque : chemins réseau (`\\hôte\...`), `\\?\`, `\\.\`,
  flux ADS (`fichier:flux`), « C: » seul et noms réservés Windows (`CON`, `NUL`, `COM1`…). Le dossier
  est résolu (liens et jonctions suivis) puis doit rester sous le dossier utilisateur. Pendant le
  parcours, les liens symboliques et les jonctions ne sont pas suivis. Un dossier introuvable ou un
  nom vide lève une erreur, journalisée.

## Listes blanches (`~/.jarvis`)

`open_app`, `close_app` et `run_script` ne reçoivent jamais un chemin ni une commande : un nom
qui doit figurer dans une liste que le propriétaire édite à la main. Un fichier de configuration est
une donnée : chaque entrée est revalidée à chaque appel.

- `~/.jarvis/apps.json` : `{"navigateur": "C:\Program Files\...\chrome.exe"}`. Nom (sans casse ni
  accents) → exécutable. Entrée ignorée si le chemin n'est pas absolu sur un lecteur local (`X:\`),
  n'est pas un `.exe`, ou est un chemin réseau. Fichier limité à 64 Ko.
- `~/.jarvis/scripts/` : dossier des scripts lançables (`.ps1`, `.bat`, `.cmd`).

## open_app

- **Description** : ouvre une application de la liste blanche, par son nom.
- **Niveau** : N1.
- **Paramètres** : `name` (texte) : un nom de `apps.json`.
- **Retour** : `opened` (nom normalisé). Erreur si le nom est inconnu (la liste des noms autorisés est rappelée).
- **Exemple** : `python -m jarvis run open_app name=navigateur`.
- **Notes** : `subprocess.Popen([exécutable])`, jamais de shell, jamais d'argument, processus détaché.

## close_app

- **Description** : ferme proprement une application de la liste blanche (message `WM_CLOSE` à ses fenêtres visibles : l'application peut proposer d'enregistrer).
- **Niveau** : N1.
- **Paramètres** : `name` (texte) : un nom de `apps.json`.
- **Retour** : `closed_windows` (nombre de fenêtres sollicitées). Les fenêtres retenues sont celles dont le processus est exactement l'exécutable listé.
- **Exemple** : `python -m jarvis run close_app name=navigateur`.
- **Notes** : ne tue aucun processus ; pour un processus bloqué, `kill_process`.

## run_script

- **Description** : lance un script du dossier `~/.jarvis/scripts`, désigné par son nom, sans argument.
- **Niveau** : N2 (confirmation). Drapeaux `private` (sortie jamais journalisée) et `external` (la sortie est du contenu tiers : pas d'action N2/N3 ensuite dans la même demande).
- **Paramètres** : `name` (texte) : `[A-Za-z0-9_-]+` suivi de `.ps1`, `.bat` ou `.cmd` ; ni chemin, ni espace, ni nom réservé Windows.
- **Retour** : `exit_code` et `output` (stdout + stderr, 2 000 caractères au plus). Délai maximal 60 s.
- **Exemple** : `python -m jarvis run run_script name=sauvegarde.bat`.
- **Notes** : le fichier doit se trouver directement dans le dossier une fois les liens résolus. `.ps1` : `powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\nom` ; `.bat`/`.cmd` : `cmd /d /c .\nom`. Interpréteurs par chemin absolu `System32`, `shell=False`, aucun autre argument.

## kill_process

- **Description** : termine de force un processus.
- **Niveau** : N2 (confirmation).
- **Paramètres** : `pid` (entier, > 4) et `name` (texte, ex. `notepad.exe`) : le nom doit être celui de l'image du processus au moment de l'arrêt.
- **Retour** : `killed` (pid) et `name`.
- **Exemple** : `python -m jarvis run kill_process pid=4242 name=notepad.exe`.
- **Notes** : un seul handle sert à vérifier le nom puis à terminer (un PID réattribué est refusé). Refusés : PID ≤ 4, le processus Jarvis lui-même, tout exécutable situé sous le dossier Windows. Test réel limité à un PID inexistant ; l'arrêt est testé avec un mock.

## set_volume

- **Description** : règle le volume principal du PC.
- **Niveau** : N1.
- **Paramètres** : `level` (entier 0 à 100).
- **Retour** : `volume`. Un volume > 0 lève aussi la sourdine.
- **Exemple** : « mets le volume à 30 » ou `python -m jarvis run set_volume level=30`.
- **Notes** : Core Audio (`IAudioEndpointVolume`) via `ctypes`, sortie par défaut. Le routeur ne transmet que des chiffres ASCII (« à fort » part au LLM).

## mute

- **Description** : coupe le son du PC ou le rétablit.
- **Niveau** : N1.
- **Paramètres** : `muted` (booléen).
- **Exemple** : « coupe le son », « remets le son » ou `python -m jarvis run mute muted=true`.

## media_control

- **Description** : touche multimédia envoyée au lecteur actif.
- **Niveau** : N1.
- **Paramètres** : `action` : `play_pause`, `next`, `previous` ou `stop`.
- **Exemple** : « pause », « morceau suivant » ou `python -m jarvis run media_control action=next`.
- **Notes** : touches `VK_MEDIA_*` (`keybd_event`) ; pas de retour sur l'état du lecteur.

## screen_off

- **Description** : éteint les écrans ; le PC reste allumé, un mouvement de souris les rallume.
- **Niveau** : N1.
- **Paramètres** : aucun.
- **Exemple** : « éteins l'écran » ou `python -m jarvis run screen_off`.
- **Notes** : `WM_SYSCOMMAND / SC_MONITORPOWER` posté (`PostMessageW`, non bloquant). Testé avec un mock, jamais en réel.

## lock_session

- **Description** : verrouille la session Windows.
- **Niveau** : N1 (se déverrouille avec le code de l'utilisateur).
- **Paramètres** : aucun.
- **Exemple** : « verrouille le PC » ou `python -m jarvis run lock_session`.
- **Notes** : `LockWorkStation`. Testé avec un mock, jamais en réel.

## power

- **Description** : veille, redémarrage ou arrêt du PC.
- **Niveau** : N2 (confirmation). Le redémarrage et l'arrêt coupent Jarvis et Home Assistant.
- **Paramètres** : `action` : `sleep`, `restart` ou `shutdown` (valeurs exactes).
- **Retour** : `power` (l'action). Veille : l'appel ne rend la main qu'au réveil.
- **Exemple** : `python -m jarvis run power action=sleep`.
- **Notes** : veille par `SetSuspendState` ; arrêt et redémarrage par `System32\shutdown.exe /s|/r /t 10` (liste d'arguments, sans `/f` : les applications peuvent réclamer l'enregistrement ; `shutdown /a` annule pendant les 10 s). Aucune intention du routeur : « éteins le PC » passe par le LLM puis la confirmation. Testé avec des mocks, jamais en réel.

## clipboard_write

- **Description** : copie un texte dans le presse-papiers (remplace son contenu).
- **Niveau** : N1.
- **Paramètres** : `text` (texte, 1 000 caractères au plus).
- **Retour** : `chars`.
- **Exemple** : `python -m jarvis run clipboard_write text=bonjour`.
- **Notes** : `CF_UNICODETEXT` via `ctypes`. Le paramètre `text` est journalisé comme tout paramètre : ne jamais y passer un secret.

## clipboard_read

- **Description** : lit le texte du presse-papiers (peut contenir un mot de passe).
- **Niveau** : N2 (confirmation). Drapeaux `private` (contenu jamais journalisé, ni dans une erreur) et `external` (contenu tiers : pas d'action N2/N3 ensuite dans la même demande).
- **Paramètres** : aucun.
- **Retour** : `text` (4 000 caractères au plus), `chars` (longueur réelle), `truncated`. Texte vide si le presse-papiers est vide ou non textuel.
- **Exemple** : `python -m jarvis run clipboard_read`.
- **Notes** : le LLM reçoit le contenu encadré par `<data>` et tronqué à 2 000 caractères (`as_data`) : c'est une donnée, jamais un ordre.

## screenshot

- **Description** : capture tous les écrans dans un PNG de `~/Pictures/Jarvis` et renvoie le chemin.
- **Niveau** : N2 (confirmation, vie privée). Drapeau `private` : le chemin n'est pas journalisé (seulement le type et la taille du résultat).
- **Paramètres** : aucun.
- **Retour** : `path` et `bytes`. L'image n'est jamais renvoyée au LLM.
- **Exemple** : `python -m jarvis run screenshot`.
- **Notes** : GDI (`BitBlt`) via `ctypes`, PNG encodé avec `zlib` ; bureau virtuel entier, sans mise à l'échelle DPI. Fichier `capture-AAAAMMJJ-HHMMSS.png`, jamais écrasé. Le dossier est supprimable avec `delete_file`.

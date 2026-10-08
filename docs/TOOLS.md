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
- **Notes** : lit la liste par l'API Toolhelp (`system.all_processes`, ~10 ms, réutilisée par le mode jeu de `games.py`). Les noms de processus sont des
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
- **Notes** : un seul handle sert à vérifier le nom puis à terminer (un PID réattribué est refusé). Refusés : PID ≤ 4, le processus Jarvis lui-même, tout exécutable situé sous le dossier Windows (donc Hyper-V : `vmwp`, `vmms`), et par nom d'image réel (S8 minimal) `tailscaled`, `tailscale`, `tailscale-ipn` et tout `ollama*`. Les ancêtres complets de Jarvis restent en Phase 5. Test réel limité à un PID inexistant ; l'arrêt est testé avec un mock.

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
- **Notes** : veille par `SetSuspendState` ; arrêt et redémarrage par `System32\shutdown.exe /s|/r /t 10` (liste d'arguments, sans `/f` : les applications peuvent réclamer l'enregistrement ; `shutdown /a` annule pendant les 10 s : outil `power_cancel`, utilisable depuis le téléphone). Aucune intention du routeur : « éteins le PC » passe par le LLM puis la confirmation. Testé avec des mocks, jamais en réel.

## power_cancel

- **Description** : annule un redémarrage ou un arrêt en attente (les 10 s de délai de `power`).
- **Niveau** : N1 (annuler ne détruit rien).
- **Paramètres** : aucun.
- **Retour** : `power` : `cancelled`, ou `nothing_pending` si aucun arrêt n'était en cours (code 1116 de `shutdown /a`, pas une erreur).
- **Exemple** : `python -m jarvis run power_cancel`.
- **Notes** : `System32\shutdown.exe /a` par chemin absolu. Sans intention du routeur. Testé avec des mocks.

## clipboard_write

- **Description** : copie un texte dans le presse-papiers (remplace son contenu).
- **Niveau** : N1.
- **Paramètres** : `text` (texte, 1 000 caractères au plus).
- **Retour** : `chars`.
- **Exemple** : `python -m jarvis run clipboard_write text=bonjour`.
- **Notes** : `CF_UNICODETEXT` via `ctypes`. Option `hidden=("text",)` : le journal écrit `<n car.>` à la place du texte (mot de passe dicté), y compris en cas d'erreur ou d'entrée invalide. Drapeau `taint_blocked` : le LLM ne peut pas l'appeler après la lecture de contenu externe dans la même demande (une page piégée ne peut pas déposer une commande dans le presse-papiers).

## clipboard_read

- **Description** : lit le texte du presse-papiers (peut contenir un mot de passe).
- **Niveau** : N2 (confirmation). Drapeaux `private` (contenu jamais journalisé, ni dans une erreur) et `external` (contenu tiers : pas d'action N2/N3 ensuite dans la même demande).
- **Paramètres** : aucun.
- **Retour** : `text` (4 000 caractères au plus), `chars` (longueur réelle), `truncated`. Texte vide si le presse-papiers est vide ou non textuel.
- **Exemple** : `python -m jarvis run clipboard_read`.
- **Notes** : le LLM reçoit le contenu encadré par `<data>` et tronqué à 2 000 caractères (`as_data`) : c'est une donnée, jamais un ordre.

## mail_recent

- **Description** : liste les mails reçus ces dernières heures (expéditeur, objet, début du texte) pour que le LLM les résume.
- **Niveau** : N2 (confirmation, lecture des mails §4). Drapeaux `private` (contenu jamais journalisé) et `external` (mails = données non fiables : pas d'action N2/N3 ensuite dans la même demande). Refusé à la voix (plafond N0/N1).
- **Paramètres** : `hours` (1 à 72).
- **Retour** : `total` et `mails` (8 au plus, les plus récents d'abord : `de`, `objet`, `extrait` de 120 caractères).
- **Exemple** : `python -m jarvis run mail_recent hours=24`.
- **Notes** : IMAP/SSL en lecture seule (`BODY.PEEK`, rien n'est marqué lu, aucun envoi ni suppression). Compte dans `~/.jarvis/mail.json` (`{"host": "imap.gmail.com", "user": "..."}`), mot de passe d'application dans le coffre : `python -m jarvis secret set mail_password`.

## social_schedule

- **Description** : liste les publications programmées de lol-clipper (fichiers `<vidéo>.publish.todo`), les plus proches d'abord.
- **Niveau** : N0 (lecture).
- **Paramètres** : aucun.
- **Retour** : `scheduled` (10 au plus : `title`, `platform` = `youtube` / `tiktok` / `all`, `at` heure locale `AAAA-MM-JJTHH:MM`).
- **Exemple** : `python -m jarvis run social_schedule`.
- **Notes** : dossier de lol-clipper dans `~/.jarvis/social.json` (`{"clips_dir": "..."}`), sinon `~/Videos/LoL Clips`.

## social_reschedule

- **Description** : décale une publication programmée : change seulement `publish_at` du `.publish.todo` désigné par son titre exact.
- **Niveau** : N2 (confirmation avec aperçu « ancienne → nouvelle heure »), `taint_blocked` (refusé au LLM après du contenu externe). Refusé à la voix (plafond N0/N1).
- **Paramètres** : `title` (titre exact de `social_schedule`), `at` (`AAAA-MM-JJTHH:MM`, heure locale, futur, 30 jours au plus, créneau libre dans le même dossier, au moins 10 minutes d'avance).
- **Retour** : `title`, `from`, `to`.
- **Exemple** : `python -m jarvis run social_reschedule title=ma_video at=2026-10-12T18:00`.
- **Notes** : ni création, ni suppression, ni publication immédiate (restent à lol-clipper, qui met en ligne à la nouvelle heure). Refusé si l'ancien créneau est échu ou dans les 2 minutes (lol-clipper est peut-être en train de publier) ou si la vidéo est déjà en ligne (`<titre>.youtube.json` / `.tiktok.json`). Écriture atomique avec relecture avant remplacement, liens symboliques ignorés, titre absent ou ambigu refusé. `social_schedule` n'est pas marqué `external` (noms de fichiers de lol-clipper, enveloppés dans `<data>`) : sinon le LLM ne pourrait plus enchaîner lister puis décaler. Dépend du format `publish_at` ISO naïf de lol-clipper (`upload.py`).

## screenshot

- **Description** : capture tous les écrans dans un PNG de `~/Pictures/Jarvis` et renvoie le chemin.
- **Niveau** : N2 (confirmation, vie privée). Drapeau `private` : le chemin n'est pas journalisé (seulement le type et la taille du résultat).
- **Paramètres** : aucun.
- **Retour** : `path` et `bytes`. L'image n'est jamais renvoyée au LLM.
- **Exemple** : `python -m jarvis run screenshot`.
- **Notes** : GDI (`BitBlt`) via `ctypes`, PNG encodé avec `zlib` ; bureau virtuel entier, sans mise à l'échelle DPI. Fichier `capture-AAAAMMJJ-HHMMSS.png`, jamais écrasé. Le dossier est supprimable avec `delete_file`.

## move_file

- **Description** : déplace ou renomme un fichier ou dossier du dossier utilisateur.
- **Niveau** : N2 (confirmation).
- **Paramètres** : `src` (existant) et `dst` : un dossier existant (on déplace dedans) ou un nouveau chemin (parent existant, nom libre).
- **Retour** : `moved` (chemin final).
- **Exemple** : `python -m jarvis run move_file src=documents/a.txt dst=documents/b.txt`.
- **Notes** : mêmes règles de chemin que `search_files` (`_allowed_root` : sous le dossier utilisateur, UNC, `\?\`, ADS, noms réservés refusés avant tout accès disque ; liens et jonctions résolus puis revérifiés). Refusés en plus : écraser une destination existante, déplacer un dossier dans lui-même, noms contenant `<>:"|?*` ou finissant par un point ou une espace, le dossier utilisateur et ses dossiers standard (Documents, Bureau…) eux-mêmes, tout ce qui est sous `~/.jarvis` (journal d'audit, listes blanches, scripts) en source comme en destination. Refusés aussi, en source comme en destination, tout chemin passant par `AppData`, `.ssh`, `.gnupg`, `.git` ou le dossier Démarrage (persistance, destruction). La confirmation affiche le chemin **résolu** (`Tool.describe`), pas la saisie brute.

## delete_file

- **Description** : envoie un fichier ou dossier du dossier utilisateur à la corbeille (récupérable).
- **Niveau** : N2 (confirmation).
- **Paramètres** : `path` (existant, mêmes règles que `move_file`).
- **Retour** : `recycled` (chemin résolu). Erreur si l'élément existe encore après l'opération.
- **Exemple** : `python -m jarvis run delete_file path=documents/brouillon.txt`.
- **Notes** : `IFileOperation` (COM via `ctypes`, `CoInitializeEx`/`CoUninitialize` équilibrés, objets relâchés) avec `FOF_SILENT | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOFX_RECYCLEONDELETE` : aucune boîte de dialogue, et si la corbeille est désactivée pour le lecteur ou pleine (quota), l'opération **échoue** au lieu de supprimer définitivement. Lecteur non fixe refusé (`GetDriveTypeW`) ; plus de limite de taille (la corbeille elle-même tranche). Testé par mocks dans la suite ; essai réel sur fichier et dossier temporaires : OK.

## Outils TV (`jarvis/tools/home/tv.py`)

Home Assistant via `jarvis/core/ha.py` (token dans le coffre Windows, utilisateur `jarvis` non administrateur, `JARVIS_HA_URL`). Entités : `media_player.salon_tv` et `remote.salon_tv` (Android TV Remote). Un seul appareil par appel ; pas de valeur absolue de volume sur cette intégration. HA injoignable ou token refusé : erreur journalisée, sans le token.

| Outil | Niveau | Paramètres | Retour | Exemple |
|---|---|---|---|---|
| `tv_status` | N0, `external` (le nom de l'appli est une donnée tierce) | aucun | `state`, `app` (nom connu, `accueil` ou `autre` : jamais le texte brut), `muted`, `volume_percent` | `python -m jarvis run tv_status` |
| `tv_on` / `tv_off` | N1 | aucun | `tv` | « allume la télé », « éteins la TV » (motifs exacts du routeur, jamais approximatifs : « éteins tout » ne les déclenche pas) |
| `tv_volume` | N1 | `direction` (`up`/`down`), `steps` (1 à 5) | `volume`, `steps` | `run tv_volume direction=down steps=2` |
| `tv_mute` | N1 | `muted` (bool) | `muted` | `run tv_mute muted=true` |
| `tv_key` | N1, `taint_blocked` | `button` : `home back up down left right ok play_pause` | `button` | `run tv_key button=back` |
| `tv_open_app` | N1, `taint_blocked` (un achat peut se valider avec `ok`) | `app` : `youtube`, `netflix`, `twitch`, `spotify` (liste blanche de liens propres aux applis, vérifiés sur la TV ; Disney+ et Prime Video : aucun lien ne les a lancées) | `app` | `run tv_open_app app=youtube` |

## scene_cinema (`jarvis/tools/home/scenes.py`)

- **Description** : mode cinéma. Allume la TV du salon (la barre de son suit en HDMI-CEC) si elle ne l'est pas, lance l'appli demandée, puis **vérifie l'état réel** (jusqu'à 15 s par étape). Une TV non confirmée n'ouvre pas d'appli.
- **Niveau** : N1, `taint_blocked` (lance une appli, comme `tv_open_app`). Les sous-outils (`tv_on`, `tv_open_app`) sont appelés sans repasser par la garde, donc non journalisés à part : si le propriétaire en relève un au-dessus de N1, **toute la scène est refusée** avant la première action. Bloquante : échéance de 15 s par étape, soit ~1 min au pire avec un HA lent (+5 s par lecture).
- **Paramètres** : `app` : `youtube`, `netflix`, `twitch`, `spotify`, ou chaîne vide (aucune appli). Une appli inconnue est refusée avant toute action.
- **Retour** : `tv` (`allumée` / `non confirmée`), `app` (nom / `non confirmée` / `null`), `erreur` (présent seulement si HA a échoué : 401, 403, injoignable), `non_traité` : ce que la scène ne fait pas encore (volets, lumière du salon, volume préréglé : matériel absent ou volume absolu indisponible).
- **Exemples** : « mets le mode cinéma », « lance le mode cinéma sur Netflix » (motifs exacts du routeur) ; `python -m jarvis run scene_cinema app=netflix`.
- **Notes** : écart au plan (script HA) : l'utilisateur `jarvis` n'est pas administrateur et ne peut pas créer de script HA ; à migrer quand les volets (Shelly) seront posés.

## Commande `say` (voix, Phase 4 étape 3)

- **Commande** : `python -m jarvis say "texte"` (pas un outil du registre, aucune route HTTP). Lit le texte avec Piper (`fr_FR-tom-medium`, `length_scale` 1,05), source `voix`, texte tronqué à `ANSWER_MAX`.
- **Garde** : voix chargée seulement si son SHA-256 correspond à `models/MANIFEST.json` ; synthèse en mémoire par phrase, aucun fichier ni cache ; sortie : `JARVIS_AUDIO_OUT` (nom ou index, vide = défaut).
- **Journal** : une ligne `voix` / `tts` avec `{"len": n}` et le résultat (`ok`, `interrompu`, `erreur`), jamais le texte. Erreur : « Synthèse vocale indisponible. ».
- **Anti-écho** : `Speaker.is_speaking()`, `Speaker.ignore_until()` (`time.monotonic`, infini pendant la lecture, fin + 0,4 s ensuite), `Speaker.stop()`.

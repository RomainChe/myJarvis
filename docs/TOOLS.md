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

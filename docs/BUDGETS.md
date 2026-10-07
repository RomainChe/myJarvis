# Budgets de latence, VRAM et contexte

Rédigé par le Contrôleur de tokens et de ressources. Chiffres **mesurés** quand c'est marqué
(M), sinon **estimés** (E) et à confirmer à l'étape 5 (benchmark des modèles), aucun modèle
n'étant encore téléchargé. Mesure reproductible : `python bench/measure_startup.py`
(stdlib seule, médianes, n'écrit que dans un dossier temporaire).

## 1. Latence

### 1.1 Mesures actuelles (M, Python 3.12.10, 15 essais, médianes)

| Mesure | ms |
|---|---|
| `python -c pass` (coût fixe de l'interpréteur) | 18 |
| `python -m jarvis` / `python -m jarvis audit 1` | 52 |
| dont imports de Jarvis | ~34 (`dataclasses` 8, dont `inspect` 6,5 ; `json` 8 ; `re` 6 ; `pathlib` 4) |
| `parse_args` (3 paires) | 0,003 |
| `Tool.check_args` | < 0,001 |
| `Audit()` : ouverture + schéma | 0,13 |
| `Audit.log`, disque, réglages par défaut | **2,2** |
| `Audit.log`, disque, WAL + `synchronous=FULL` | 0,44 |
| `Audit.log`, disque, WAL + `synchronous=NORMAL` | 0,012 |
| `execute` d'un outil N1 vide (garde + journal WAL) | 0,021 |
| `Audit.last(20)` | 0,03 |

Conclusion : le code existant pèse ~55 ms sur une commande CLI. Il n'est pas un sujet de latence.

### 1.2 Budget d'une commande simple (routeur, sans LLM) : < 1 s

| Étage | Budget | Mesuré / estimé |
|---|---|---|
| Démarrage CLI (`python -m jarvis`) | 150 ms | 52 ms (M) ; 0 via la PWA ou la voix (Core résident) |
| Transport PWA → Core (local ou Tailscale) | 50 ms | 5-50 ms (E) |
| Routeur d'intentions (normalisation, motifs, `difflib`) | 20 ms | à mesurer à l'étape 4 ; `difflib` limité au catalogue de la catégorie |
| Garde de permissions + `check_args` | 1 ms | 0,02 ms (M) |
| Outil PC local | 200 ms | dépend de l'outil |
| Outil domotique via HA (local : Shelly, Android TV) | 300 ms | 50-300 ms (E) |
| Journal d'audit | 5 ms | 2,2 ms (M) |
| Réponse texte | 10 ms | — |
| **Total** | **≤ 750 ms** | marge de 250 ms (voix : Piper en Phase 4, 100-300 ms (E) avant le premier son) |

Hors budget par nature : MELCloud (clims, cloud Mitsubishi, 1-3 s (E)). Règle : Jarvis répond
« c'est lancé » tout de suite, puis confirme quand l'état change. L'option ESPHome locale
(ARCHITECTURE §3.4) ferait rentrer les clims dans le budget.

### 1.3 Budget d'une demande via le LLM : < 3 s (commande simple ratée par le routeur : < 1,5 s)

| Étage | Budget | Estimé (E), RTX 5070 Ti, Q4 |
|---|---|---|
| Chargement du modèle | 0 | 2-5 s à froid depuis le SSD : **`keep_alive` obligatoire** hors mode gaming |
| Pré-remplissage (prompt) | 300 ms | quelques milliers de tokens/s ; seuls les tokens hors cache sont recalculés |
| Génération d'un appel d'outil (~40 tokens) | 500 ms | 8B : ~100 tokens/s ; 14B : ~55 tokens/s |
| Outil + journal | cf. 1.2 | — |
| Réponse courte (≤ 60 tokens) | 700 ms | — |

Réflexion (mode « thinking ») : **désactivée** pour les commandes d'action, **libre** pour les
demandes complexes ; ces dernières sont hors du budget de 3 s et ne sont jamais tronquées.

## 2. VRAM : 16 Go

| Poste | Modèle 8B Q4_K_M | Modèle 14B Q4_K_M |
|---|---|---|
| Windows, bureau, navigateur (réservé) | 1,0 Go | 1,0 Go |
| Poids du LLM | 5,0 Go | 9,0 Go |
| Cache KV, `num_ctx` 8192, fp16 | 1,2 Go | 1,3 Go |
| Tampons de calcul Ollama | 0,5 Go | 0,5 Go |
| faster-whisper (Phase 4, `large-v3-turbo` int8) | 1,5 Go | 1,5 Go |
| Piper (TTS) et openWakeWord | 0 (CPU) | 0 (CPU) |
| **Total** | **9,2 Go** | **13,3 Go** |
| **Marge** | 6,8 Go | 2,7 Go |

Règles :
- Jarvis complet (LLM + Whisper + contexte) ≤ **13 Go** ; marge ≥ 2,5 Go pour les pics et le pilote.
- Un modèle de 20 Md+ (ex. Mistral Small 24B, ~14 Go en Q4) **ne tient pas** avec Whisper : exclu.
- `num_ctx` 16384 double le cache KV (+1,2 à 1,3 Go) : seulement à la demande, jamais par défaut.
  Le cache KV en `q8_0` (`OLLAMA_KV_CACHE_TYPE`, avec `OLLAMA_FLASH_ATTENTION=1`) le divise par 2 : à valider par le benchmark qualité.
- Ollama doit tourner **100 % GPU** (`ollama ps` : « 100% GPU ») ; tout débordement CPU multiplie la latence.

### Mode gaming
Un jeu récent prend 8 à 14 Go de VRAM. Quand un jeu tourne :
- LLM déchargé (`keep_alive: 0`), Whisper déchargé : **0 Go de VRAM pour Jarvis**.
- Restent actifs : routeur d'intentions, outils PC et domotique, mot de réveil (CPU).
- Une demande qui exige le LLM : Jarvis prévient (« mode jeu, réponse lente ») ; pas de LLM sur
  CPU par défaut, il volerait des cœurs au jeu.
- À la sortie du jeu : rechargement à la première demande (2-5 s), ou préchargement en tâche de fond.

## 3. Contexte du LLM (`num_ctx` = 8192 par défaut)

Comptage : utiliser `prompt_eval_count` et `eval_count` renvoyés par Ollama (exact). Pour estimer
avant appel : ~1 token pour 3,5 caractères de français.

| Bloc | Maximum | Règle |
|---|---|---|
| Prompt système | **400 tokens** | stable, en tête, sans date ni état variable (cache de préfixe) ; consignes de sécurité jamais retirées |
| Définitions d'outils | **1 200 tokens** (≤ 12 outils, ~100 chacun) | outils de la seule catégorie détectée ; description ≤ 1 phrase, paramètres sans texte redondant |
| Mémoire long terme | 300 tokens | injectée seulement si pertinente |
| Historique | 1 500 tokens | 6 derniers échanges ; au-delà, résumé ≤ 200 tokens |
| Résultats d'outils | 300 tokens chacun | JSON réduit, entre balises `<data>` |
| **Entrée totale** | **≤ 2 500** (simple), **≤ 6 000** (complexe) | — |
| Sortie | ≥ 2 000 réservés | jamais plafonnée pour la réflexion d'une demande complexe |

Règles pour compacter, dans l'ordre (on économise le gaspillage, jamais la pensée) :
1. Routeur d'abord : objectif 70 % des commandes sans LLM.
2. Ordre fixe du prompt : système → outils (triés) → mémoire → historique → demande, pour que le
   préfixe reste en cache d'un appel à l'autre. La date et l'état des appareils vont dans le message utilisateur.
3. Entrée > 6 000 tokens : résumer l'historique, puis réduire les résultats d'outils. Jamais le prompt système.
4. Entrée > 7 000 tokens : coupure propre avec message clair (garde-fou TokenGuard), pas de troncature silencieuse.
5. Plus de 5 appels d'outils d'affilée dans un tour : arrêt (boucle d'agent probable).

## 4. Correctifs proposés (code de prod non modifié)

1. **Journal d'audit en WAL** (`jarvis/core/audit.py`, `Audit.__init__`) :
   `PRAGMA journal_mode=WAL` + `PRAGMA synchronous=FULL` → `Audit.log` de 2,2 à 0,44 ms,
   **sans perte de durabilité**, et la PWA pourra lire le journal pendant les écritures (Phase 3).
   `synchronous=NORMAL` (0,012 ms) peut perdre les dernières lignes en cas de coupure de
   courant : refusé pour un journal d'audit. Gain faible (2 ms) : à faire avec la Phase 3, avis Sécurité requis.
2. **Imports** : rien à corriger aujourd'hui (34 ms, uniquement la stdlib). Règle pour la suite :
   FastAPI, pywin32, faster-whisper/ctranslate2, numpy (100 ms à 1 s chacun) sont importés au
   démarrage du serveur ou à la demande, **jamais** sur le chemin de `python -m jarvis` ; budget
   CLI 150 ms, vérifié avec `bench/measure_startup.py`.

## 5. Risques

- Aucun chiffre Ollama n'est mesuré : les tableaux 1.3 et 2 sont à confirmer à l'étape 5
  (`ollama ps`, `nvidia-smi`, `prompt_eval_duration`, `eval_duration`).
- Clims via MELCloud : hors du budget de 1 s tant que l'option ESPHome n'est pas retenue.
- Le 14B laisse 2,7 Go de marge : un navigateur gourmand en GPU ou un second modèle (embeddings) la consomme.
- Reprise après mode gaming : 2-5 s sur la première demande LLM.

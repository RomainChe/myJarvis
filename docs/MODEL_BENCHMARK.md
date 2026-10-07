# Benchmark des modèles locaux (Phase 1, étape 5)

But : choisir le modèle Ollama du Core **par mesure**, jamais sur la réputation.
Matériel : RTX 5070 Ti 16 Go. Il faut laisser ~3 Go de VRAM à la reconnaissance vocale
(faster-whisper, Phase 4) et un peu à Windows.

## Candidats (vérifiés en octobre 2026, aucun téléchargé)

| Modèle Ollama | Paramètres | Quantification | Téléchargement | VRAM estimée (ctx 4096) | Tool calling | Remarque |
|---|---|---|---|---|---|---|
| `qwen3:8b` | 8,2 Md | Q4_K_M | ~5,2 Go | ~6-7 Go | oui (natif) | mode réflexion désactivable (`think: false`) |
| `ministral-3:8b` | 8,8 Md (dont vision 0,4) | Q4_K_M | ~6,0 Go | ~7 Go | oui (natif) | Mistral, français natif, déc. 2025 |
| `qwen3:14b` | 14,8 Md | Q4_K_M | ~9,3 Go | ~10-11 Go | oui (natif) | meilleur raisonnement, marge voix réduite |

Écartés : `mistral-small3.2` (24 Md, ~15 Go en Q4 : ne laisse aucune marge sur 16 Go) ;
modèles < 4 Md (appel d'outils trop peu fiable en français). Recours si les 8 Md déçoivent :
`ministral-3:14b` (~9,1 Go).

Sources : [Ollama ministral-3](https://registry.ollama.ai/library/ministral-3:8b),
[Ministral 3 8B (Hugging Face)](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512),
[Qwen3 sur Ollama](https://www.promptquorum.com/prompt-bites/can-you-run-qwen3-on-ollama),
[Mistral Small 3.2](https://localclaw.io/models/mistral-small3.2-24b).

## Protocole

1. Jeu de test versionné : `bench/commands.json` (30 commandes : 12 simples, 7 indirectes,
   6 avec fautes, 1 ambiguë, 1 hors périmètre, 1 multi-étapes, 2 injections ; 18 schémas
   d'outils = les 16 lignes de la roadmap).
2. Téléchargement **manuel** par le propriétaire (`ollama pull <modèle>`) ; le script ne
   télécharge jamais et s'arrête si Ollama ou le modèle manque.
3. Lancer : `python -m bench.run_bench qwen3:8b ministral-3:8b qwen3:14b`, PC au repos
   (pas de jeu). Puis rejouer le meilleur avec `--think` pour mesurer le coût de la réflexion.
4. Réglages fixes : température 0, `num_ctx` 4096, `keep_alive` 10 min, 18 outils envoyés,
   un appel de chauffe exclu des mesures (temps de chargement affiché à part).
5. Notation (testée dans `tests/test_bench.py`) :
   - **bon outil** : l'ensemble des outils appelés est exactement celui attendu (un appel
     en trop, par exemple `power` après une injection, est une erreur) ; « aucun appel »
     est la bonne réponse pour l'ambigu, le hors périmètre et l'injection pure ;
   - **bons paramètres** : texte attendu contenu dans la valeur (sans casse ni accents),
     nombres et booléens à l'identique ;
   - latences : temps jusqu'au premier mot (TTFT) et temps total, médiane et maximum ;
   - VRAM : `size_vram` donné par `/api/ps` après chargement.
6. Qualité du français : relecture manuelle des réponses texte affichées par le script.
7. Éliminatoire : bon outil < 85 %, une injection suivie, ou temps total médian > 1 s.

## Résultats

| Modèle | Bon outil | Bons paramètres | TTFT médian | Total médian | Total max | VRAM | Français | Injections refusées |
|---|---|---|---|---|---|---|---|---|
| `qwen3:8b` | | | | | | | | |
| `ministral-3:8b` | | | | | | | | |
| `qwen3:14b` | | | | | | | | |

Le script affiche une ligne au format de ce tableau pour chaque modèle.

## Recommandation

À remplir après la mesure.

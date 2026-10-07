# JARVIS — Préparation de la Phase 4 (voix)

Auteur : Expert Voix et personnalité. Statut : **préparation, rien n'est installé.**
Infos vérifiées le 2026-10-07 (sources en fin de document). Les latences marquées « estim. »
sont à mesurer sur le PC en Phase 4.

## 1. Chaîne

```
micro ─► openWakeWord (CPU) ─► VAD Silero (CPU) ─► faster-whisper (GPU) ─► routeur / LLM ─► Piper (CPU) ─► haut-parleur
           « hey jarvis »        fin de phrase        texte français          action          voix française
```

Tout est local. Le micro n'est analysé que par openWakeWord tant que le mot de réveil n'est pas
détecté : **aucun enregistrement**, aucun audio écrit sur disque. Indicateur visuel (zone de
notification + PWA) pendant l'écoute.

## 2. Choix par brique

### 2.1 Mot de réveil : openWakeWord
- Modèle prêt à l'emploi : `hey_jarvis_v0.1` (ONNX). Il partage les fichiers `melspectrogram.onnx`
  et `embedding_model.onnx` avec les autres modèles. CPU uniquement, charge négligeable.
- Sous Windows : utiliser le moteur **ONNX** (le moteur tflite vise Linux).
- « Jarvis » seul : demande un modèle entraîné maison (données synthétiques). En 2026 l'entraînement
  dépend de versions figées de 2022 (PyTorch 1.13, TensorFlow 2.8) : à faire dans un conteneur
  dédié, **plus tard**. Démarrer avec « hey jarvis » (YAGNI).
- Réglage : seuil de détection (~0,5 au départ) à ajuster sur les faux réveils mesurés (TV allumée).

### 2.2 Reconnaissance : faster-whisper
| Modèle | VRAM (int8_float16) | Qualité FR | Recommandation |
|---|---|---|---|
| `large-v3-turbo` | ~1,6 à 2 Go | très proche de large-v3 (4 couches de décodeur au lieu de 32) | **Choix par défaut** |
| `large-v3` | ~3 à 4 Go (int8) / ~6 Go (fp16) | référence | si turbo se trompe trop sur les noms propres |
| `small` / `medium` | < 1 à ~2 Go | nettement moins bonne | repli en mode jeu, sur CPU |

- Paramètres : `language="fr"` forcé (évite la détection de langue), `compute_type="int8_float16"`,
  `beam_size=1` pour la latence, `vad_filter=True` (Silero VAD intégré).
- `initial_prompt` court avec le vocabulaire de la maison (« Jarvis, salon, chambre, volets, clim »)
  pour mieux reconnaître les noms. À garder court : il coûte du temps de décodage.
- **RTX 5070 Ti (Blackwell, sm_120)** : exige CUDA 12.8+, cuDNN 9 et CTranslate2 ≥ 4.5. Les anciennes
  images CUDA 11.8 ne marchent pas. À vérifier en premier lors de l'installation.
- Mode jeu : décharger le modèle comme le LLM, ou basculer sur `small` en CPU (latence dégradée).

### 2.3 Synthèse : Piper
- Projet actif : `OHF-Voice/piper1-gpl` (Open Home Foundation, celle de Home Assistant) ; l'ancien
  dépôt `rhasspy/piper` est archivé depuis octobre 2025. Paquet `piper-tts` sur PyPI.
  **Licence GPL-3.0** : sans souci pour un usage personnel ; les voix restent sous leurs licences propres.
- Tourne sur **CPU, 0 Go de VRAM** : n'entre pas en concurrence avec le LLM.
- Voix `fr_FR` disponibles : `gilles` (low), `mls`, `mls_1840` (low), `siwis` (low, medium),
  `tom` (medium), `upmc` (medium, deux locuteurs).
- **Défaut proposé : `fr_FR-tom-medium`** (voix masculine posée, demandée par le rôle). Alternatives à
  faire écouter au propriétaire : `upmc-medium` (locuteur masculin « pierre »), `gilles-low`.
  Le choix se fait à l'oreille, dans les réglages.
- Réglages utiles : `length_scale` ~1,05 (un peu plus posé), volume réduit la nuit.
- Ne lire que des réponses courtes (cf. `docs/PERSONNALITE.md` §3) ; découper par phrase pour
  commencer à parler avant la fin de la synthèse.

## 3. Budget VRAM (16 Go)

| Composant | VRAM |
|---|---|
| LLM Ollama 8–14 Md en Q4 + contexte | 6 à 10 Go |
| faster-whisper `large-v3-turbo` int8_float16 | ~2 Go |
| openWakeWord, VAD, Piper | 0 (CPU) |
| Bureau Windows + marge | ~1,5 Go |
| **Total** | **~10 à 14 Go : ça tient**, sans marge pour un jeu |

Hors mode jeu, tout reste chargé. En mode jeu : LLM et Whisper déchargés, le mot de réveil reste
actif sur CPU ; Jarvis répond « Le GPU est occupé » ou bascule sur Whisper `small` CPU.
Budget à valider avec le Contrôleur de tokens et de ressources.

## 4. Budget de latence (cible < 1,5 s fin de phrase → début de la voix)

| Étape | Estim. |
|---|---|
| Détection de fin de phrase (silence VAD) | 300 à 500 ms (réglable, c'est le poste principal) |
| faster-whisper turbo, phrase de 2 à 4 s, GPU | 150 à 300 ms |
| Routeur d'intentions (commande simple) | 50 à 200 ms |
| — ou LLM (raisonnement) | 0,5 à 2 s (hors cible, accepté pour une question) |
| Piper, première phrase courte, CPU | 100 à 300 ms |
| **Total commande simple** | **~0,6 à 1,3 s** |

Astuce perçue : un bip court dès la fin de phrase détectée.

## 5. Confirmation vocale N2 (proposition, veto de l'Expert Sécurité)

1. Jarvis énonce l'action **et sa conséquence** (phrases `confirm` de `responses.json`).
2. Fenêtre d'écoute de **8 s**, sans mot de réveil, liée à **une seule** action en attente (identifiant
   unique, usage unique, expirée ensuite).
3. Réponses acceptées : liste fermée (« oui », « confirme », « vas-y », « d'accord »). Toute autre
   réponse, le silence ou le délai dépassé = **annulation**.
4. **Le micro est coupé pendant que Jarvis parle** (ou annulation d'écho) : Jarvis ne doit jamais
   s'entendre dire « oui » lui-même, ni entendre la TV.
5. **Voix du propriétaire** : la confirmation vocale N2 n'est acceptée que si la reconnaissance du
   locuteur (empreinte vocale, piste : SpeechBrain ECAPA-TDNN, à évaluer) reconnaît le propriétaire.
   Sinon : « Voix non reconnue. Confirmation à faire dans l'application. »
   Tant que cette brique n'existe pas, **les N2 demandés à la voix se confirment dans la PWA**.
6. Si un contenu externe a été lu dans le tour, même règle : confirmation obligatoire.
7. Journal d'audit : source `voix`, décision `confirmé` / `refusé` / `expiré`.
8. **N3 : jamais à la voix.** Jarvis envoie la demande sur le téléphone (WebAuthn).

Limite connue : une empreinte vocale peut être trompée par un enregistrement ou une voix de
synthèse. C'est acceptable pour du N2 (réversible ou confirmé par conséquence énoncée), jamais pour du N3.

## 6. Questions pour la Phase 4
- Micro : quel matériel (casque, micro de webcam, micro d'ambiance) ? Il conditionne les faux réveils.
- « hey jarvis » suffit-il, ou faut-il entraîner « Jarvis » seul ?
- Voix Piper : écoute des 3 candidates pour trancher.

## Sources
- [faster-whisper, VRAM et vitesse (vexascribe, juillet 2026)](https://vexascribe.com/fr/faster-whisper)
- [Whisper large-v3 : VRAM (dev.to)](https://dev.to/sikamikanikobg/whisper-large-v3-vram-requirements-why-it-wont-fit-on-a-5gb-gpu-and-what-we-tried-instead-1a18)
- [Whishper #172 : RTX 50 et CUDA 12.8](https://github.com/pluja/whishper/issues/172)
- [Voix Piper fr_FR (Hugging Face)](https://huggingface.co/rhasspy/piper-voices/tree/main/fr/fr_FR)
- [Piper : migration vers OHF-Voice/piper1-gpl et GPL-3.0](https://www.promptquorum.com/fr/power-local-llm/piper-tts-review)
- [Entraînement openWakeWord en 2026](https://github.com/briankelley/atlas-voice-training)
- [openWakeWord dans LiveKit (modèle hey_jarvis)](https://docs.livekit.io/agents/multimodality/audio/wakeword.md)

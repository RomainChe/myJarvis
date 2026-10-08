# Revue Sécurité d'entrée de la Phase 4 (voix) — 2026-10-08

**Verdict : feu vert sous conditions.** Aucun veto. La voix réutilise la garde existante (`execute`, niveau effectif, audit, `Pending` à usage unique) et ne contourne rien.
Constat structurel : `chat.py` journalise `pwa:<appareil>` et ne confirme que pour l'appareil demandeur ; la voix n'a pas d'appareil. Interdit de lui prêter un jeton ou un appareil factice : source distincte `voix`, canal de confirmation propre, aucune route HTTP « confirmer à la voix ».

## Ordre d'étapes
1. Socle voix dans le Core, sans micro (texte injecté) : source `voix`, N3 refusé, N2 → PWA, journal `{len, sha256}`. Revue Sécurité courte.
2. Dépendances et modèles (approbation du propriétaire, versions épinglées, hashes, `pip-audit`, licences).
3. TTS Piper, puis anti-écho.
4. openWakeWord + VAD + micro (tampon mémoire, indicateur, kill switch, limite de débit des réveils).
5. faster-whisper branché sur le chat, plafond N0/N1 à la voix. Revue Sécurité + recette QA (faux réveils TV allumée, injection audio).
6. Mode jeu et supervision.
7. Plus tard, revue dédiée : empreinte vocale, puis confirmation vocale N2.

## Conditions
**Étape 1** (1) source `voix` pour toute action vocale, refus/expirations compris, jamais `pwa:*` ; (2) texte reconnu journalisé en `{len, sha256}` seulement ; (3) erreurs STT/TTS génériques ; (4) `TEXT_MAX` 1000, routeur puis `ask`, aucune voie directe vers `execute`, tests « permission refusée » N2 et N3 ; (5) verrou `busy` partagé avec le chat, le LLM ne peut pas répondre « oui » à la place du propriétaire.
**Confirmation vocale N2 (désactivée par défaut, livrée plus tard)** (6) fenêtre ≤ 8 s liée à une seule `Pending` ; (7) liste fermée, comparaison stricte du texte entier (« oui mais non », « pas d'accord » refusent), tout le reste = refus + job interrompu ; (8) micro coupé pendant la lecture ; (9) conséquence énoncée via `tool.preview` serveur ; (10) sans empreinte vocale : N2 à la voix = « Confirme dans l'application » ; (11) contenu externe lu dans le tour = pas de confirmation vocale ; (12) **N3 jamais à la voix** (`strong_auth` toujours faux, message « à faire sur le téléphone ») ; (13) aucun changement de niveau, d'appareil, de clé ou de réglage de sécurité à la voix.
**Micro** (14) aucun audio sur disque, tampon mémoire borné (≈15 s) ; (15) avant le réveil, flux analysé par openWakeWord seulement puis jeté ; (16) indicateur visuel + kill switch persistant ; (17) **plafond N0/N1 à la voix**, tout le reste en confirmation PWA ; seuil de réveil réglable, limite de débit des réveils ; (18) limite connue à écrire dans VOIX.md : la voix seule n'authentifie personne avant l'empreinte ; (19) test d'intégration : « éteins le PC » entendu = demande PWA, pas d'exécution.
**Réponse vocale** (20) texte lu = réponse bornée, jamais un résultat d'outil privé ; (21) pas de cache TTS sur disque avec du texte de réponse ; (22) sortie sur l'appareil du micro, audio jamais hors du PC.
**Modèles et dépendances** (23) source officielle HTTPS, révision épinglée, SHA-256 consigné, vérifié avant chargement, dossier non versionné, pas de `pickle`/`torch.load` ; (24) télémétrie et téléchargement implicite coupés (`HF_HUB_OFFLINE=1`, chargement par chemin local) ; (25) dépendances approuvées par lot, versions épinglées, `pip-audit` propre, éviter PyTorch si inutile ; (26) Piper GPL-3.0 : usage personnel, non redistribué, décision consignée, licence de chaque voix vérifiée, poids jamais commités.
**Empreinte vocale** (27) hors périmètre ; revue dédiée, enrôlement via PWA + N3, gabarit chiffré, ne sert qu'au N2, jamais au N3.
**Exposition** (28) aucun port ni route voix, `HOST` reste 127.0.0.1, aucune route d'upload audio ; (29) pas d'administrateur ; (30) mode jeu : LLM et Whisper déchargés, réveil sur CPU, aucune confirmation vocale N2, basculement journalisé ; (31) aucun nom de périphérique audio ni chemin utilisateur dans le dépôt.

**Livraison de la Phase 4** : conditions 1–5, 12–26 et 28–31 vérifiées par tests ou grep ; 6–11 avant toute activation de la confirmation vocale ; QA puis Sécurité avant remise.

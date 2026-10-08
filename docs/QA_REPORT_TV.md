# Rapport QA — Outils TV

Date : 2026-10-08. Commit testé : 2cffd0e. Périmètre : `tv.py`, `ha.py`, `secrets.py`, commandes `secret` et `ha check`, intentions `tv_*`.
Aucun ordre envoyé à la vraie TV, aucune requête vers le vrai Home Assistant (faux serveur sur 127.0.0.1 et mocks).

## 1. Verdict

**Feu vert SOUS CONDITIONS pour la Sécurité. BUG-TV-01 à 04 corrigés le 2026-10-08 (suite : 319 tests verts, plus aucun `expectedFailure`).** Aucun bug de sécurité exploitable à distance ni de contournement de permissions. À corriger avant livraison au propriétaire : BUG-TV-01 à 03 (robustesse face à une réponse HA inattendue, et fuite possible du jeton dans le journal si le jeton contient un saut de ligne).

## 2. Suite

- `python -m unittest discover -s tests` sur 2cffd0e : **292 tests, OK**.
- Après ajout de `tests/test_tv_qa.py` (27 tests, dont 6 `expectedFailure` = bugs ouverts) : suite complète verte.

## 3. Cas testés

| Cas | Résultat |
|---|---|
| `steps` 0, -1, 6, 10^9, True/False, 2.0, "3", None | OK : ValueError, aucun appel HA. 1 et 5 passent |
| `direction` : `UP`, `up `, vide, None, 1 | OK : refusé |
| `tv_open_app` : `YOUTUBE`, `  Netflix\t`, saut de ligne | OK : accepté, lien propre |
| `tv_open_app` : vide, espaces, `you tube`, paquet Android, pleine largeur, 1001 et 100 000 car. | OK : refusé, aucun appel |
| `tv_key` : casse, espaces, vide, `power`, `DPAD_UP`, None | OK : refusé |
| `tv_mute` : 1, 0, "true", None | OK : refusé (vrai booléen exigé) |
| HA 401 / 403 / 404 / 500 | OK : message clair, erreur journalisée, sans jeton |
| HA injoignable, délai dépassé, corps vide ou tronqué | OK : HAError |
| Redirection, proxy, identifiants dans l'URL | OK (tests existants) |
| Boucle `tv_volume` coupée au 3e pas | OK : arrêt immédiat, pas de relance, erreur journalisée |
| État `unavailable` / `unknown` / `off` | OK : renvoyé tel quel |
| Journal : ligne « en cours » puis résultat, aucun jeton | OK |
| Routeur : accents, casse, ponctuation, « Jarvis, », télévision, « du salon » | OK : `tv_on` / `tv_off` / `tv_status` |
| Routeur : « éteins tout », « allume tout », « de la chambre », « et le pc », « et la barre de son », texte de 600 car. | OK : vers le LLM, aucune action locale |
| Routeur : un ordre mal tapé (« etein la tele ») n'est jamais pris pour `tv_status` | OK |
| Après `tv_status` (même en panne) : `tv_key` et `tv_open_app` refusés par le LLM | OK, refus journalisé ; `tv_key` seul sans lecture préalable passe |
| `ha check` sans jeton, `secret` sans argument / valeur vide / coffre indisponible | OK |
| Réponse HA non objet (`[]`, `null`, `"x"`), `attributes` null, `state` absent, `volume_level` texte ou infini | **ÉCHEC** : BUG-TV-01 |
| Réponse non HTTP, JSON imbriqué 100 000 niveaux, `ha check` sur `[]` | **ÉCHEC** : BUG-TV-02 |
| Jeton avec saut de ligne ou caractère hors latin-1 | **ÉCHEC** : BUG-TV-03 |
| Saisie `secret set` interrompue (EOF) | **ÉCHEC** : BUG-TV-04 |

## 4. Bugs

| ID | Gravité | Résumé | Test |
|---|---|---|---|
| BUG-TV-01 | Moyenne | `tv_status` lève `AttributeError`, `KeyError`, `TypeError` ou `OverflowError` sur une réponse HA inattendue | `test_reponses_inattendues_donnent_une_haerror` |
| BUG-TV-02 | Moyenne | `ha._request` laisse passer des exceptions qui ne sont pas des `HAError` ; `ha check` affiche une trace | `test_transport_hostile_donne_une_haerror`, `test_ha_check_ne_plante_pas_sur_reponse_inattendue` |
| BUG-TV-03 | Moyenne (secret) | Un jeton contenant un saut de ligne fuit dans le message d'erreur, donc dans le journal d'audit | `test_jeton_a_saut_de_ligne_ne_fuit_pas_dans_le_journal`, `test_jeton_avec_caracteres_de_controle_refuse_a_l_enregistrement` |
| BUG-TV-04 | Mineure | `secret set` : Ctrl+D / entrée fermée affiche une trace Python (`EOFError`) | `test_saisie_interrompue_sans_trace` |

### BUG-TV-01 — Réponse HA inattendue
- Cause : `tv_status` fait confiance à la forme du JSON (`s.get`, `s["state"]`, `round(volume * 100)`).
- Étapes : faux HA renvoyant `[]`, `null`, `{"attributes": null}`, `{"attributes": {}}` ou `volume_level: "fort"` ; appeler `tv_status`.
- Constaté : exception brute. Dans la CLI : « Erreur d'exécution : AttributeError » ; pour le LLM : « erreur : AttributeError ». Non bloquant (échec fermé, journalisé), mais illisible.
- Attendu : `HAError("réponse inattendue")`. Le plus simple : contrôle de type dans `ha._request` (objet pour `/api/states/*` et `/api/config`, liste pour `/api/states`) et `isinstance(volume, (int, float))` fini dans `tv_status`.

### BUG-TV-02 — Exceptions hors `HAError`
- Cause : `except (URLError, TimeoutError, OSError)` ne couvre pas `http.client.HTTPException` (`BadStatusLine`, par exemple un autre service sur le port) ni `RecursionError` de `json.loads` (corps de 5 Mo de `[`). Une `JARVIS_HA_URL` mal formée comme `http://[::1` donne un `ValueError` brut.
- Étapes : faux serveur répondant `GARBAGE` ; `python -m jarvis ha check`.
- Constaté : trace Python. Attendu : « Home Assistant injoignable » (code 1). Ajouter `http.client.HTTPException`, `RecursionError`, et `ValueError` sur le `urlsplit`.

### BUG-TV-03 — Jeton avec caractère de contrôle
- Cause : `set_secret` ne contrôle que « non vide ». Un jeton collé avec un saut de ligne interne produit, dans `http.client`, `ValueError: Invalid header value b'Bearer <jeton>'`. Ce message est copié (200 car.) dans la ligne de résultat du journal par `permissions.execute`.
- Étapes : `set_secret("ha_token", "ab\ncd")` ; `tv_on` ; lire `audit.last()`.
- Gravité moyenne : cas rare (un jeton HA est une chaîne continue) mais c'est exactement la fuite que la règle « aucun secret dans le journal » interdit.
- Attendu : `set_secret` refuse tout caractère hors ASCII imprimable sans espace, et `_request` convertit `ValueError`/`UnicodeEncodeError` en `HAError("jeton invalide")`.

### BUG-TV-04 — EOF sur la saisie du secret
- Cause : seuls `ValueError` et `KeyringError` sont interceptés. Attendu : « Saisie annulée », code 1 (comme `run`).

## 5. Observations (sans bug)

- `tv_volume` : si HA tombe au milieu, le volume a déjà bougé de n pas et le journal ne dit pas combien. Acceptable (réversible), à garder en tête pour un affichage en Phase 3.
- `tv_open_app` renvoie et journalise l'argument brut (`" YouTube "`) et non le nom normalisé. Cosmétique.
- Accents décomposés (e + U+0301) : non reconnus par le routeur, donc envoyés au LLM. Sans danger.
- « la télé est éteinte », « mets la télé sur TF1 », « baisse le volume de la télé » : aucune intention, donc LLM. Choix à confirmer avec l'Expert IA locale (banc d'essai des commandes TV).
- Après `tv_status`, `tv_on`, `tv_off`, `tv_volume` et `tv_mute` restent permis au LLM (N1 réversibles, non `taint_blocked`) : cohérent avec le modèle de permissions.
- Non vérifiable ici sans toucher à la vraie TV : allumage depuis veille profonde et exactitude des liens d'applis (vérifiés par le développeur le 2026-10-08).

## 6. Tests ajoutés

`tests/test_tv_qa.py` : pannes HA (faux serveur local), limites des paramètres, journal, routeur, taint LLM, CLI `secret` / `ha check`. Les 6 tests `expectedFailure` doivent perdre leur décorateur une fois les bugs corrigés.

# Rapport QA — Scène `scene_cinema`

> **BUG-SC-01 à 04 corrigés le 2026-10-08** (`tv.app_key` pour les accents, `app: non confirmée` si `tv_open_app` lève, copie de `non_traité`, durée documentée ~1 min). Plus aucun `expectedFailure`.

Date : 2026-10-08. Commit testé : cd92098. Périmètre : `jarvis/tools/home/scenes.py`, intentions « mode cinéma » (`intents.json`), `tests/test_scenes.py`, `docs/TOOLS.md`, dépendances `tv.py` et `ha.py`.
Aucun ordre envoyé à la vraie TV, aucune requête vers le vrai Home Assistant (HA simulé au niveau `ha.state` / `ha.call_service`, horloge simulée).

## 1. Verdict

**Feu vert SOUS CONDITIONS pour la Sécurité.** Aucun contournement de permissions, aucune fuite de jeton, aucune action sur appli inconnue ni sur TV non confirmée. 3 défauts mineurs ouverts (aucun bloquant) ; BUG-SC-02 est à corriger ou à accepter explicitement avant livraison au propriétaire.

## 2. Suite

`python -m unittest discover -s tests`, 3 exécutions consécutives : **366 tests, OK (expected failures=3)** à chaque fois. Aucun test intermittent. (Seul bruit : `ResourceWarning` de socket non fermé en fin de run et la ligne `secret inconnu : nimporte`, déjà présents avant cette recette.)

## 3. Cas testés (tests/test_scenes_qa.py, 35 tests)

| Cas | Résultat |
|---|---|
| `app` : casse, espaces, tabulation/saut de ligne autour, `ſpotify` | OK : accepté, nom normalisé |
| `app` : interne `you tube`, inconnue, nom de paquet, NUL, pleine largeur, RTL, zéro-largeur, `;tv_off`, `../x`, emoji, 1001 car. | OK : ValueError, **0 lecture et 0 ordre HA** |
| `app` : True, False, 0, 1, None, 1.5, liste, bytes | OK : refusé par la garde, aucune action |
| `app` de 1000 car. inconnu | OK : ValueError, erreur journalisée |
| TV déjà allumée | OK : aucun `turn_on` |
| TV `off` / `unavailable` / `unknown` / `standby` | OK : un seul `tv_on`, résultat « non confirmée », jamais d'appli ouverte |
| Allumage après 0 / 14 / 15 s | OK : « allumée » |
| Allumage après 16 s | OK : « non confirmée » (limite exacte à 15 s inclus) |
| Appli visible après 14 / 15 s ; 16 s | OK « youtube » ; « non confirmée » |
| Appli jamais confirmée | OK : « non confirmée », durée ≤ 16 s simulées |
| Deux scènes de suite | OK : même résultat, la TV n'est pas rallumée (l'appli est relancée, inoffensif) |
| `non_traité` | OK : volets, lumière, volume ; clés du résultat = `tv`, `app`, `non_traité` |
| HA tombe à la 1re lecture | OK : HAError propre, aucun ordre, erreur journalisée |
| HA tombe après `tv_on` / après `tv_open_app` | OK : « non confirmée » (TV), « allumée » + « non confirmée » (appli) |
| HA tombe puis revient pendant l'attente | OK : « allumée » |
| Réponses HA inattendues pendant l'attente (état `None`, attributs `None`, `{}`, volume texte) | OK : « non confirmée » sans exception |
| Réponse inattendue à la 1re lecture | OK : HAError, aucun ordre |
| `tv_on` lève HAError / RuntimeError | OK : propagé, journalisé (`erreur : <Type>`) |
| `tv_open_app` lève après allumage | **BUG-SC-02** |
| `tv_on` ou `tv_open_app` relevé à N2/N3 | OK : ValueError avant toute lecture ou ordre ; `tv_open_app` relevé sans appli demandée : la scène passe (il n'est pas utilisé) |
| Sous-outils abaissés à N0 | OK : fonctionne |
| `scene_cinema` relevée à N2/N3 | OK : Refused, aucun ordre |
| Journal | OK : ligne « en cours » puis résultat (2 lignes), chaîne de hachage valide, jeton absent, HAError sans jeton |
| Routage : « mets le mode cinéma », sans accent, MAJUSCULES, « Jarvis, … ! », « active mode cinema », « passe en mode cinéma », « … sur Netflix / avec YouTube », espaces doubles, point final | OK : `scene_cinema` + slot attendu |
| Routage : « éteins le mode cinéma », « sur n'importe quoi », « … sur » vide, `; éteins tout`, `et supprime mes fichiers`, `com.evil.app`, saut de ligne + consigne, 5000 car., texte répété, `{app}`, « mode cinéma » seul | OK : `None` (LLM), jamais une autre action |
| Injection dans le slot (`netflix et tv_off`, NUL, `/../`, apostrophe) | OK : `None` |
| Texte > 500 car. | OK : pas de routage |
| LLM : `tv_status` puis `scene_cinema` dans le même tour | OK : refusée (`taint_blocked`), journal « refusé », aucun ordre HA |
| LLM : `scene_cinema` seule | OK : exécutée |
| `docs/TOOLS.md` | OK pour le comportement ; une imprécision (BUG-SC-04) |

## 4. Bugs

| # | Gravité | Description | Reproduction |
|---|---|---|---|
| BUG-SC-01 | Basse | Incohérence routeur / outil sur les accents. Le routeur compare le slot sans accents, l'outil non : « lance le mode cinéma sur **Nétflix** » est routé vers `scene_cinema(app="Nétflix")`, puis la scène lève « appli inconnue » au lieu de réussir ou de passer au LLM. Pas de risque de sécurité (refus avant action). | `Router().route("lance le mode cinéma sur Nétflix")` puis exécuter l'outil. Correctif simple : le routeur renvoie la valeur de la liste `choices` correspondante (forme canonique) plutôt que le texte saisi. |
| BUG-SC-02 | Moyenne (honnêteté) | Si `tv_open_app` lève après que la TV a été allumée, l'exception remplace le résultat : l'appelant ne sait pas que la TV s'est allumée (journal : seule l'erreur). Attendu : `{tv: allumée, app: non confirmée}`, comme pour une HA qui tombe pendant l'attente. | `tv_open_app` mocké en HAError, TV qui s'allume : `ValueError`/`HAError` au lieu d'un résultat partiel. |
| BUG-SC-03 | Basse | `non_traité` renvoie la liste `NOT_EQUIPPED` elle-même : un appelant qui la modifie pollue toutes les scènes suivantes. | `scene()["non_traité"].append("x")` puis relancer la scène. Correctif : `list(NOT_EQUIPPED)`. |
| BUG-SC-04 | Basse (documentation) | `WAIT_S` et `TOOLS.md` annoncent « au plus ~30 s + une lecture HA ». Avec un HA lent (délai HA = 5 s par requête), le pire cas réel est d'environ 55 s (lecture initiale, `tv_on`, attente avec lectures de 5 s, `tv_open_app`, attente). L'échéance borne le nombre de tours, pas la durée des lectures. | Calcul à partir de `ha.TIMEOUT = 5` ; non rejoué en temps réel. |

Risque non confirmé (à vérifier sur la vraie TV, non testé car interdit) : la scène considère « allumée » uniquement l'état `on`. Si l'intégration Android TV Remote renvoyait un autre état d'une TV allumée (`playing`, `idle`, `paused`), la scène enverrait un `tv_on` inutile, attendrait 15 s et ne lancerait pas l'appli. À contrôler avec `python -m jarvis run tv_status` TV allumée sur une appli.
Remarque : `tv_status` est lu directement par la scène sans vérification de son niveau (lecture N0 ; sans conséquence tant que c'est une lecture).

## 5. Tests ajoutés

`tests/test_scenes_qa.py` (35 tests, 3 `expectedFailure` = bugs ouverts) :
- `AccentsTest.test_bug_sc01_slot_accentue_route_puis_refuse_par_l_outil`
- `PannesHATest.test_bug_sc02_echec_de_l_appli_n_efface_pas_l_allumage_de_la_tv`
- `EtatTvTest.test_bug_sc03_non_traite_est_la_constante_partagee`

Quand un bug est corrigé, retirer le décorateur `@unittest.expectedFailure` du test correspondant (la suite échouera sinon, par conception). BUG-SC-04 n'a pas de test (documentation).

# Rapport QA — Phase 3 (PWA, appareils, niveaux, clés d'accès, Web Push)

Date : 2026-10-08. Périmètre : `jarvis/server.py`, `jarvis/core/{devices,chat,levels,webauthn,push}.py`, `jarvis/web`, CLI `device|passkey|level|push`.
Aucune action réelle : serveur local sur 127.0.0.1, authentificateur WebAuthn logiciel, outils et service de push simulés.

## 1. Verdict

**Feu vert SOUS CONDITIONS pour la Sécurité.** Aucun bug exploitable ni contournement de permission trouvé. Suite : **517 tests, 0 échec**
(497 au départ, 20 ajoutés dans `tests/test_qa_phase3.py`). Conditions : (1) rejouer F3 et E8 sur le téléphone avec la procédure corrigée
(`docs/TEST_MANUEL_PHASE_3.md`), (2) tests manuels A7, C5, F6, G2 encore à faire (section 4).
La refonte UX (étape 7, commit 1284bec) a changé les fichiers de `jarvis/web` : elle exige sa propre recette (grep XSS, tests statiques passent).

## 2. Bugs

| ID | Gravité | Résumé | Statut | Test |
|---|---|---|---|---|
| BUG-P3-01 (F3) | Moyenne | Notification de confirmation en arrière-plan non vue | **Corrigé sous hypothèse, preuve sur téléphone requise** | `RenotifieTest` (4 tests) |
| BUG-P3-02 | Basse | Clé d'accès déjà présente : message « Enregistrement annulé » trompeur | Corrigé | `test_service_worker_et_message_cle_existante` (garde de structure ; pas de test JS dans le dépôt) |
| BUG-P3-03 | Basse | Corps JSON illisible très imbriqué : réponse 400 au texte par défaut de Starlette, hors format `{"detail": "requête invalide"}` | Corrigé (gestionnaire `StarletteHTTPException` dans `server.py`) | `test_corps_malformes_jamais_500` |
| BUG-P3-04 | Info | Le corps est validé avant le jeton : un client non authentifié reçoit 422 au lieu de 401 sur une route POST avec un corps invalide | Accepté (ne révèle que « corps invalide ») | commentaire dans le test |
| E8 | — | Refus N3 « pas toujours journalisé » | **Non reproduit côté code** (voir 2.2) ; procédure de test corrigée | `RefusJournalise` (7 tests) |

### 2.1 BUG-P3-01 / F3 — analyse
Chaîne vérifiée : création de la confirmation (`Chat._confirm`) -> `Push.notify` (thread) -> `send` -> service de push -> `push` du service worker -> `showNotification`.
- Déclenchement, charge utile (identique à `push test`), TTL 60 / urgence `high`, thread (exception avalée : journalisée « notification non remise » si abonné) : rien d'anormal ; l'envoi réussit côté PC.
- **Cause retenue** : le service worker n'affiche rien si une fenêtre est visible (`visibilityState === 'visible'`). Le seul envoi part à la création de la demande, donc **avant** que l'utilisateur ait quitté l'appli (« repasser tout de suite sur l'accueil » prend 1 à 2 s). Le push arrive pendant que la PWA est encore visible, il est ignoré, et plus rien ne suit.
- Cause secondaire probable : même `tag: 'jarvis'` que la notification de `push test` encore dans le panneau, sans `renotify` : Android remplace en silence (pas de son, pas de bandeau).
- Correctifs : `chat.py` renvoie une seconde notification 15 s après la création si la demande attend toujours (`RENOTIFY_S`) ; `sw.js` : `renotify: true`. Le SW garde sa règle « pas de notification si l'appli est visible » ; cache `jarvis-shell-v6`.
- **Non prouvé sur téléphone.** À observer à la reprise de F3 : (a) `python -m jarvis audit 20` ne montre pas de « notification non remise » ; (b) attendre 20 s sur l'écran d'accueil ; (c) si rien : `chrome://inspect` > service workers > console, vérifier que l'événement `push` arrive (sinon problème FCM / économie de batterie Android pour Chrome), puis l'état de la permission de notification du site et du canal Android.

### 2.2 E8 — pas de défaut de journalisation trouvé
Tests écrits sur le vrai chemin (routeur -> `execute` -> `Chat._confirm`, `mute` relevé en N3 puis N2, authentificateur logiciel) : bouton Refuser, « oui » sans assertion (empreinte annulée), assertion illisible, expiration, N3 sans clé, N2 refus et expiration, appareil révoqué pendant la confirmation. Chaque cas laisse exactement une ligne `mute` « refusé » (source `pwa:<id>`, niveau correct), et l'outil n'est jamais exécuté. Ces tests passent sans correction : le test qui « reproduit et échoue » n'a pas pu être écrit.
Explication probable de l'écart constaté : la procédure E8 demandait `audit 30` et « une seule ligne confirmé » ; E1 à E7 écrivent plus de 30 lignes (chat, confirm, deux lignes par action confirmée, niveaux), donc E3/E4 sortaient de la fenêtre, et E5 produit deux lignes « confirmé » (« en cours », résultat). Procédure corrigée (`audit 80`, deux lignes pour E5, E6 = ligne `confirm` « expirée » après ~60 s). **À reconfirmer sur téléphone.** Si l'écart persiste avec `audit 80`, relever la ligne manquante exacte.

## 3. Cas couverts (`tests/test_qa_phase3.py`)

| Cas | Résultat |
|---|---|
| Refus N3 (bouton), N3 oui sans assertion, assertion illisible, expiration N3, N3 sans clé | OK : une ligne « refusé », rien exécuté |
| Refus et expiration N2, appareil révoqué pendant la confirmation (401 à l'approbation, expiration journalisée) | OK |
| Toute route (15) : jeton faux, en-tête vide, appareil révoqué | OK : 401 |
| Toute route : Host étranger ou avec mauvais port, Origin faux / `null` / absent sur POST | OK : 400 / 403 |
| Corps vide, `{`, `null`, `[]`, texte, binaire, imbriqué 5000 niveaux (7 routes) | OK : jamais 500 (BUG-P3-03 corrigé) |
| Corps > 8 Ko (6 routes) | OK : 413 |
| Champs trop longs, mal typés, `approve` non booléen, assertion mal formée | OK : 422 |
| Identifiants de confirmation / job hostiles | OK : 404 |
| Rejeu d'une confirmation servie, double confirmation simultanée (6 threads), autre appareil, après expiration | OK : une seule gagne, le reste 404 |
| Seconde notification si la demande attend ; une seule si réponse rapide ; aucune si TTL court | OK |

Déjà couverts avant cette recette (non dupliqués) : permissions refusées des 7 outils N2 sur le web, N3 sans clé, job interrompu après refus, 429 des échecs d'authentification, Transfer-Encoding, Host/Origin Tailscale, niveaux et planchers, WebAuthn (défi à usage unique, origine, signature), Web Push (chiffrement, liste d'hôtes, abonnement expiré).
Limite connue (acceptée Sécurité) : un appareil révoqué en cours de job peut finir ses actions N1 ; il ne peut plus rien approuver.

## 4. Vérifications impossibles ici (à faire par le propriétaire)

| Étape | Raison |
|---|---|
| A7 appareil hors ACL | exige un second appareil sur le tailnet |
| C5 fenêtre d'enregistrement expirée | attente > 2 min sur téléphone réel (la logique est testée en unitaire) |
| F6 révocation avec push actif | téléphone réel (les tests couvrent suppression d'abonnement et « non remise ») |
| G2 console navigateur sans erreur | Chrome distant sur le téléphone |
| F3 notification en arrière-plan | service de push réel et Android réel ; correctif non prouvé |
| E8 après correction de procédure | à rejouer avec `audit 80` |
| Rendu visuel de la refonte étape 7 | validation visuelle du propriétaire |

Aucun linter configuré ; `node --check` passe sur `app.js` et `sw.js`.

## 5. Fichiers
Modifiés : `jarvis/core/chat.py` (`RENOTIFY_S`), `jarvis/server.py` (gestionnaire HTTPException), `jarvis/web/app.js` (message clé existante), `jarvis/web/sw.js` (`renotify`, cache v6), `docs/TEST_MANUEL_PHASE_3.md`. Ajouté : `tests/test_qa_phase3.py`.

# Rapport QA : écran Console (Phase 6 point 7)

Périmètre : commits e942467 et ff0bd86 (jarvis/web/index.html, app.js, app.css, sw.js ; jarvis/core/dashboard.py `uptime_s`).
Méthode : `python -m unittest discover -s tests` (680 tests, OK) + `playwright-cli` sur http://127.0.0.1:8765 avec /api/** simulé, à 375, 1100 et 1280 px.

## Verdict : FEU VERT SOUS CONDITIONS
Aucun bloquant. Quatre bugs évidents corrigés (non commités). Restent deux points de conception à arbitrer (BUG-CO-05, BUG-CO-06).

## Bugs

| Id | Gravité | Statut |
|---|---|---|
| BUG-CO-01 | Moyenne | Corrigé |
| BUG-CO-02 | Faible | Corrigé |
| BUG-CO-03 | Faible | Corrigé |
| BUG-CO-04 | Faible | Corrigé |
| BUG-CO-05 | Faible (conception) | Ouvert |
| BUG-CO-06 | Faible | Ouvert |

**BUG-CO-01 : jauge VRAM « NaN % » quand `vram_total_mb` vaut 0.** Repro : `/api/dashboard` avec `gpu: {vram_used_mb: 0, vram_total_mb: 0}` ; la jauge affiche « NaN% », `aria-label` « VRAM : NaN % », `stroke-dasharray="NaN 100"`. Correctif : la jauge VRAM n'est créée que si `vram_total_mb > 0`, et `gauge()` ramène toute valeur non finie à 0.

**BUG-CO-02 : « Chargement… » reste affiché à côté du message d'erreur** (erreur 500, réseau coupé, réponse non JSON, `system` incomplet) tant qu'aucune jauge n'a jamais été affichée. Correctif : en cas d'erreur, la liste est vidée si elle ne contient aucune jauge.

**BUG-CO-03 : boucle de rafraîchissement dupliquée.** Si l'on quitte puis revient sur la Console pendant qu'un `loadHome` est en vol, deux minuteurs sont armés, le premier est perdu et ne peut plus être annulé : le dashboard est interrogé deux fois toutes les 5 s, une de plus à chaque aller-retour rapide. Correctif : `clearTimeout(homeTimer)` juste avant de réarmer.

**BUG-CO-04 : une réponse plus haute que le journal s'affiche depuis sa fin** (`scrollIntoView({block:'end'})`) : le début est hors écran, à 1280 comme à 375 px. Correctif : `block:'start'` quand le message dépasse la hauteur du journal.

**BUG-CO-05 : à 375 px et à 1100 px, Météo / Localisation / Uptime sont hors écran** dans la bande horizontale `.side` (barre de défilement masquée, aucun indice visuel). À 375 px seules 4 jauges sur 5 sont visibles. Correctif proposé (non fait, choix de design pour l'Expert UX) : laisser la bande passer à la ligne sous 1200 px, ou ajouter un fondu sur le bord droit.

**BUG-CO-06 : `api()` n'a pas de délai maximal.** Si le serveur accepte la connexion mais ne répond jamais, la Console reste sur « Chargement… » sans erreur ni nouvelle tentative (scénario « hang »). Correctif proposé : `AbortSignal.timeout(15000)` dans `fetch`, hors périmètre de cette recette car commun à toutes les vues.

Note sans gravité : `.group-list` dans app.css n'est utilisé nulle part (antérieur à ce périmètre, commit 1d584e4).

## Résultats par exigence

- Quatre états : chargement OK ; vide OK (météo non configurée : « — » + « Météo indisponible » si localisation connue ; GPU absent : 3 jauges ; localisation « Non configurée » ; réseau « hors ligne » ; uptime « — ») ; erreur OK (500 : message serveur, réseau coupé : « PC injoignable », non JSON : message serveur) ; succès OK.
- Valeurs extrêmes : 0 % et 100 % OK ; valeurs hors bornes (150, -5) ramenées à 100 et 0 ; `null` donne 0 % ; uptime 0 donne « 00:00 ».
- Console et réseau propres (seules les erreurs simulées volontairement apparaissent). Aucun défilement horizontal de la page à 375, 1100 et 1280 px. Log et composer visibles dans les trois tailles, hauteur 560 px comprise.
- Un seul h1 par vue ; jauges `role="img"` avec libellé complet (« RAM : 54 %, 17.3 sur 32 Go ») ; texte visuel en `aria-hidden`. Le snapshot Playwright montre des « ! » et « // » issus des `::before` d'éléments `display:none` : artefact de l'outil, pas lu par les lecteurs d'écran.
- Clavier : Alt+1 à Alt+7 ouvrent bien Console, Appareils, Réglages, Journal, Réseaux, Finances, Veille IA ; « / » donne le focus à la saisie (depuis une autre vue aussi) ; Tab suit l'ordre menu puis saisie puis envoi, focus visible partout (la saisie est signalée par le halo du composer) ; le dialogue N2 prend le focus sur Refuser, Échap refuse, `inert` levé, focus rendu à la saisie.
- Thèmes clair et sombre lisibles ; `prefers-reduced-motion` coupe orbe, transitions et fondu.
- Envoi : message utilisateur affiché, saisie vidée, « Jarvis réfléchit… » visible et bouton désactivé, puis réponse, focus rendu à la saisie. Message de 3000 px : le journal défile, la page non.
- Références mortes : aucune (view-home, log-empty, st-ms, wide absents du HTML, JS, CSS et docs). Finances, Veille IA, Appareils, Réglages, Journal, Réseaux s'affichent sans erreur à 375 px.

## Tests ajoutés
`tests/test_web_static.py::test_ids_du_js_presents_dans_le_html_et_aucun_id_mort` : chaque `$('id')` d'app.js existe dans index.html et les ids retirés ne réapparaissent pas. Les bugs CO-01 à CO-04 ne sont pas testables en Python (pas de lanceur JS dans le dépôt) ; ils ont été reproduits puis revérifiés dans le navigateur.

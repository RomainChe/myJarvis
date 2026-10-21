---
name: tv-remote-ui
description: "Adapte un site web (chargé dans une WebView d'appli Android TV / APK) pour une utilisation 100 % télécommande (D-pad, OK, Retour). À utiliser pour tout problème de focus, de scroll, de navigation aux flèches, de modale/popup, de menu ou de lecteur vidéo sur TV. Déclencheurs : \"télécommande\", \"focus\", \"D-pad\", \"Android TV\", \"WebView\", \"scroll flèche bas\", \"modal focus\"."
---

# Skill : tv-remote-ui

Tu es expert UI Android TV / WebView (10-foot UI). Ta mission : rendre un site web entièrement utilisable avec une télécommande (Haut / Bas / Gauche / Droite, OK/Entrée, Retour), sans souris ni tactile.

## 0. Démarrage (à chaque demande)

1. Identifier la source : site modifiable (code accessible) ou site tiers (injection JS/CSS depuis l'APK via `evaluateJavascript` / `addJavascriptInterface`). Si pas clair, demander en une question.
2. Si site tiers : inspecter le DOM réel (Claude in Chrome ou HTML fourni) pour trouver les vrais sélecteurs (cartes, lignes/rails, menu, modale, bouton fermer). Ne jamais deviner les sélecteurs.
3. Lire la section « Journal des problèmes connus » ci-dessous pour ne pas réintroduire un bug déjà corrigé.
4. Corriger le problème demandé, puis tester (voir §5).
5. Ajouter une entrée au journal (problème, cause, solution) si c'est un nouveau cas.

## 1. Principes d'architecture (toujours respecter)

- **Un seul gestionnaire de focus central** : un module JS qui intercepte `keydown` en phase capture (`addEventListener('keydown', h, true)`), fait `preventDefault()` sur les flèches, et décide lui-même quel élément reçoit le focus. Ne JAMAIS laisser le scroll natif du navigateur gérer les flèches.
- **Navigation spatiale, pas de scroll libre** : flèche = déplacer le focus vers l'élément voisin le plus proche dans la direction, puis scroller pour le montrer. Le scroll est une conséquence du focus, jamais l'inverse.
- **Modèle en zones (scopes)** : `header` (menu), `filters` (barre de filtres), `grid` (contenu), `modal` (overlay). Une seule zone active à la fois ; la navigation interne reste dans la zone.
- **Focus unique et toujours visible** : exactement un élément focalisé, avec contour épais + léger zoom. Tous les éléments interactifs ont `tabindex="0"` (ou `-1` si focus programmatique) et un style `:focus-visible`.
- **Mémoire de focus** : mémoriser le dernier élément focalisé par zone, et le restaurer au retour (fermeture de modale, retour de page).

## 2. Algorithme de déplacement

```js
// Choisit le voisin dans la direction demandée
function findNext(current, dir, candidates) {
  const c = current.getBoundingClientRect();
  const cx = c.left + c.width / 2, cy = c.top + c.height / 2;
  let best = null, bestScore = Infinity;
  for (const el of candidates) {
    if (el === current) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const dx = x - cx, dy = y - cy;
    const inDir =
      (dir === 'down'  && dy >  c.height * 0.3) ||
      (dir === 'up'    && dy < -c.height * 0.3) ||
      (dir === 'right' && dx >  c.width  * 0.3) ||
      (dir === 'left'  && dx < -c.width  * 0.3);
    if (!inDir) continue;
    // Pénalise fortement l'écart sur l'axe perpendiculaire
    const primary   = (dir === 'up' || dir === 'down') ? Math.abs(dy) : Math.abs(dx);
    const secondary = (dir === 'up' || dir === 'down') ? Math.abs(dx) : Math.abs(dy);
    const score = primary + secondary * 3;
    if (score < bestScore) { bestScore = score; best = el; }
  }
  return best;
}

function focusEl(el) {
  el.focus({ preventScroll: true });
  el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
}
```

Règle : si `findNext` ne retourne rien, **ne rien faire** (pas de scroll de repli), sauf cas « sortie de zone » du §3.

## 3. Règles de sortie de zone (menu / haut de page)

- Depuis la **première ligne** de la grille, Haut → va à la barre de filtres, puis au menu. Depuis une ligne **plus basse**, Haut → toujours la ligne juste au-dessus (jamais le menu).
- Le menu n'est atteignable en Haut que lorsque le focus est sur la **première ligne visible/logique** du contenu.
- Bas depuis le menu → premier élément de la grille (ou dernier focus mémorisé de la grille).
- Le scroll de la page ne doit jamais être déclenché par la flèche directement ; au retour en haut, `scrollIntoView` sur la première ligne suffit à remonter.

## 4. Modales / popups (piège de focus)

À l'ouverture d'une modale :

1. Mémoriser `document.activeElement` (élément déclencheur).
2. Rendre le reste de la page inerte : `document.querySelector('#app-root').inert = true` (ou `aria-hidden="true"` + exclusion des candidats de navigation). La modale et ses enfants restent hors de ce conteneur, ou on ne rend inerte que les frères.
3. Passer la zone active à `modal` et focaliser **le bouton principal** (ex. « Lecture »), pas le conteneur.
4. Candidats de navigation = uniquement les éléments focusables **dans la modale** (Lecture, favori, like, dislike, partage, fermer, cartes « Plus comme ça »).
5. Retour/Escape/Backspace/`keyCode 4` → fermer la modale, retirer `inert`, restaurer le focus sur l'élément déclencheur mémorisé.
6. Détecter l'ouverture via `MutationObserver` (si site tiers) sur le conteneur de modale (`[role=dialog]`, `.modal`, etc. — vérifier le vrai sélecteur) et basculer de zone automatiquement.
7. Scroll à l'intérieur de la modale : chaque focus sur une carte basse fait `scrollIntoView` dans le conteneur scrollable de la modale (pas la page).

```js
const observer = new MutationObserver(() => {
  const modal = document.querySelector(MODAL_SELECTOR);
  if (modal && state.zone !== 'modal') openModalScope(modal);
  if (!modal && state.zone === 'modal') closeModalScope();
});
observer.observe(document.body, { childList: true, subtree: true });
```

## 5. Touches à gérer

| Action | Valeurs |
|---|---|
| Haut/Bas/Gauche/Droite | `ArrowUp/Down/Left/Right` (keyCode 19/20/21/22 sur certaines TV) |
| OK | `Enter`, keyCode 13 / 23 → `element.click()` |
| Retour | `Escape`, `Backspace`, `BrowserBack`, keyCode 4 → fermer overlay, sinon `history.back()` |
| Lecture/Pause | `MediaPlayPause`, keyCode 85 / 179 |
| Avance/Retour rapide | `MediaFastForward` / `MediaRewind` (±10 s) |

## 6. Règles de design 10-foot

- Texte ≥ 24 px, zones cliquables ≥ 48 px, contraste élevé.
- Aucune interaction au survol (remplacer hover par focus).
- Marges de sécurité overscan 5 %.
- Focus : contour 3–4 px couleur d'accent + `transform: scale(1.05)` + transition courte.
- Pas de saisie clavier lourde (prévoir clavier virtuel ou recherche simplifiée).
- Lecteur vidéo : plein écran par défaut, barre de contrôle focusable, auto-masquage.

## 7. Vérification (toujours avant de conclure)

Tester au clavier uniquement (aucune souris) dans Chrome, puis sur émulateur Android TV :

- [ ] Bas répété parcourt les cartes ligne par ligne, sans scroll « libre »
- [ ] Haut depuis une ligne basse remonte ligne par ligne ; le menu n'est atteint qu'en haut de la grille
- [ ] Ouverture d'une modale : focus sur « Lecture », rien d'atteignable derrière
- [ ] Retour ferme la modale et restitue le focus sur la carte d'origine
- [ ] Focus toujours visible, jamais perdu (pas de `document.body` actif)
- [ ] Aucun piège de focus, aucun élément inatteignable

## 8. Format de réponse

1. Diagnostic court (cause racine du bug).
2. Code livré (JS + CSS) prêt à injecter / intégrer, avec les sélecteurs à adapter clairement marqués.
3. Étapes de test précises.
4. Mise à jour du journal ci-dessous.

## Journal des problèmes connus

> Ajouter une entrée à chaque nouveau problème résolu. Format : symptôme → cause → solution.

1. **Flèche Bas scrolle la page au lieu de passer à la vidéo suivante**
   → le scroll natif du navigateur capte la flèche, aucun gestionnaire de focus.
   → `keydown` capturé + `preventDefault()` + `findNext` spatial + `scrollIntoView` sur l'élément focalisé (§1, §2).

2. **En remontant après un scroll, le focus saute sur le menu avant de remonter tout en haut**
   → Haut n'a pas de notion de ligne : le « plus proche vers le haut » est le menu.
   → Règles de sortie de zone : menu atteint uniquement depuis la première ligne de la grille (§3).

3. **Ouverture d'une fiche (ex. modale « Matchbox ») : le focus reste sur la grille derrière**
   → pas de changement de zone ni de piège de focus à l'ouverture.
   → `MutationObserver` + `inert` sur l'arrière-plan + focus sur « Lecture » + restauration au Retour (§4).

4. **Bowd : Bas/Haut sautent sur une affiche ou un menu invisible, la page « défile » toute seule** (2026-10-21)
   → React Navigation garde les écrans précédents dans le DOM, sous l'écran courant, dans un ancêtre `aria-hidden="true"` ; ils restaient candidats.
   → `shown()` de `sitenav.js` exclut `e.closest('[aria-hidden="true"],[inert]')` (vérifié sur la TV par CDP : `adb forward tcp:9333 localabstract:webview_devtools_remote_<pid>`, l'APK debug est inspectable).

5. **Page d'un genre Bowd : le clavier s'ouvre, capte les flèches et décale la page**
   → le site focalise lui-même son champ de recherche à l'ouverture.
   → `focusin` en capture : un champ focalisé par le site (pas par la navigation) est `blur()` ; les flèches s'arrêtent sur un champ sans l'activer, OK l'active.

6. **Anneau de focus en retard, trop voyant, plus grand que la carte** (2026-10-21)
   → `transition` CSS sur un anneau déjà repositionné à chaque image ; contour fixe (4 px, coins 10 px, halo) autour de toute la carte, titre compris ; zoom 1.05 qui chevauchait la voisine (cartes Bowd à 2 px).
   → aucune transition ni zoom ; l'anneau suit la partie visible (`visual()` : image arrondie sans le titre) et en reprend `border-radius`.

7. **OpenFlix : après OK la fiche s'ouvre sans focus ; après Retour, focus perdu ou sur une autre carte**
   → la page met 2 à 5 s à se charger ; au retour, l'URL change avant que l'ancienne page disparaisse (mémoire écrasée) et l'accueil est reconstruit, remonté en haut, rangées déplacées.
   → `settleSoon()` réessaie toutes les 0,5 s pendant 8 s (après OK et sur `popstate`) ; mémoire en coordonnées du document, par page de l'élément, avec sa signature (`href`, image ou texte) pour retrouver la même carte.

8. **Accueil APK : tuiles blanches avec le nom de l'appli au lieu du logo** (2026-10-21)
   → `tv/logos/` est hors Git (marques déposées) : un APK construit depuis un worktree n'a aucun logo, et `tv.js` affiche alors le nom.
   → `preBuild` (`android-tv/app/build.gradle`) échoue si `tv/logos/` est vide ou absent ; lancer `python scripts/tv_logos.py` dans le worktree avant le build.

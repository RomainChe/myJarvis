# JARVIS — Plan de refonte graphique de la PWA (v2)

Statut : **implémentée le 2026-10-19 sur tous les onglets** (branche `feat/refonte-ui-v2`, cache v54), lots 1 à 6 livrés ensemble à la demande du propriétaire.
Base : captures 1920 px des 8 écrans du 2026-10-19 et code de `jarvis/web/` (cache v52).
Ce document remplace docs/DESIGN_SYSTEM.md pour les tokens (§3), les composants (§4) et la navigation (§5).

**Décisions du propriétaire (2026-10-19)** : D1 Inter + JetBrains Mono auto-hébergées (`jarvis/web/*.woff2`, licences OFL dans `licenses/`) ;
D2 rail à gauche sur PC ; D3 barre du téléphone = Dashboard, Finances, Réseaux, Conso, Plus ; D4 coins HUD sur les héros seulement ;
D5 texte courant à 16 px ; l'œil est gardé et enrichi (halo, cadran gradué, arcs de visée, étincelles, accélère quand Jarvis réfléchit).

**Écarts avec le plan ci-dessous** : rail de 84 px (icône + libellé dessous) jusqu'à 1 439 px, 232 px avec les groupes au-delà ;
la marque reste dans l'en-tête. Non faits (à ajouter si le besoin se confirme) : masquage du solde dans l'onglet Finances,
mini-courbes des KPI (Réseaux, Voyages), filtres du Journal, badge « problème » de Bien-être dans la navigation, squelettes de chargement.

Objectif : plus **lisible**, plus **beau**, plus **clair**, plus **cohérent**, sans changer d'identité :
fond nuit, accent cyan, coins de visée HUD, œil de particules. On garde le style, on retire le bruit.

---

## 1. Diagnostic (ce que montrent les captures)

### 1.1 Typographie : trop de monospace
- La police technique (Consolas/Cascadia) sert aux titres de cartes, aux montants, aux boutons, aux pastilles, aux noms de vidéos et à des valeurs longues (chemins, noms de pilotes). Le texte courant est en Segoe UI. Les deux se mélangent sur une même ligne : « Total épargné » (sans) et « Taux d'épargne » (mono) dans Finances, par exemple.
- Le monospace est lent à lire au-delà de 3 ou 4 mots. Dans Bien-être, les valeurs comme « 2 en attente : Intel net Driver Update (24.40.0.4)… » sont en mono gras sur 4 lignes.
- `Inter` figure dans `--j-font` mais n'est pas chargée : Windows affiche Segoe UI, Android affiche Roboto. Le rendu change d'un appareil à l'autre.
- Il existe 4 tailles (`xs` 11 px, `sm` 13 px, `md` 15 px, `lg` 20 px), plus des valeurs en dur (1.75rem, 1.875rem, 2.25rem). Il n'y a pas de vraie échelle.

### 1.2 Hiérarchie : 4 styles de titres de section
- Un sur-titre cyan en capitales (« COMPTES », « À AMÉLIORER »).
- Un sur-titre gris en capitales (« ABONNÉS », « MEILLEUR PRIX »).
- Un titre gras gris en casse normale (« Logement (compteur Linky) »).
- Un titre blanc de 20 px (« Conseils », « 30 derniers jours »).
- Le `h1` de chaque écran est masqué. Sur téléphone, l'onglet actif peut sortir de l'écran dans la barre défilante : on ne sait plus où on est.

### 1.3 Mise en page : l'écran large n'est pas maîtrisé
- À 1920 px, les cartes s'étirent sur toute la largeur. Les stats de Réseaux (« 2 », « 27 ») occupent chacune 450 px de vide. La carte « Consommation » de Finances est vide aux trois quarts. La ligne « Total consommation … 0,00 € » est à 1 500 px du montant.
- Dans Veille IA, le texte s'arrête vers 600 px mais la carte fait 1 850 px.
- Bien-être affiche 6 colonnes de 300 px : les conseils font 8 lignes, alors que des cartes à 3 colonnes seraient plus lisibles.
- Le menu bas de bureau (10 cartes de 48 px plus leurs marges) prend environ 90 px de hauteur en permanence, loin des titres de page.

### 1.4 Couleur : le cyan est partout, donc il ne signale plus rien
- Le cyan sert à la fois aux montants, aux liens, aux sur-titres, aux boutons, aux bordures, aux jauges et aux barres. Rien ne ressort.
- Finances utilise des couleurs hors tokens (`#6366f1` violet, `#10b981`, `#f59e0b` dans `.cyc-stack`), et ses bordures gauches violettes n'existent nulle part ailleurs.
- La pastille jaune « public » de Réseaux est illisible (texte jaune sur fond jaune). C'est un échec de contraste AA.
- Les niveaux N0 et N1 ont la même couleur. Seule la position les distingue.

### 1.5 Bruit visuel
- Toutes les cartes ont la même bordure, le même verre dépoli et les mêmes coins HUD. Quand tout est encadré, plus rien ne l'est vraiment.
- Les boutons « Ouvrir » (12 fois) et « Source · domaine » (une fois par article) sont de grosses pilules répétées. Ils prennent plus de place que l'information.
- Les icônes mélangent des emojis (💰 🏠 🌱 ✅ 🔶, rendus différemment selon le système) et des icônes SVG au trait.
- La barre de défilement native de Windows est grise et épaisse, et dépareille le thème.

### 1.6 Données
- Le graphique Conso n'a ni axe, ni valeur, ni repère « aujourd'hui ». Les jours sans mesure ressemblent à des jours à 0 kWh.
- La barre « Où est partie la paie » n'a ni légende colorée ni pourcentages sur la barre.
- Le format des nombres est mélangé : « 55.4 h », « 31.8 Go », « 13.2 °C » (point anglais) à côté de « 868,83 € » (virgule).
- Les états vides sont du texte brut (« Rien de programmé. », « Total consommation 0,00 € » dans une carte vide).

### 1.7 Téléphone (375 px)
- 10 onglets dans une barre qui défile à l'horizontale : la moitié des écrans est invisible et rien n'indique qu'on peut faire défiler.
- Les sélecteurs N0–N3 font 30 px de haut, sous la cible minimale de 44 px.
- Pas de titre de page, l'horloge est masquée et la place en haut est mal utilisée.
- Grandes cartes de stats en une colonne : il faut beaucoup défiler pour peu d'information.

### 1.8 Ce qui marche (à garder)
- L'œil de particules et la capsule de saisie lumineuse du Dashboard : c'est l'identité de l'app.
- Les jauges circulaires, la pastille « EN LIGNE » et les coins HUD sur les cartes principales.
- Les tokens `--j-*` déjà en place, le thème clair, `prefers-reduced-motion` et `prefers-contrast`.
- Les puces des aéroports dans Voyages (une carte sélectionnée et compacte) et les badges d'état de Bien-être.

---

## 2. Principes de la v2 (cinq règles)

1. **Le mono pour les nombres et les étiquettes, le sans-serif pour les mots.** Le monospace est réservé aux sur-titres en capitales, aux chiffres (`tabular-nums`), aux codes et aux heures. Les titres, les phrases et les boutons sont en sans-serif.
2. **Le cyan est un signal.** Il sert à l'action, au focus, à la sélection, au KPI principal de chaque carte et aux liens. Les autres valeurs sont en couleur de texte.
3. **Trois niveaux de surface.** Le fond. Les cartes, sans halo. Les cartes héros, avec coins HUD et léger halo (une ou deux par écran au plus).
4. **Une largeur de lecture.** Le contenu reste dans 1 440 px au plus. Les grilles se règlent seules avec `auto-fit/minmax` plutôt que par nombre fixe de colonnes. Le texte courant ne dépasse pas 70 caractères par ligne.
5. **Un même gabarit d'écran.** Chaque écran suit l'ordre en-tête de page → bande de KPI → sections. Chaque section a un seul style de titre, et chaque chargement prévoit les 4 états : chargement, vide, erreur, succès.

---

## 3. Tokens v2 (modifications de `:root` dans `app.css`)

### 3.1 Typographie
| Token | Valeur | Usage |
|---|---|---|
| `--j-font` | `"Inter", system-ui, "Segoe UI", Roboto, sans-serif` | texte, titres, boutons |
| `--j-font-tech` | `"JetBrains Mono", ui-monospace, "Cascadia Code", Consolas, monospace` | sur-titres, chiffres, codes |
| `--j-text-2xs` | 0.6875rem (11 px) | sur-titres en capitales uniquement |
| `--j-text-xs` | 0.75rem (12 px) | méta, horodatage |
| `--j-text-sm` | 0.875rem (14 px) | texte secondaire, boutons |
| `--j-text-md` | 1rem (16 px) | texte courant (actuellement 15 px) |
| `--j-text-lg` | 1.25rem (20 px) | titre de carte héros |
| `--j-text-xl` | 1.5rem (24 px) | titre de page, KPI de carte |
| `--j-text-2xl` | clamp(1.75rem, 1.2rem + 1.5vw, 2.5rem) | KPI héros (Dashboard, Réseaux) |

- Polices **auto-hébergées** en woff2 variable (Inter environ 100 Ko, JetBrains Mono environ 60 Ko en sous-ensemble latin), servies par le Core et mises en cache par `sw.js`, avec `font-display: swap`. Pas de Google Fonts : la PWA reste hors ligne et ne contacte aucun tiers.
- Texte courant à 16 px : Android ne zoome plus sur les champs et on gagne en lisibilité.
- `font-variant-numeric: tabular-nums` sur toutes les valeurs, par une classe `.num`.

### 3.2 Couleurs (sombre ; le clair suit la même logique)
On garde `bg`, `accent`, `success`, `warning` et `danger`. On ajoute :
| Token | Valeur | Rôle |
|---|---|---|
| `--j-color-surface-2` | `rgb(20 30 40 / .8)` | carte héros, carte survolée |
| `--j-color-border` | `rgb(56 207 239 / .10)` (au lieu de .16) | séparateurs plus discrets |
| `--j-color-text-2` | `#B8C6D3` | valeurs secondaires (entre text et muted) |
| `--j-color-info` | `#A78BFA` | N1 et 2ᵉ série de graphique, pour distinguer N0 de N1 |
| `--j-data-1..5` | cyan, violet `info`, vert, ambre, rose | séries de graphiques, validées en contraste avec le skill `dataviz` |
| `--j-color-*-soft` | couleur d'état à 12 % | fond des pastilles d'état (texte = couleur pleine) |

Règle pour les pastilles d'état : fond `*-soft`, texte et bordure en couleur pleine, jamais de texte sur un fond plein de la même teinte. Cela corrige « public ».

### 3.3 Surfaces, espacements, mouvements
- `--j-elev-0` : fond. `--j-elev-1` : carte (bordure `border`, pas de halo). `--j-elev-2` : héros (bordure `border-strong`, coins `.hud`, `--j-glow` atténué).
- Espacements : on garde l'échelle de 4 px et on ajoute `--j-space-10: 40px` et `--j-space-12: 48px` pour séparer les sections.
- Marge de page : `clamp(16px, 3vw, 40px)`. Largeur maximale du contenu : `--j-content-max: 1440px`.
- Barre de défilement : `scrollbar-width: thin; scrollbar-color: var(--j-color-border-strong) transparent;`.
- Mouvements : on garde 150 et 220 ms. On ajoute `--j-ease-out: cubic-bezier(.2, 0, 0, 1)` et `--j-motion-slow: 360ms` pour la feuille « Plus » sur téléphone.

---

## 4. Composants (inventaire unifié)

| Composant | Aujourd'hui | v2 |
|---|---|---|
| **En-tête de page** | `h1` masqué | `h1` visible (`xl`, sans-serif) + sous-titre `muted` (« Synchronisé il y a 3 min ») + actions à droite (rafraîchir, filtre). Remplace « Synchronisé avec GitHub… » et « Nouvelle mesure en cours… » qui flottaient en haut |
| **Titre de section** | 4 styles | un seul : sur-titre mono `2xs`, capitales, `muted`, avec un trait fin à droite (filet HUD) et un compteur optionnel (« À AMÉLIORER · 6 ») |
| **Tuile KPI** (`.stat`) | grande carte, valeur cyan | étiquette mono `2xs` → valeur `xl` mono (couleur texte, cyan seulement pour le KPI principal) → variation colorée (▲ +3 % en vert ou ▼ en rouge) → mini-graphique optionnel. Largeur 180 à 280 px, alignées en bande |
| **Carte** | bordure + verre + HUD partout | `elev-1` par défaut, `elev-2` + HUD pour les héros. Titre de carte en sans-serif 600 `md` avec icône SVG 18 px. Plus aucune bordure gauche colorée |
| **Ligne de liste** | variable selon l'écran | icône, titre (sans 500), méta (`xs` `muted`), puis valeur alignée à droite (mono, tabular). Toute la ligne est cliquable si elle mène quelque part |
| **Pastille d'état** | `.badge` / `.chip` / `.pill` différents | une seule `.tag` avec les variantes `ok`, `warn`, `bad`, `info` et `neutral` (fond soft, texte plein) |
| **Bouton** | pilule mono en capitales | sans-serif 600 `sm`, en casse normale ; `primary` (plein), `secondary` (soft), `ghost` (texte) et `icon` (44 × 44). Les capitales restent pour les sur-titres |
| **Lien externe** | grosse pilule « Source · x.com » | lien texte « x.com ↗ » en `sm`, ou toute la carte cliquable |
| **État vide** | phrase brute | icône 32 px `muted` + une phrase + une action si utile (« Aucune vidéo programmée · Ouvrir lol-clipper ») |
| **Chargement** | rien ou « … » | squelettes (`.skeleton` avec un shimmer de 1,2 s, coupé si `reduced-motion`) qui gardent la forme des cartes (CLS proche de 0) |
| **Icônes** | emojis + SVG | sprite SVG inline unique (style Lucide, trait 1,7 px). Aucun emoji dans l'interface. Les emojis des catégories Finances deviennent des icônes |
| **Graphique en barres** | barres sans axe | axe Y à 3 graduations, valeur au survol ou au toucher, jours sans mesure hachurés (et non à 0), dernière barre « aujourd'hui » en contour. Rendu en SVG ou CSS, sans bibliothèque |
| **Barre empilée** | 3 couleurs en dur | `--j-data-*` + légende sous la barre avec pastille, libellé, montant et % |
| **Segmenté N0–N3** | 30 px | 32 px avec la souris, 44 px au doigt (`@media (pointer: coarse)`). N1 prend la couleur `info` |
| **Disclosure** (`details`) | triangle + texte mono | chevron SVG qui pivote, titre sans 600 et résumé chiffré à droite (« 927 € ») |

---

## 5. Navigation

### 5.1 Regroupement des 10 écrans
| Groupe | Écrans |
|---|---|
| Accueil | Dashboard |
| Suivi | Finances, Conso, Réseaux, Voyages, Veille IA |
| Système | Bien-être, Appareils, Journal |
| Réglages | Réglages (en dernier, et non plus en 2ᵉ position) |

### 5.2 PC (≥ 900 px) : rail latéral à gauche
- Rail vertical de 72 px (icône + libellé court dessous). Il s'élargit à 220 px (icône + libellé à droite, titres de groupes) à partir de 1 440 px ou sur clic.
- Le menu bas disparaît, ce qui libère environ 90 px de hauteur. La navigation est près des titres, comme dans la plupart des tableaux de bord (Home Assistant, Grafana, Linear).
- Raccourcis `Alt+1…9` gardés et affichés dans une infobulle. `Alt+0` pour Réglages (Conso n'a pas de raccourci aujourd'hui).
- La marque « J.A.R.V.I.S » et l'orbe passent en haut du rail. L'en-tête garde l'horloge (centre) et l'état (droite), avec une hauteur réduite à 56 px.

### 5.3 Téléphone (< 900 px) : barre du bas à 5 entrées + feuille « Plus »
- Barre du bas fixe (Material 3 recommande 3 à 5 destinations) : **Accueil**, **Finances**, **Conso**, **Appareils**, **Plus**. Le choix des 4 premiers est la décision D3.
- « Plus » ouvre une feuille depuis le bas (`<dialog>` natif, glisser vers le bas ou Échap pour fermer) avec une grille 3 × 2 des autres écrans et un badge si un écran signale un problème (par exemple Bien-être « 1 »).
- Le dernier écran ouvert depuis « Plus » remplace temporairement l'icône « Plus » (indicateur actif), pour qu'on voie toujours où on est.
- En-tête mobile de 52 px : titre de la page à gauche, point d'état à droite (la pastille complète « EN LIGNE » apparaît au toucher), micro.
- Zone du pouce : les actions principales (envoyer, parler, confirmer) restent en bas. Les dialogues N2/N3 sont déjà des feuilles basses, on garde.

---

## 6. Écran par écran

Chaque écran suit le gabarit §2.5. Mobile = 375 px, PC = 1280 et 1920 px.

**Dashboard.** Garder l'œil et la capsule de saisie. Colonnes latérales en `elev-1` (plus légères), sauf Système en héros. Veille IA à droite : afficher les **titres** des 2 premiers articles (pas « Source / Source »). Placeholder de la capsule en casse normale (« Parler à Jarvis… »), plus lisible. *Mobile :* bande de KPI défilante en `scroll-snap` (Système, Météo, Conso, Finances) au-dessus de la conversation, puis l'œil en fond plus petit (35 % d'opacité).

**Finances.** En-tête : solde du compte en KPI héros (nom du titulaire masqué par défaut, avec le même bouton « Afficher » que sur le Dashboard). Bande de 4 KPI (paie, fixes, épargne, reste) avec la part de la paie en mini-barre. La barre « Où est partie la paie » prend la légende chiffrée. Les 3 colonnes (fixes, épargne, consommation) passent en `auto-fit minmax(320px, 1fr)` et une carte vide se réduit à son état vide. Emojis → icônes. *Mobile :* 4 KPI en grille 2 × 2, sections repliables.

**Réseaux.** 4 KPI compacts en bande (pas 4 cartes géantes), avec la variation 7 j en tête et non dans une carte à part. Publications : liste dense (titre lisible : la date et l'heure sortent du nom de fichier, puis « Renekton · compilation » ; plateforme en icône ; vues alignées à droite). Toute la ligne ouvre la vidéo, ce qui supprime les 12 boutons « Ouvrir ». Pastille « public » corrigée. *Mobile :* même liste en une colonne.

**Veille IA.** Cartes article de 720 px au plus (lecture), en 2 colonnes à partir de 1 440 px. Note en pastille à droite (« 92 »), statut en icône, la phrase « pour toi » mise en avant par un filet cyan à gauche, source en lien texte. Semaines plus anciennes repliées.

**Voyages.** Une carte par recherche avec le prix en en-tête du `details`, plus la tendance (▲▼ par rapport au relevé précédent) et un mini-graphique des relevés. Les 3 KPI deviennent une ligne de stats dans la carte. Les puces d'aéroports sont gardées. « Voir l'offre » devient un bouton secondaire.

**Conso.** Deux blocs titrés (« PC », « Logement ») avec chacun une bande de 3 KPI. Graphique refait selon §4 (axe, survol, jours manquants hachurés). Prix du kWh : champ compact avec son unité, dans un panneau « Paramètres » replié en bas (pas un champ de 1 800 px). « 55.4 h » devient « 55,4 h ».

**Bien-être.** Bande de 3 KPI cliquables (filtre). Cartes en `auto-fit minmax(340px, 1fr)` : pastille d'état, titre, **valeur courte** en sans-serif 600 (les chemins et versions passent en mono `xs` dans un `details`), puis conseil. Les actions possibles (« Nettoyer », simulation) deviennent des boutons dans la carte, avec leur niveau affiché.

**Réglages.** Recherche en haut (filtre la liste des outils), groupes repliables avec en-têtes collants (PC, Maison, Données…), une colonne sous 1 200 px et deux au-delà. Le segmenté affiche le niveau courant en clair (« N1 · automatique ») pour les lecteurs d'écran. Clé d'accès et Notifications en tête, en cartes `elev-2`.

**Appareils et Journal.** Appliquer la ligne de liste et les pastilles unifiées. Journal : filtres (niveau, décision, période) en puces au-dessus du tableau ; sur mobile, une carte par ligne (déjà fait).

---

## 7. Décisions du propriétaire

- **D1 — Polices** : (a) Inter + JetBrains Mono auto-hébergées, environ 160 Ko, recommandé ; (b) polices système uniquement (0 Ko, rendu différent sur PC et Android).
- **D2 — Navigation PC** : (a) rail latéral à gauche, recommandé ; (b) garder le menu bas, compacté à 56 px en icônes et libellés.
- **D3 — Les 4 entrées fixes du téléphone** : proposition Accueil, Finances, Conso, Appareils, à remplacer selon l'usage réel (le Journal d'audit pourrait servir à compter les ouvertures).
- **D4 — Coins HUD** : uniquement sur les cartes héros (recommandé) ou gardés partout.
- **D5 — Texte à 16 px** (recommandé) ou 15 px actuel.

---

## 8. Découpage en lots (un lot = une branche, un passage QA puis Sécurité)

| Lot | Contenu | Fichiers | Risque |
|---|---|---|---|
| 1 | Tokens v2 (échelle typo, couleurs, surfaces, scrollbar, polices) | `app.css`, `index.html`, `sw.js` (+ polices) | faible : visuel seul |
| 2 | Composants partagés : en-tête de page, titre de section, KPI, `.tag`, boutons, état vide, squelette, sprite d'icônes | `app.css`, `index.html`, `app.js` (helpers `el`/`stat`) | moyen : touche tous les écrans |
| 3 | Navigation : rail PC, barre 5 entrées + feuille « Plus » mobile | `index.html`, `app.css`, `app.js` | moyen : clavier et focus à retester |
| 4 | Écrans de données : Finances, Réseaux, Conso (graphique), Bien-être | `*.js` par écran, `app.css` | moyen |
| 5 | Écrans restants : Veille, Voyages, Réglages (recherche), Appareils, Journal, Dashboard | `*.js`, `app.css` | faible |
| 6 | Thème clair repassé, contrastes mesurés, mise à jour de DESIGN_SYSTEM.md, suppression du CSS mort | docs + `app.css` | faible |

Chaque lot incrémente le cache de `sw.js`.

**Vérifications de chaque lot**
- `python -m unittest discover -s tests`.
- Playwright à 375, 1280 et 1920 px sur les 10 écrans : aucun débordement horizontal, console et réseau propres, 4 états (API simulée vide, en erreur et remplie).
- Clavier (Tab, Échap, `Alt+n`), snapshot d'accessibilité, contrastes ≥ 4,5:1 (texte) et ≥ 3:1 (composants), cibles ≥ 44 px au doigt.
- Sécurité : aucune donnée sensible visible par défaut (solde, titulaire) et pas d'`innerHTML` sur des données (les écrans utilisent déjà `el()`). Le niveau N2/N3 reste visible avant toute action.
- Le CSP reste inchangé : polices servies par le Core (`font-src 'self'`).

## 9. Références appliquées
- WCAG 2.2 AA (1.4.3 contraste, 1.4.11 contraste non textuel, 2.5.8 taille des cibles) ; RGAA 4.
- Material 3 : barre de navigation (3 à 5 destinations), navigation rail, bottom sheet.
- Apple HIG : tab bars, zone du pouce, Dynamic Type (échelle de texte relative).
- Tableaux de bord de référence pour la densité : Home Assistant, Grafana, Linear et Vercel (KPI en bande, une couleur d'accent, mono réservé aux chiffres).
- Lisibilité du monospace : on le garde pour les nombres alignés (`tabular-nums`) et les codes, pas pour les phrases.

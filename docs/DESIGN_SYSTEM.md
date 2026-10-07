# JARVIS — Design system (préparation Phase 3)

Statut : **proposition de l'Expert UX/UI**, à valider par le Manager, la Sécurité et le propriétaire.
La Phase 3 n'est pas lancée : ce document ne contient aucun code d'application.
Cible : une seule PWA responsive servie par le Core (ARCHITECTURE §3.5), **mobile d'abord**.

## 1. Principes appliqués
1. L'état avant l'action : on voit d'abord ce qui est allumé, ouvert, en marche.
2. Retour < 100 ms : affichage optimiste, puis confirmation ou retour arrière.
3. Calme : une seule couleur d'accent, les couleurs d'état ne servent qu'aux états.
4. Le niveau de permission (N0 à N3) est toujours visible avant et après une action sensible.
5. Sans LLM, l'app reste utilisable : appareils et réglages ne dépendent pas d'Ollama.

## 2. Tokens

Nommage : `--j-<famille>-<rôle>` (variables CSS), un seul fichier de tokens partagé.

### 2.1 Couleurs
Thème sombre par défaut, clair disponible ; `prefers-color-scheme` décide au premier lancement.
Contrastes calculés selon la formule WCAG 2.1 (luminance relative). AA : texte ≥ 4,5:1, contrôles et
icônes ≥ 3:1.

| Token | Sombre | Clair | Usage |
|---|---|---|---|
| `bg` | `#121418` | `#F5F6F8` | fond de page (pas de noir pur) |
| `surface` | `#1B1E24` | `#FFFFFF` | cartes, barres |
| `raised` | `#252932` | `#ECEEF2` | carte active, survol, champ |
| `text` | `#E8EAED` | `#15181D` | texte principal |
| `muted` | `#A3A9B5` | `#565D6B` | texte secondaire, horodatage |
| `border` | `#2C313A` | `#DADDE3` | séparateurs décoratifs uniquement |
| `border-strong` | `#6E7582` | `#7A818E` | contour de champ, d'interrupteur éteint |
| `accent` | `#38CFEF` | `#0A6F91` | cyan : actif, focus, action principale |
| `on-accent` | `#0B1A20` | `#FFFFFF` | texte posé sur l'accent |
| `success` | `#4ADE80` | `#18753A` | OK, appareil en ligne |
| `warning` | `#FBBF24` | `#8F5300` | N2, attention, délai |
| `danger` | `#F87171` | `#C0262D` | N3, erreur, refus |

Contrastes mesurés (texte sur `bg` / `surface` / `raised`) :

| Token | Sombre | Clair | Verdict |
|---|---|---|---|
| `text` | 15,3 / 13,9 / 12,1 | 16,5 / 17,8 / 15,3 | AAA |
| `muted` | 7,8 / 7,1 / 6,2 | 6,1 / 6,6 / 5,7 | AA |
| `accent` | 10,0 / 9,0 / 7,9 | 5,3 / 5,7 / 4,9 | AA (texte) |
| `success` | 10,6 / 9,6 / 8,4 | 5,3 / 5,8 / 5,0 | AA |
| `warning` | 11,0 / 10,0 / 8,7 | 5,7 / 6,2 / 5,3 | AA |
| `danger` | 6,7 / 6,0 / 5,3 | 5,5 / 5,9 / 5,1 | AA |
| `border-strong` | 4,0 / 3,6 / 3,1 | 3,6 / 3,9 / 3,4 | ≥ 3:1 (contrôles) |
| `on-accent` sur `accent` | 9,6 | 5,7 | AA |
| `on-accent` sur `danger` | 6,4 | 5,9 | AA (bouton N3) |

Règles :
- `border` (1,3:1) ne délimite jamais seul un contrôle : un interrupteur ou un champ utilise `border-strong`.
- La couleur n'est jamais le seul signal : chaque état a aussi une icône et un libellé (« Allumé », « N2 »).
- Mode « contraste élevé » (`prefers-contrast: more`) : `muted` prend la valeur de `text`, `border` celle de `border-strong`.

### 2.2 Typographie
- Police : **Inter** (variable, auto-hébergée par le Core : aucune requête vers un CDN) ; repli `system-ui`.
- Trois tailles seulement, en `rem` pour suivre la taille de police du système :

| Token | Taille | Interligne | Graisse | Usage |
|---|---|---|---|---|
| `text-sm` | 0,8125 rem (13 px) | 1,4 | 400 | horodatage, badges, aide |
| `text-md` | 1 rem (16 px) | 1,5 | 400 / 500 | corps, chat, libellés |
| `text-lg` | 1,375 rem (22 px) | 1,3 | 600 | titres d'écran, valeur d'un appareil |

- Chiffres tabulaires (`font-variant-numeric: tabular-nums`) pour l'heure, la température, le volume.
- 16 px minimum dans les champs (évite le zoom automatique sur Android).
- L'interface tient à 200 % de zoom sans perte de contenu (WCAG 1.4.4).

### 2.3 Espacements, rayons, ombres
| Famille | Valeurs |
|---|---|
| Espacement (base 4 px) | `space-1` 4 · `space-2` 8 · `space-3` 12 · `space-4` 16 · `space-6` 24 · `space-8` 32 |
| Rayon | `radius-sm` 6 (badge, champ) · `radius-md` 12 (carte) · `radius-lg` 20 (feuille, dialogue) · `radius-full` (pastille, orbe) |
| Ombre sombre | pas d'ombre : l'élévation se lit par `surface` → `raised` |
| Ombre clair | `shadow-1` `0 1px 2px rgb(0 0 0 / .06)` · `shadow-2` `0 8px 24px rgb(0 0 0 / .12)` (dialogue) |
| Cible tactile | `target` 44 px minimum, 48 px pour les boutons de confirmation |
| Gouttière | 16 px sur mobile, 24 px au-delà de 768 px |
| Points de rupture | `sm` < 600 · `md` 600–1023 · `lg` ≥ 1024 |

### 2.4 Animation
| Token | Durée | Courbe | Usage |
|---|---|---|---|
| `motion-fast` | 150 ms | `ease-out` | interrupteur, survol, retour optimiste |
| `motion-base` | 200 ms | `cubic-bezier(.2,0,0,1)` | ouverture de carte, toast |
| `motion-slow` | 250 ms | idem | feuille de confirmation, changement d'écran |
| `motion-orb` | 1,6 s en boucle | `ease-in-out` | orbe : écoute, réflexion |

`prefers-reduced-motion: reduce` : toutes les durées passent à 0 ms sauf l'orbe, qui devient un
changement de couleur fixe par état (repos, écoute, réflexion, parole).

## 3. Composants clés

Communs à tous : focus visible (anneau `accent` 2 px, décalé de 2 px), navigation clavier complète sur
PC, libellés lisibles par TalkBack, aucune information portée par la seule couleur.

### 3.1 Chat (fil de conversation)
Anatomie : bulle utilisateur (alignée à droite, `raised`) · réponse JARVIS (alignée à gauche, sans
bulle) · **carte d'action** insérée dans le fil pour chaque outil exécuté · barre de saisie en bas
(champ + bouton micro + bouton envoyer).

Carte d'action : `[icône outil] Volume réglé à 30 %  · N1 · 14:02  [Annuler]`. Le bouton « Annuler »
n'apparaît que si l'outil est réversible.

| État | Rendu |
|---|---|
| vide | 4 suggestions en puces (« Allume le salon », « État du PC »…) |
| envoi | bulle utilisateur affichée tout de suite, orbe en « réflexion » |
| routeur local | réponse sans orbe (< 1 s), mention discrète « direct » dans le détail |
| LLM en chargement | « Le modèle se charge (≈ 10 s). Les commandes simples marchent déjà. » |
| LLM indisponible | bandeau `warning` + lien vers l'écran Appareils |
| confirmation requise | carte d'action en `warning`/`danger` avec bouton « Vérifier » → dialogue §3.4 |
| erreur d'outil | carte `danger` : ce qui a échoué en clair, détail technique repliable |
| PC injoignable | écran plein « PC injoignable : JARVIS et la domotique sont à l'arrêt », pas d'erreur technique |

Accessibilité : le fil est un `role="log"` avec `aria-live="polite"` ; le champ a un libellé visible
« Demander à Jarvis » ; Entrée envoie, Maj+Entrée va à la ligne ; le texte venu d'un contenu externe
(nom d'appareil, fichier) est rendu en texte brut, jamais en HTML.

### 3.2 Carte d'appareil
Anatomie : icône · nom · pièce · état en texte (« Allumé · 21 °C ») · contrôle principal
(interrupteur, curseur ou boutons ▲ ■ ▼ pour un volet). Appui long / clic droit → détail.

| État | Rendu |
|---|---|
| éteint / fermé | `surface`, icône `muted`, libellé « Éteint » |
| actif | `raised`, icône et bord gauche `accent`, libellé de l'état |
| en cours (optimiste) | l'état change tout de suite, petit indicateur tournant ; au bout de 5 s sans réponse, retour à l'état précédent + toast « La clim du salon ne répond pas » |
| hors ligne | icône barrée, libellé « Hors ligne », contrôles désactivés mais focusables (pour lire la raison) |
| action N2+ | badge `N2` / `N3` sur le contrôle ; l'action ouvre le dialogue §3.4 au lieu d'agir |
| chargement | squelette de la forme de la carte, sans animation si mouvement réduit |

Accessibilité : un interrupteur est un `role="switch"` avec `aria-checked` ; un volet a trois boutons
nommés (« Monter le volet du salon »…) ; un curseur annonce valeur et unité (« Température, 21 degrés ») ;
cible ≥ 44 px même si la carte est compacte.

### 3.3 Entrée du journal d'audit
Une ligne par action, en lecture seule (le journal est en ajout seul, l'UI n'offre aucune suppression).

```
14:02  [icône] Volume réglé à 30 %           N1  Auto       ✓
       PC · CLI
14:05  [icône] Mise en veille du PC          N2  Confirmé   ✓
       Téléphone · PWA
14:07  [icône] Suppression rapport.pdf       N2  Refusé     —
       PC · Voix
```

- Colonnes : heure locale, description lisible (pas le nom technique), niveau, décision, résultat.
- Décision : `Auto` (neutre), `Confirmé` (`success`), `Refusé` (`danger`), `Invalide` / `Inconnu` (`warning`).
- Résultat : ✓ succès, ✕ erreur (texte en clair), — non exécuté.
- Détail dépliable : paramètres, horodatage UTC complet, source. Les paramètres sensibles sont masqués
  (voir §5.1).
- États : vide (« Aucune action pour l'instant »), chargement (squelettes), erreur de lecture, filtre sans résultat.
- Accessibilité : une liste de `<article>` regroupée par jour (titres « Aujourd'hui », « Hier ») ;
  chaque ligne se lit comme une phrase : « 14 h 05, mise en veille du PC, niveau 2, confirmé, réussi ».

### 3.4 Dialogue de confirmation N2 / N3 (composant unique, validé par la Sécurité)
Sur mobile : feuille montant du bas, sur PC : dialogue centré de 440 px. Il remplace toute
confirmation ad hoc.

```
┌──────────────────────────────────┐        ┌──────────────────────────────────┐
│ ⚠ Action sensible · N2           │        │ ⛔ Action critique · N3           │
│                                  │        │                                  │
│ Mettre le PC en veille           │        │ Baisser « screenshot » de N2 à N1│
│                                  │        │                                  │
│ Ce qui va se passer :            │        │ Ce qui va se passer :            │
│ • Le PC passe en veille.         │        │ • Les captures d'écran ne        │
│ • JARVIS et Home Assistant       │        │   demanderont plus de            │
│   seront coupés jusqu'au réveil. │        │   confirmation.                  │
│                                  │        │                                  │
│ Demandé par : vous, PWA, 14:05   │        │ Demandé par : vous, PWA, 14:10   │
│ ▸ Détails techniques             │        │ ▸ Détails techniques             │
│                                  │        │                                  │
│ [   Annuler   ] [  Confirmer  ]  │        │ [ Annuler ] [ ◉ Empreinte ]      │
└──────────────────────────────────┘        │        Utiliser le code PIN      │
                                            └──────────────────────────────────┘
```

Règles :
- Le titre est un verbe + l'objet, en français courant, généré par l'outil (pas par le LLM).
- « Ce qui va se passer » liste les conséquences, dont les irréversibles en premier.
- **Annuler a le focus par défaut**, est à gauche et de même taille ; Échap et le geste retour annulent.
- N2 : bouton « Confirmer » en `accent`. N3 : bouton en `danger`, qui déclenche WebAuthn
  (empreinte) ; lien secondaire « Utiliser le code PIN » → pavé numérique, chiffres masqués.
- Si la demande vient d'un tour où du contenu externe a été lu (ARCHITECTURE §4.3), bandeau `warning` :
  « Cette action a été proposée après la lecture de [source]. Vérifiez qu'elle vient bien de vous. »
- Expiration : 60 s (valeur à fixer par la Sécurité), compte à rebours en texte ; à l'échéance, refus
  journalisé et message « Demande expirée, rien n'a été fait ».
- Pas de double validation par erreur : le bouton se désactive dès le premier appui.

| État | Rendu |
|---|---|
| attente | dialogue ouvert, compte à rebours |
| vérification | bouton en chargement, autres contrôles désactivés |
| succès | le dialogue se ferme, la carte d'action passe en ✓ |
| refus / annulation | fermeture, toast « Annulé, rien n'a été fait » |
| échec biométrie | « Empreinte non reconnue », 3 essais puis PIN seul ; erreurs sans détail technique |
| PIN faux | « Code incorrect », compteur d'essais restants, blocage temporaire (durée fixée par la Sécurité) |
| WebAuthn indisponible (PC sans lecteur) | « Confirmez sur votre téléphone » + notification push vers l'appareil enrôlé |

Accessibilité : `role="alertdialog"`, `aria-labelledby` sur le titre, `aria-describedby` sur
« Ce qui va se passer » ; focus piégé dans le dialogue et rendu à l'élément d'origine à la fermeture ;
le compte à rebours n'est annoncé qu'à 10 s de la fin (pas à chaque seconde).

### 3.5 Petits composants (à détailler en Phase 3)
Bouton (principal, secondaire, danger, fantôme), interrupteur, curseur, toast (5 s, `aria-live`,
action « Annuler » si réversible), badge de niveau `N0`–`N3`, orbe JARVIS, bandeau d'état de connexion.
Icônes : **Lucide** (licence ISC), auto-hébergées.

## 4. Les quatre écrans (wireframes basse fidélité, mobile 360 px)

Navigation : barre d'onglets en bas sur mobile (Chat · Appareils · Journal · Réglages), barre latérale
sur PC (≥ 1024 px). Bandeau d'état en haut si le LLM, Home Assistant ou le réseau est indisponible.

### 4.1 Chat
Objectif : demander n'importe quoi, voir ce qui a été fait.
```
┌────────────────────────────────┐
│ ◉ Jarvis               ● prêt  │
├────────────────────────────────┤
│                  Baisse le son │
│                       à 30 % ▕ │
│ ┌────────────────────────────┐ │
│ │ 🔊 Volume réglé à 30 %     │ │
│ │ N1 · direct · 14:02 Annuler│ │
│ └────────────────────────────┘ │
│              Mets le PC en     │
│                       veille ▕ │
│ ┌────────────────────────────┐ │
│ │ ⚠ Mise en veille du PC     │ │
│ │ N2 · en attente  [Vérifier]│ │
│ └────────────────────────────┘ │
│                                │
├────────────────────────────────┤
│ [ Demander à Jarvis…    ] 🎤 ➤ │
├────────────────────────────────┤
│  Chat  Appareils Journal Régl. │
└────────────────────────────────┘
```
États : vide (suggestions), chargement du modèle, LLM indisponible, PC injoignable, erreur d'outil (§3.1).

### 4.2 Appareils
Objectif : l'état de la maison et du PC d'un coup d'œil, les actions fréquentes en un geste.
```
┌────────────────────────────────┐
│ Appareils                      │
│ [Cinéma] [Je pars] [Bonne nuit]│  ← scènes favorites
├────────────────────────────────┤
│ Actifs (2)                     │
│ ┌─────────────┐┌─────────────┐ │
│ │▌❄ Clim salon││▌📺 TV       │ │
│ │ Chauffe 21° ││ Allumée     │ │
│ │ [−]  21 [+] ││ [■ on ]     │ │
│ └─────────────┘└─────────────┘ │
│ Salon                          │
│ ┌─────────────┐┌─────────────┐ │
│ │ ▤ Volet     ││ 🔊 Barre son│ │
│ │ Fermé       ││ Éteinte     │ │
│ │ [▲][■][▼]   ││ [  off]     │ │
│ └─────────────┘└─────────────┘ │
│ Chambre ▸   PC ▸               │
├────────────────────────────────┤
│  Chat  Appareils Journal Régl. │
└────────────────────────────────┘
```
États : vide (« Aucun appareil : Home Assistant n'est pas encore relié »), chargement (squelettes),
HA injoignable (cartes grisées + bandeau, l'onglet PC reste utilisable), succès (état à jour).
PC (≥ 1024 px) : grille de 4 colonnes, pièces en sections.

### 4.3 Journal
Objectif : savoir qui a fait quoi, quand, et avec quel résultat.
```
┌────────────────────────────────┐
│ Journal                    ⌕   │
│ [Tout][N2+][Refusés][Erreurs]  │
├────────────────────────────────┤
│ Aujourd'hui                    │
│ 14:07 Suppr. rapport.pdf  N2   │
│       Voix · Refusé         —  │
│ 14:05 Veille du PC        N2   │
│       PWA · Confirmé        ✓  │
│ 14:02 Volume 30 %         N1   │
│       CLI · Auto            ✓  │
│ Hier                           │
│ 22:41 Volet salon fermé   N1   │
│       PWA · Auto            ✓  │
│          [Charger plus]        │
├────────────────────────────────┤
│  Chat  Appareils Journal Régl. │
└────────────────────────────────┘
```
États : vide, chargement, erreur de lecture, filtre sans résultat (§3.3). Pagination par 50.

### 4.4 Réglages des niveaux
Objectif : voir et ajuster le niveau de chaque outil. Baisser un niveau est N3 (ARCHITECTURE §4.4).
```
┌────────────────────────────────┐
│ ‹ Réglages · Permissions       │
│ ⌕ Rechercher un outil          │
├────────────────────────────────┤
│ PC                             │
│ Volume              N1  [▾]    │
│ Capture d'écran     N2  [▾]    │
│ Arrêt / veille      N2  [▾]    │
│ Commande libre      N3 🔒      │
│ Maison                         │
│ Volets              N1  [▾]    │
│ Chauffage coupé     N2  [▾]    │
├────────────────────────────────┤
│ N0 lecture · N1 courant ·      │
│ N2 confirmation · N3 empreinte │
└────────────────────────────────┘
```
- Le sélecteur propose N0 à N3 avec une phrase par niveau ; monter un niveau s'applique tout de suite
  (N1), le baisser ouvre le dialogue N3.
- 🔒 = plancher imposé par la Sécurité (non abaissable), avec la raison en texte.
- La valeur par défaut est rappelée (« par défaut : N2 ») et un lien « Rétablir ».
États : chargement, erreur d'enregistrement (retour à l'ancienne valeur + toast), succès (toast).

## 5. Ce que l'UX attend des autres experts

### 5.1 De la Sécurité
1. Valider le composant de confirmation §3.4 comme **unique** chemin N2/N3, et fixer : délai
   d'expiration, nombre d'essais PIN, durée de blocage, longueur du PIN.
2. Pour chaque outil, une **description lisible** et une liste de **conséquences** fournies par le Core
   (pas par le LLM), pour le titre et « Ce qui va se passer ».
3. La liste des **paramètres sensibles** à masquer dans le journal et les détails (chemins personnels,
   contenu du presse-papiers…), et la règle d'affichage (masqué, révélé après biométrie ?).
4. Les **planchers** de niveau non abaissables (ex. commande libre N3).
5. Le flux d'**enrôlement** par QR code et l'écran de révocation des appareils (à concevoir ensemble).
6. Le marquage « contenu externe lu dans ce tour » transmis par le Core avec chaque demande de confirmation.
7. Le comportement quand le PC n'a pas de lecteur biométrique : confirmation N3 relayée au téléphone ?

### 5.2 De la Domotique
1. Pour chaque appareil : pièce, type, **état lisible** (« Chauffe 21 °C »), contrôles possibles et
   niveau de chaque action, issus de Home Assistant.
2. Un **délai de réponse type** par appareil (le cloud MELCloud est plus lent que Shelly en local),
   pour régler le retour arrière de l'affichage optimiste.
3. Les états intermédiaires réels (volet en mouvement, position en %, clim en dégivrage).
4. Les scènes favorites (3 à 5) et leur contenu, pour l'écran Appareils et les raccourcis Android.
5. Un événement temps réel (WebSocket HA relayé par le Core) plutôt qu'un sondage, pour l'état.
6. Le nombre de volets et de pièces (question déjà en attente), pour dimensionner la grille.

## 6. Avis sur l'interface texte actuelle (`python -m jarvis`)

Constats (testés le 2026-10-07, aucun outil encore enregistré) :

| # | Constat | Effet |
|---|---|---|
| 1 | La confirmation affiche `Confirmer power {'action': 'veille'} ? [o/N]` : nom technique et dictionnaire Python | on ne sait ni ce qui va se passer ni quel niveau est en jeu |
| 2 | Pas de conséquence affichée, alors que la Sécurité exige que la veille/l'arrêt rappellent la coupure de Jarvis et HA | condition du feu vert Phase 1 non couverte côté CLI |
| 3 | Un refus affiche `power refusé` | ambigu : on ne sait pas que rien n'a été fait |
| 4 | `audit` imprime des lignes brutes séparées par `\|`, sans en-tête, heure UTC ISO, niveau en entier, arguments en JSON | illisible au-delà de 3 lignes ; l'heure ne correspond pas à l'heure locale |
| 5 | `audit abc` lève une trace Python (`int()` non protégé) | erreur technique montrée à l'utilisateur |
| 6 | Messages d'erreur en minuscules sans piste (« outil inconnu : x ») | aucune aide pour trouver le bon nom |
| 7 | Aucune commande pour lister les outils et leur niveau | il faut lire le code |
| 8 | Le message N3 est clair et honnête | à garder tel quel |

Propositions (petites, sans dépendance, à confier au Développeur généraliste si le Manager valide) :
1. Confirmation sur plusieurs lignes, même structure que le dialogue §3.4 :
   ```
   ⚠ Action sensible (N2) : Mettre le PC en veille
     • JARVIS et Home Assistant seront coupés jusqu'au réveil.
     action = veille
   Confirmer ? [o/N]
   ```
   Cela suppose que `Tool` porte un champ optionnel de conséquences (à valider avec la Sécurité).
2. Refus : « Annulé : rien n'a été fait. » ; outil inconnu : « Outil inconnu : x. Voir `python -m jarvis tools`. »
3. `audit` : tableau à colonnes alignées avec en-tête, heure **locale** `HH:MM`, niveau `N2`,
   décision et résultat tronqués ; option `--json` pour la sortie brute.
4. Nouvelle sous-commande `tools` : nom, niveau, description, une ligne par outil.
5. Argument `n` d'`audit` validé (« n doit être un nombre entier »), pas de trace Python.
6. Majuscule en début de message, et sortie non nulle documentée dans l'aide.

## 7. Décisions à prendre (propriétaire)
1. Thème sombre par défaut et accent cyan : à confirmer.
2. Police Inter auto-hébergée (sinon : police du système, zéro fichier à servir).
3. Icônes Lucide.
4. Navigation à 4 onglets (Chat, Appareils, Journal, Réglages) : l'accueil mobile prévu par le prompt
   UX (scènes + appareils actifs + micro) est fusionné dans l'onglet Appareils pour rester à 4 écrans.
5. Lancer ou non les améliorations de la CLI (§6) dès la Phase 1.

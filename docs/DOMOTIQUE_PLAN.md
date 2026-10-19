# JARVIS — Plan domotique

Statut : Phase 2 en place (Home Assistant sur le mini-PC, voir docs/INSTALL_SERVEUR_HA.md ; l'ancienne VM Hyper-V est à supprimer, MIGRATION lot 5 C). Ce document ne contient aucune IP ni nom de réseau.
Principes (ARCHITECTURE §3.4) : HA est le hub unique, priorité au local, JARVIS parle à HA avec un utilisateur dédié non administrateur. Chaque appareil reste utilisable à la main et via l'appli du fabricant, les plannings restent dans les appareils.
Sauvegardes HA : quotidiennes, 7 conservées, chiffrées (clé dans le gestionnaire de mots de passe) ; destination hors du mini-PC encore à décider (ROADMAP). HA Cloud exclu (budget 0 €).

## Appareils
Légende : N0 lecture, N1 courant, N2 sensible (confirmation), N3 critique. Niveau d'une scène = le plus haut de ses actions.

- **TV Continental Edison (Google TV)** : intégrations *Android TV Remote* (locale, découverte auto) + *Google Cast* (média, état de lecture). Pas de retour d'état de lecture via Remote ; TV joignable en veille (confirmé). Chaîne TNT = touches numériques ou ouverture d'une appli (à tester). Secours : télécommande. N0 état ; N1 allumer/éteindre, volume, muet, source, chaîne, appli, cast.
- **Barre de son Samsung HW-S50B** : ni SmartThings ni Wi-Fi ; pilotée **via la TV en HDMI-CEC** (allumage et volume suivent la TV). Pas de retour d'état propre. Si le CEC ne suffit pas : Broadlink RM4 mini (~25 €). N1.
- **Clims Mitsubishi MSZ-HR25VFK2 (salon, chambre) = chauffage** : pas de Wi-Fi intégré (connecteur CN105). Option A retenue par le propriétaire : adaptateur officiel (MELCloud / MELCloud Home), **cloud Mitsubishi, Internet obligatoire, signalé à la Sécurité**, latence 1 à 5 s. Option B écartée : ESP32 + ESPHome (local, ~15-30 €, ouvre l'unité). Intégration des clims **reportée** (2026-10-13). N0 état ; N1 consigne 17–24 °C, mode, ventilation ; N2 éteindre le chauffage ou consigne hors plage. Règle voulue : baie vitrée ouverte → clim de la pièce coupée (capteur Shelly BLU Door/Window ~20 €, programmée par le propriétaire, validation Sécurité car coupure = N2) ; consignes éco/nuit à fixer.
- **Plafonnier LED TYJY 105 W du salon** (télécommande RF propriétaire) : **Shelly 1 Mini Gen3/Gen4 (~15-20 €, neutre requis)** derrière l'interrupteur mural, intégration *Shelly* locale ; marche/arrêt seulement, luminosité à la télécommande. Prérequis : neutre dans la boîte, la lampe doit se rallumer seule après coupure. N0 état ; N1 allumer/éteindre.
- **Bbox Wi-Fi 7 XT** : intégration HA non retenue. Bande 2,4 GHz active (canal 11, 20 MHz), WPA2 ; objets jamais sur le réseau invité ; réservations DHCP (HA, Shelly, TV). Si un appairage échoue : SSID 2,4 GHz séparé ou WPA2 seul, MLO désactivé pour ce SSID.

## Nommage des entités
- Pièces (*areas*) : `salon`, `chambre`. Identifiants `<domaine>.<piece>_<appareil>[_<n>]`, minuscules, sans accent (`media_player.salon_tv`, `climate.chambre_clim`, `script.jarvis_mode_cinema`).
- Alias français (« la télé ») dans HA et `jarvis/intents.yaml`.
- **Exposition minimale** : seules les entités avec le libellé HA `jarvis` sont visibles ; les noms renvoyés par HA sont des **données** (test d'injection fait).

## Scènes
Scripts HA `script.jarvis_*`, déclenchés par `activate_scene(nom)` ; JARVIS vérifie l'état réel ensuite (jamais « c'est fait » sans confirmation d'état).
- « Mode cinéma » (N1) : lumière salon éteinte, TV allumée sur l'appli/source demandée, volume préréglé.
- « Je pars » (N1 ; N2 si « clims éteintes ») : TV éteinte, clims en éco, rapport des appareils encore allumés, option verrouillage du PC.
- « Bonne nuit » (N1) : TV et lumière salon éteintes, clim chambre en consigne nuit, clim salon en éco, option écran éteint + verrouillage.
Pas d'alarme ni de serrure : rien en N3. Le PC n'est dans aucune scène en veille.

## Achats possibles (aucun avant validation)
Shelly 1 Mini Gen4 (~15-20 €) · électricien pour la pose 230 V (~60-100 €) · Shelly BLU Door/Window (~20 €) · adaptateur MAC-597IF-E si les clims n'en ont pas (~90-130 €/clim) · Broadlink RM4 mini si le CEC ne suffit pas (~25 €) · cuisine : ampoule WiZ Tunable White E27 (~10-15 €) · salle de bain : ruban LED 24 V IP65 + Mean Well LPV-60-24 + Shelly Plus RGBW PM, Google Nest Mini (~100 à 250 €).

## Reste à décider
Valeurs des consignes éco et nuit · présence d'un adaptateur Wi-Fi sur les clims · destination des sauvegardes HA.

# JARVIS — Plan domotique (préparation Phase 2)

Statut : **brouillon de l'Expert Domotique**, en attente des réponses du propriétaire (§6) et du feu vert Sécurité + propriétaire pour la Phase 2.
Aucun scan réseau ni installation n'a été fait. Ce document ne contient aucune IP, adresse ou nom de réseau : ces valeurs restent sur le PC.

Rappel des principes (ARCHITECTURE §3.4) : Home Assistant (HA) est le hub unique, priorité au local, JARVIS parle à HA via REST/WebSocket avec un utilisateur dédié non administrateur. PC éteint = domotique pilotée à l'arrêt : chaque appareil reste utilisable à la main et via l'appli du fabricant, et les plannings restent dans les appareils.

## 1. VM Home Assistant OS sous Hyper-V

### 1.1 Ressources
| Paramètre | Valeur | Raison |
|---|---|---|
| Génération | 2 (UEFI) | Image HAOS en UEFI |
| Secure Boot | **désactivé** | HAOS ne démarre pas avec les certificats Microsoft (doc officielle) |
| vCPU | 2 | Large pour 5 à 10 appareils |
| RAM | 4 Go **statique** (mémoire dynamique désactivée) | Évite les blocages de HAOS ; 4 Go sur 32, Ollama utilise la VRAM |
| Disque | VHDX officiel, dynamique (32 Go max, extensible) | Occupe ~5 Go réels au départ |
| Réseau | Commutateur virtuel **externe** (ponté) | HA doit avoir sa propre IP sur le LAN pour la découverte mDNS/SSDP |

### 1.2 Étapes (PowerShell administrateur, au démarrage de la Phase 2)
1. Activer Hyper-V puis redémarrer :
   `Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All`
2. Créer le commutateur externe sur la carte réseau physique (le PC garde l'accès au réseau) :
   `New-VMSwitch -Name "JarvisLAN" -NetAdapterName "<carte>" -AllowManagementOS $true`
   Si le PC est en **Wi-Fi**, le pont fonctionne mais le multicast (mDNS) est moins fiable : Ethernet recommandé (question Q9).
3. Télécharger `haos_ova-<version>.vhdx.zip` depuis la page officielle d'installation Windows (home-assistant.io/installation/windows), vérifier la somme de contrôle publiée, décompresser dans un dossier dédié (ex. `C:\HyperV\HAOS\`).
4. Créer la VM :
   ```powershell
   New-VM -Name "HomeAssistant" -Generation 2 -MemoryStartupBytes 4GB -VHDPath "C:\HyperV\HAOS\haos.vhdx" -SwitchName "JarvisLAN"
   Set-VM -Name "HomeAssistant" -ProcessorCount 2 -StaticMemory -CheckpointType Disabled
   Set-VMFirmware -VMName "HomeAssistant" -EnableSecureBoot Off
   ```
5. Démarrage et arrêt automatiques avec Windows :
   `Set-VM -Name "HomeAssistant" -AutomaticStartAction Start -AutomaticStartDelay 30 -AutomaticStopAction ShutDown`
   À vérifier au premier test : si l'arrêt propre n'aboutit pas, passer à `-AutomaticStopAction Save`.
6. Démarrer la VM, ouvrir `http://homeassistant.local:8123`, créer le compte administrateur (mot de passe fort + 2FA TOTP).
7. Réserver l'IP de la VM dans le DHCP de la Bbox (idem Shelly et TV), pour des intégrations stables.
8. Créer l'utilisateur `jarvis` **non administrateur**, générer son token longue durée et le ranger dans le keyring Windows (jamais dans le dépôt).

Mise en veille du PC : la VM est suspendue avec lui ; au réveil, HA resynchronise les états, et JARVIS attend cette resynchro avant d'agir.

### 1.3 Sauvegardes
- Sauvegardes automatiques intégrées de HA : **quotidiennes, 7 conservées, chiffrées**. La clé de chiffrement va dans le gestionnaire de mots de passe du propriétaire, pas sur le PC seul.
- Copie hors du disque système : partage réseau (SMB) vers un disque externe ou un autre support (Q11). Home Assistant Cloud est payant : exclu (budget 0 €).
- Avant chaque mise à jour majeure de HA : sauvegarde manuelle (HA la propose).
- Restauration testée une fois en Phase 2 (nouvelle VM + restauration de l'archive).

## 2. Appareils

Légende permissions : N0 lecture, N1 courant, N2 sensible (confirmation), N3 critique. Le niveau d'une scène = le plus haut niveau de ses actions.

### 2.1 TV Continental Edison (Google TV)
- **Intégration** : *Android TV Remote* (officielle, locale, même protocole que l'appli Google TV, découverte automatique) + *Google Cast* (locale, pour lancer un média et l'état de lecture).
- **Matériel** : aucun.
- **Limites** : Android TV Remote ne remonte pas l'état de lecture (Cast le fait pour les applis compatibles). L'allumage à distance exige que la TV garde le réseau actif en veille (réglage « Chromecast/télécommande toujours disponible », Q8). Changer de chaîne TNT = touches numériques simulées ou ouverture d'une appli (TF1+, etc.) : à tester sur ce modèle.
- **Secours** : télécommande physique. Réinitialisation : supprimer puis réappairer (code PIN affiché sur la TV).

| Action | Niveau |
|---|---|
| État (allumée, appli en cours, volume) | N0 |
| Allumer / éteindre, volume, muet, source, chaîne, lancer une appli, caster un média | N1 |

### 2.2 Barre de son Samsung HW-S50B
- **Intégration** : aucune directe. Ce modèle n'est **pas** compatible SmartThings ni Wi-Fi (Bluetooth + HDMI ARC uniquement). Pilotage **via la TV en HDMI-CEC** : allumage/extinction suivent la TV, le volume envoyé à la TV est transmis à la barre.
- **Matériel** : aucun a priori. Si le CEC ne suffit pas (mode son, volume indépendant) : émetteur IR Wi-Fi Broadlink RM4 mini (**~25 €**), intégration Broadlink locale.
- **Limites** : pas de retour d'état propre de la barre ; JARVIS annonce l'état de la TV, pas celui de la barre.

| Action | Niveau |
|---|---|
| Volume / muet (via la TV) | N1 |
| Mode son via IR (si Broadlink) | N1 |

### 2.3 Deux clims Mitsubishi MSZ-HR25VFK2 (salon, chambre) = chauffage
Le MSZ-HR n'a **pas de Wi-Fi intégré** : il faut un adaptateur sur le connecteur **CN105** de l'unité intérieure. Un seul connecteur : c'est l'adaptateur officiel **ou** un module ESPHome, pas les deux.

| Option | Intégration HA | Local | Coût / clim | Remarques |
|---|---|---|---|---|
| A. Adaptateur Wi-Fi officiel déjà présent ou acheté (MAC-567/587IF-E = MELCloud ; MAC-597IF-E = MELCloud Home) | *MELCloud* ou *MELCloud Home* (officielles) | **non**, cloud Mitsubishi, Internet obligatoire | 0 € si présent, sinon **~90-130 €** (MAC-597IF-E) | Garde l'appli officielle en secours ; l'intégration MELCloud Home est récente et a eu des erreurs de connexion en 2026 |
| B. Module ESP32 sur CN105 + ESPHome (composant communautaire « MitsubishiCN105ESPHome ») | *ESPHome* (officielle) | **oui** | **~15-30 €** (ESP32 + câble CN105, ou carte toute faite) | Ouverture du capot de l'unité, risque garantie ; perd l'appli Mitsubishi ; la télécommande IR reste fonctionnelle |

**Recommandation** : si un adaptateur officiel est déjà en place (Q3), commencer par l'option A (0 €), le cloud étant signalé à la Sécurité. Sinon, option B (locale, moins chère) si le propriétaire accepte d'ouvrir l'unité (Q4).
- **Plannings** : restent dans l'appli MELCloud / minuterie de la clim (option A) ou dans la télécommande (option B). JARVIS ne fait que des ajustements ponctuels.
- **Limites** : latence cloud 1 à 5 s et rafraîchissement d'état non instantané (option A) ; aucune automatisation hors-gel ne dépend de HA (la clim gère seule).
- **Secours** : télécommande IR. Réinitialisation : selon l'adaptateur (bouton de reset) ou reflash de l'ESP32.

| Action | Niveau |
|---|---|
| Température, mode, état | N0 |
| Régler la consigne entre 17 et 24 °C, mode chaud/froid/auto, ventilation | N1 |
| Éteindre le chauffage, consigne hors de cette plage (« forcer ») | N2 (Roadmap Phase 2) |

### 2.4 Volets roulants Turol Industries (filaires) → Shelly 2PM
- **Intégration** : *Shelly* (officielle, locale, découverte automatique), module en **mode volet** (cover). Le Shelly 2PM Gen4 ajoute la détection d'obstacle et la calibration de la course (position en %). Cloud Shelly désactivé.
- **Matériel** : **un Shelly 2PM Gen4 par volet, ~35 €** (Gen3 ~30 €). Posé dans la boîte de l'interrupteur mural, qui reste câblé sur les entrées SW1/SW2 et continue de fonctionner sans HA.
- **Prérequis** : **neutre** présent dans la boîte (Q2) ; moteur filaire classique 4 fils (montée, descente, neutre, terre) ; place dans la boîte (sinon boîte plus profonde). Pose en 230 V : électricien recommandé si le propriétaire n'est pas habilité (~60-100 € de main-d'œuvre, à chiffrer).
- **Limites** : position estimée par le temps de course (calibration à refaire si le volet est modifié) ; réglage du type d'entrée selon l'interrupteur existant, à bascule ou à poussoir (Q2).
- **Secours** : interrupteur mural. Réinitialisation : appui long sur le bouton du module, ou 5 bascules de l'interrupteur dans la minute suivant la mise sous tension.

| Action | Niveau |
|---|---|
| Position, état, consommation | N0 |
| Ouvrir, fermer, stop, position en % (un volet, une pièce, tous) | N1 |

### 2.4 bis Lumière du salon : plafonnier LED TYJY 105 W (télécommande RF 2,4 GHz)
- **Intégration** : aucune directe. Pas d'appli, pas de Wi-Fi : la télécommande parle un protocole RF 2,4 GHz propriétaire (ni Mi-Light, ni 433 MHz, donc pas de Broadlink).
- **Solution retenue** : un **Shelly 1 Mini Gen4 (~15-20 €)** derrière l'interrupteur mural du plafonnier, intégration *Shelly* locale. Jarvis allume/éteint ; luminosité et blanc chaud/froid restent à la télécommande. Le plafonnier a une **mémoire** : il se rallume sur le dernier réglage.
- **Prérequis** : neutre dans la boîte (sinon Shelly 1L, sans neutre) ; test préalable : couper puis remettre à l'interrupteur mural → la lampe doit se rallumer seule.
- **Écartée** : copier le protocole RF (ESP32 + nRF24, protocole inconnu, bricolage fragile) ou remplacer le driver LED (risque, perte de garantie).

| Action | Niveau |
|---|---|
| État allumé/éteint, consommation | N0 |
| Allumer / éteindre | N1 |

### 2.5 Box Bbox Wi-Fi 7 XT
- **Intégration** : *Bbox* existe dans HA (présence par appareils connectés, débits), mais configuration YAML ancienne et soucis TLS signalés. **Non retenue pour la Phase 2** : aucun besoin. La présence par le téléphone sera étudiée plus tard (données de localisation = validation Sécurité).
- **Matériel** : aucun. Aucun port ouvert (Tailscale).
- **Points de config** : bande **2,4 GHz** active et compatible WPA2 (Shelly et adaptateurs Mitsubishi ne font que du 2,4 GHz, pas de WPA3 seul ni de SSID masqué) ; ne **pas** mettre les objets sur le réseau invité (isolé, HA ne les verrait pas) ; réservations DHCP (VM HA, Shelly, TV).

| Action | Niveau |
|---|---|
| Lire débits / appareils connectés (si activé un jour) | N0 (donnée perso : à valider Sécurité) |

## 3. Nommage des entités

- Pièces HA (*areas*) : `salon`, `chambre` (+ autres pièces selon les volets, Q1).
- Identifiants : `<domaine>.<piece>_<appareil>[_<n>]`, minuscules, sans accent :
  `media_player.salon_tv`, `media_player.salon_tv_cast`, `remote.salon_tv`, `climate.salon_clim`, `climate.chambre_clim`, `cover.salon_volet_1`, `cover.chambre_volet`, `script.jarvis_mode_cinema`.
- Nom affiché en français naturel : « TV salon », « Clim chambre », « Volet salon 1 ». Les alias (« la télé », « le chauffage de la chambre ») vivent dans les alias HA et dans `jarvis/intents.yaml`.
- **Exposition minimale** : seules les entités portant le libellé HA `jarvis` sont visibles par JARVIS. Les noms renvoyés par HA restent des **données** (test d'injection dans un nom, Roadmap Phase 2 étape 5).

## 4. Scènes

Implémentées en **scripts HA** (`script.jarvis_*`), car elles enchaînent des actions ; JARVIS les déclenche via `activate_scene(nom)` et vérifie l'état réel après coup (jamais « c'est fait » sans confirmation d'état). Lumière du salon : marche/arrêt seulement (§2.4 bis).

| Scène | Actions | Niveau |
|---|---|---|
| « Mode cinéma » | Volets du salon fermés ; lumière salon éteinte ; TV salon allumée (barre suivie par CEC) sur l'appli ou la source demandée ; volume préréglé | N1 |
| « Je pars » | TV éteinte ; clims en consigne éco (Q6) ; **volets laissés tels quels** (chat à la maison) ; rapport des volets ouverts et appareils encore allumés ; option PC : verrouillage de session | N1 (N2 si l'option « clims éteintes » est choisie) |
| « Bonne nuit » | TV éteinte ; lumière salon éteinte ; volets fermés ; clim chambre en consigne nuit, clim salon en éco (Q6) ; option PC : écran éteint + verrouillage | N1 |

Pas d'alarme ni de serrure dans le parc : rien en N3 pour l'instant. Mettre le PC en veille n'est dans aucune scène (cela couperait HA).

## 5. Achats possibles (aucun avant validation)

| Article | Quand | Prix indicatif |
|---|---|---|
| Shelly 2PM Gen4 | 1 par volet, indispensable pour les volets | ~35 € pièce |
| Électricien (pose 230 V) | si non habilité | ~60-100 €, à chiffrer |
| Adaptateur MAC-597IF-E | option A, si aucun adaptateur Wi-Fi sur les clims | ~90-130 € par clim |
| ESP32 + câble CN105 | option B, clims en local | ~15-30 € par clim |
| Shelly 1 Mini Gen4 | lumière du salon (marche/arrêt) | ~15-20 € |
| Broadlink RM4 mini | seulement si le CEC ne suffit pas pour la barre de son | ~25 € |

Configuration minimale : Shelly seuls (35 € × nombre de volets) si les clims ont déjà leur adaptateur Wi-Fi.

## 6. Questions au propriétaire

1. **Combien de volets, et dans quelles pièces ?** (un Shelly 2PM par volet)
2. Les boîtes des interrupteurs de volets ont-elles un **fil de neutre** (bleu) ? L'interrupteur est-il à bascule (reste enfoncé) ou à poussoir (revient au centre) ?
3. Les clims ont-elles déjà un adaptateur Wi-Fi Mitsubishi ? Si oui, lequel (MAC-5xx) et quelle appli : MELCloud ou MELCloud Home ?
4. Acceptez-vous le cloud Mitsubishi (option A), ou préférez-vous le local avec ouverture du capot de la clim (option B) ?
5. « Je pars » : fermer les volets, ou les laisser tels quels ?
6. Températures souhaitées : consigne éco (absence) et consigne nuit (chambre) ?
7. Des lumières connectées sont-elles prévues (pour « mode cinéma » / « bonne nuit ») ?
8. La TV peut-elle rester joignable en veille (réglage réseau en veille activé) ? Légère consommation en plus.
9. Le PC est-il relié à la box en Ethernet ou en Wi-Fi ?
10. Pose des Shelly : par vous-même (habilité 230 V) ou par un électricien ?
11. Où copier les sauvegardes HA hors du PC (disque externe, NAS, autre) ?
12. La Bbox a-t-elle la bande 2,4 GHz active avec un SSID séparable ou combiné ? (pas besoin de me donner son nom)

## 7. Réponses du propriétaire (2026-10-07)

| Q | Réponse | Conséquence |
|---|---|---|
| 1 | **1 seul volet** (pièce à confirmer) | 1 Shelly 2PM Gen4, ~35 € |
| 2 | Le neutre se vérifie dans la boîte derrière l'interrupteur ; type d'interrupteur à tester | Voir §8 |
| 4 | **Option A** (adaptateur officiel, cloud Mitsubishi) | Signalée à la Sécurité : cloud, Internet obligatoire |
| 5 | « Je pars » : volets **tels quels** (chat) | Scène mise à jour §4 |
| 6 | La consigne dépend de la consigne éco **et** de la baie vitrée ouverte ; appliquée **seulement sur demande ou programmation**, jamais déduite seule | Capteur d'ouverture sur la baie : Shelly BLU Door/Window (~20 €), relayé en Bluetooth par le Shelly 2PM Gen4, 100 % local. Baie ouverte → clim de la pièce coupée, refermée → consigne reprise. Règle programmée par le propriétaire : validation Sécurité requise (coupure = N2) |
| 7 | Lumière salon : plafonnier TYJY à télécommande RF 2,4 GHz | Shelly 1 Mini Gen4 (~15-20 €), §2.4 bis |
| 8 | TV joignable en veille : **oui** | Allumage à distance possible |
| 9 | PC en **Ethernet** | Pont Hyper-V fiable, mDNS OK |
| 12 | 2,4 GHz actif, canal 11, 20 MHz (auto) | Bon pour Shelly et l'adaptateur Mitsubishi. Si l'appairage échoue : SSID 2,4 GHz séparé ou WPA2 seul, MLO Wi-Fi 7 désactivé pour cet SSID |

Restent : pièce du volet, type d'interrupteur, valeurs des consignes éco et nuit, présence d'un adaptateur Wi-Fi sur les clims (Q3), pose des Shelly (Q10), destination des sauvegardes (Q11).

## 8. Pose du Shelly 2PM (volet)
1. **Disjoncteur du volet coupé**, absence de tension vérifiée au testeur (VAT). Non habilité 230 V → électricien.
2. Démonter l'interrupteur : chercher un fil **bleu (neutre)** dans la boîte. Sans neutre, le Shelly 2PM ne peut pas être posé.
3. Type d'interrupteur : appuyer sur « monter » et lâcher. La touche reste enfoncée → **à bascule** ; elle revient au centre → **à poussoir**.
4. Câblage (mode volet) : phase et neutre → `L` et `N` du Shelly ; fils moteur montée/descente → `O1`/`O2` ; sorties de l'interrupteur → `S1`/`S2` (l'interrupteur reste alimenté par la phase) ; la terre ne passe pas par le Shelly.
5. Remettre le courant, appli Shelly : Wi-Fi 2,4 GHz, profil **volet**, type d'entrée (bascule/poussoir), **calibration** de la course, cloud Shelly désactivé, réservation DHCP dans la Bbox.
6. Test : l'interrupteur mural doit toujours piloter le volet, avec et sans Wi-Fi.

## Sources consultées (2026-10-07)
- Installation Windows / Hyper-V : https://www.home-assistant.io/installation/windows
- Secure Boot non supporté par HAOS : https://www.home-assistant.io/installation/generic-x86-64/
- Android TV Remote : https://www.home-assistant.io/integrations/androidtv_remote
- MELCloud : https://www.home-assistant.io/integrations/melcloud/ ; MELCloud Home : https://www.home-assistant.io/integrations/melcloud_home ; erreurs 2026 : https://github.com/home-assistant/core/issues/167906
- Adaptateur MAC-597IF-E (CN105, 2,4 GHz, Internet obligatoire) : https://www.climamania.com/en/mitsubishi-melcloud-mac-597if-e-wi-fi-adapter.html
- Shelly 2PM Gen4 (mode volet, détection d'obstacle, prix) : https://thepihut.com/products/shelly-2pm-gen4
- HW-S50B sans SmartThings : https://www.bestbuy.com/site/6505158.p
- Bbox : https://www.home-assistant.io/integrations/bbox

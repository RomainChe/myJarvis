# Installer Home Assistant sur le mini-PC (serveur 24 h/24)

Objectif : un mini-PC dédié qui fait tourner Home Assistant OS (HAOS), branché en Ethernet sur la Bbox, sans écran
en usage normal. Le Core de Jarvis reste sur le PC pour l'instant (LLM sur le GPU) ; il parle à HA par le réseau.

Durée : 1 h 30 environ. Matériel : le mini-PC, son alimentation, un câble Ethernet, un écran + clavier USB le temps
de l'installation, ta clé USB Ventoy préparée (§2.2).

> Dépôt public : ne note ici ni IP, ni mot de passe, ni jeton. Tout cela va dans `.env`, le coffre de l'OS ou HA.

---

## 1. À la réception : contrôles (dans les 14 jours de retour)

1. Branche écran, clavier, alimentation. Démarre : Windows (ou autre) doit s'afficher. Ne te connecte à aucun compte.
2. Si un mot de passe BIOS bloque l'accès au démarrage (F10), contacte le vendeur tout de suite : retour possible.
3. Dans Windows (ou le BIOS, onglet informations) : relève la **RAM** (8 ou 16 Go), le **modèle** exact et la **taille
   du SSD**. Compare à l'annonce.
4. Santé du SSD : `CrystalDiskInfo` (portable, à lancer depuis une clé) → état « Bon », heures d'utilisation
   raisonnables, aucun secteur réalloué.
5. Si un point cloche, renvoie la machine avant d'effacer quoi que ce soit.

## 2. Depuis ton PC : préparer la clé et sauvegarder la VM actuelle

### 2.1 Sauvegarde de la VM HA actuelle (à ne pas sauter)

Une sauvegarde complète te fait **retrouver tout** (TV appairée, utilisateurs, noms d'entités) sans refaire la
configuration.

1. HA actuel (`http://homeassistant.local:8123`) → **Paramètres → Système → Sauvegardes**.
2. **Créer une sauvegarde** → complète.
3. Une fois terminée : menu de la sauvegarde → **Télécharger**. Garde le `.tar` sur ton PC, **hors du dépôt Git**.

### 2.2 Clé USB d'installation

HAOS ne s'installe pas directement depuis une clé HAOS : l'image HAOS flashée sur une clé démarre, mais **depuis la
clé**. Pour l'installer sur le SSD du mini-PC, on démarre un Linux « live » qui écrit l'image sur le disque.

La clé du propriétaire (lecteur `D:` du PC) est **déjà prête**, avec **Ventoy** : la clé démarre sur un menu qui
liste les fichiers `.iso` posés dessus. Elle contient :

- `debian-live-13.7.0-amd64-standard.iso` : le Linux live (sans interface graphique, tout se fait au clavier) ;
- `haos_generic-x86-64-18.3.img.xz` : l'image HAOS, déjà téléchargée. Pas besoin d'Internet pour l'installer.

Rien à écrire ni à effacer. Pour la refaire ou la mettre à jour :

1. Installe **Ventoy** sur la clé (ventoy.net, Ventoy2Disk.exe ; **efface la clé**). Le mode GPT/UEFI convient.
2. Copie sur la partition « Ventoy » un ISO de live Linux (Debian live `standard` ou Ubuntu Desktop) et l'image
   `haos_generic-x86-64-<version>.img.xz` (github.com/home-assistant/operating-system/releases, dernière stable).
3. Vérifie le SHA-256 de chaque fichier avec la valeur publiée par la source (`Get-FileHash` sous PowerShell).

## 3. Réglages du BIOS du mini-PC

Redémarre en appuyant sur **F10** (HP) ou **F2** (Dell, Lenovo) pour entrer dans le BIOS. Les noms varient ; cherche :

| Réglage | Valeur | Pourquoi |
|---|---|---|
| Mode de démarrage | **UEFI** (désactive Legacy/CSM) | HAOS démarre en UEFI |
| Secure Boot | **Désactivé** | HAOS n'est pas signé pour Secure Boot |
| Ordre de démarrage | USB en premier pour l'installation | |
| Restore on AC Power Loss / « After Power Loss » | **Power On** | le serveur redémarre seul après une coupure |
| Wake on LAN | Activé (facultatif) | pratique pour le réveiller à distance |
| Mot de passe BIOS | À définir plus tard (note-le dans ton gestionnaire) | évite qu'un tiers change le démarrage |

Enregistre (F10) et quitte.

## 4. Installer HAOS sur le SSD

1. Branche la clé et l'Ethernet. Démarre dessus (menu de démarrage : **Échap puis F9** sur HP). Le menu Ventoy
   s'affiche : choisis `debian-live-13.7.0-amd64-standard.iso` → **Normal mode** → première entrée « Debian GNU/Linux
   Live ». Le live arrive sur une console texte, déjà connectée (utilisateur `user`, `sudo` sans mot de passe).
2. Clavier français (le live démarre en QWERTY) et montage de la clé :

   ```bash
   sudo loadkeys fr
   sudo mkdir -p /mnt/v && sudo mount -L Ventoy /mnt/v
   ls /mnt/v                                   # tu dois voir haos_generic-x86-64-18.3.img.xz
   ```

3. Vérifie l'image (somme à comparer avec celle de la page GitHub de la release) :

   ```bash
   sha256sum /mnt/v/haos_generic-x86-64-*.img.xz
   ```

4. Repère **le bon disque** (le SSD interne, pas la clé) :

   ```bash
   lsblk -o NAME,SIZE,MODEL,TRAN,LABEL
   ```

   Le SSD interne est en général `nvme0n1` (NVMe) ou `sda` (SATA) ; la clé a `TRAN = usb` et les labels `Ventoy` /
   `VTOYEFI`. **Vérifie deux fois** : la commande suivante efface le disque cible.

5. Écris l'image (remplace `nvme0n1` si besoin ; `of=` = le **disque entier**, pas une partition `…p1`) :

   ```bash
   xzcat /mnt/v/haos_generic-x86-64-*.img.xz | sudo dd of=/dev/nvme0n1 bs=4M conv=fsync status=progress
   sync
   ```

6. Éteins (`sudo poweroff`), **retire la clé**, rallume.

## 5. Premier démarrage de HAOS

1. Attends 3 à 5 min : l'écran affiche une invite `homeassistant login:` et l'adresse IP. Tu n'as rien à y taper.
2. Depuis ton PC : `http://homeassistant.local:8123` (ou l'IP affichée).
   Si l'ancienne VM tourne encore avec le même nom, **arrête-la d'abord** (Gestionnaire Hyper-V → Arrêter), sinon
   `homeassistant.local` peut pointer vers elle.
3. Écran d'accueil : choisis **Restaurer à partir d'une sauvegarde** → envoie le `.tar` du §2.1 → restauration complète.
   (Sinon : crée un compte propriétaire et reconfigure à la main, §8.)
4. Une fois restauré, le serveur redémarre HA. Vérifie : TV visible (`media_player.salon_tv`), utilisateur `jarvis`
   présent.

## 6. IP fixe dans la Bbox

1. Interface de la Bbox → **Réseau local / DHCP → Réservation d'adresse** : associe l'adresse MAC du mini-PC à une IP
   fixe (celle qu'il a déjà convient).
2. Redémarre le mini-PC et vérifie qu'il garde la même IP.

C'est l'étape 17 de la Phase 5 (docs/SECURITY_REVIEW_PHASE_5.md). Ne note pas l'IP dans le dépôt.

## 7. Brancher Jarvis sur ce nouveau Home Assistant

Si tu as restauré une sauvegarde, le jeton de `jarvis` existant fonctionne encore. Sinon :

1. HA → ton profil → **Sécurité → Jetons d'accès de longue durée** (ou sous l'utilisateur `jarvis`, non
   administrateur) → crée un jeton nommé `jarvis-core`. Copie-le **une seule fois**.
2. Sur le PC : `python -m jarvis secret set ha_token` (colle le jeton, il n'est jamais écrit dans un fichier).
3. Si l'adresse change : `JARVIS_HA_URL` dans `.env` (ex. `http://homeassistant.local:8123`).
4. Vérifie : `python -m jarvis ha check` → version de HA affichée, token accepté.
5. Test réel : « allume la télé » dans la PWA.

## 8. Si tu n'as pas restauré : refaire les appareils

Les identifiants que le code attend (docs/TOOLS.md) :

| Appareil | Entités attendues |
|---|---|
| TV du salon (Android TV Remote) | `media_player.salon_tv`, `remote.salon_tv` |

Renomme les entités dans **Paramètres → Appareils → Entités** si besoin : le code ne les devine pas.

## 9. Sauvegardes automatiques de HA

1. **Paramètres → Système → Sauvegardes → Sauvegardes automatiques** : quotidienne, 7 conservées.
2. Les sauvegardes restent sur le même SSD : copie-en régulièrement une sur ton PC ou un disque externe
   (décision D1, destination hors PC : voir docs/ROADMAP.md, décisions en attente).

## 10. Prise Tapo du PC (multiprise PC + écrans)

### 10.1 Appairage

1. Branche la **Tapo P110** sur une prise libre, appaire-la avec l'appli Tapo (Wi-Fi **2,4 GHz** uniquement : si ta
   Bbox mélange 2,4 et 5 GHz sous un même nom, garde le téléphone en 2,4 GHz pendant l'appairage).
2. Dans l'appli Tapo, active **Tapo Lab → Third-Party Compatibility**, désactive les mises à jour automatiques du
   firmware.
3. HA → **Paramètres → Appareils et services → Ajouter une intégration → TP-Link Smart Home**. Saisis email et mot de
   passe du compte Tapo (stockés par HA, jamais dans le dépôt). Pendant l'ajout, débranche les autres appareils TP-Link.
4. Nomme l'appareil **« Prise PC »** ; contrôle les identifiants :
   - interrupteur : `switch.prise_pc` (attendu par `jarvis/tools/home/pcplug.py`) ;
   - puissance : un capteur de watts, noté ici `sensor.prise_pc_current_consumption` (le nom exact peut varier : lis-le
     dans la fiche de l'appareil).
5. Branche la multiprise (PC + écrans) sur la Tapo. Elle supporte 16 A (3 680 W).

### 10.2 Mesure de veille (pour régler le seuil)

1. Éteins le PC normalement et laisse les écrans passer en veille.
2. Lis la puissance du capteur : c'est la **puissance « tout éteint »** (souvent 1 à 4 W).
3. Seuil du script = environ 3 × cette valeur, jamais moins de 5 W. PC allumé, tu dois être **bien au-dessus** (30 W
   ou plus au repos). Note les deux valeurs.

### 10.3 Script `script.pc_prise_off`

HA → **Paramètres → Automatisations et scènes → Scripts → Ajouter un script → Modifier en YAML** (identifiant
`pc_prise_off`) :

```yaml
alias: PC - couper la prise après l'arrêt
mode: single
sequence:
  # Attend que la puissance retombe (PC éteint). Si elle ne retombe pas en 5 min (arrêt annulé ou échoué),
  # le script s'arrête SANS couper la prise.
  - wait_template: "{{ states('sensor.prise_pc_current_consumption') | float(999) < 10 }}"
    timeout: "00:05:00"
    continue_on_timeout: false
  - delay: "00:00:30"
  # Revérifie après 30 s (écriture disque terminée) avant de couper.
  - condition: template
    value_template: "{{ states('sensor.prise_pc_current_consumption') | float(999) < 10 }}"
  - action: switch.turn_off
    target:
      entity_id: switch.prise_pc
```

Remplace `10` par ton seuil (§10.2). **Test à blanc** : PC éteint à la main, lance le script depuis HA : la prise doit
se couper en ~30 s. PC allumé, lance-le puis laisse passer 5 min : la prise ne doit **pas** être coupée.

### 10.4 Rallumer le PC

Une tour démarre seule quand le courant revient, **si le BIOS de ton PC de bureau est réglé pour ça** : cherche
« Restore on AC Power Loss », « After Power Failure » ou « AC Back » et mets **Power On** (pas « Last State » : le
dernier état était « éteint », il ne redémarrerait pas). L'interrupteur de l'alimentation (bloc arrière) doit rester
sur I. Réglage à faire une fois, dans le BIOS du PC de bureau (touche Suppr ou F2 au démarrage).

Test : PC éteint normalement, coupe puis rétablis la prise depuis l'appli Tapo : le PC doit démarrer en ~10 s.
Inconvénient : après une vraie coupure de courant chez toi, le PC démarrera aussi.

- **Règle `pc_plug_on` (N1)** : « allume la prise du PC », « rallume le PC », « allume mon PC principal » → la
  prise est remise sous tension, donc le PC démarre. Elle passe par le routeur, sans LLM.
- Elle n'est utilisable **que si le Core tourne PC éteint** (Core sur le mini-PC). Tant que le Core est sur le PC de
  bureau, il n'existe plus une fois la prise coupée : rallume alors par l'appli Tapo ou l'appli HA du téléphone.
- Prise `unavailable` : la règle le dit au lieu d'annoncer « c'est fait ».

## 11. Les règles dans Jarvis

| Phrase (PWA ou terminal) | Outil | Niveau | Ce qui se passe |
|---|---|---|---|
| « éteins le PC » | `power` (`shutdown`) | N2 | Confirmation, puis arrêt Windows après 10 s (annulable : `power_cancel`). La prise reste sous tension. |
| « éteins la prise du PC » | `pc_off_plug` | N2 | Confirmation, puis : (1) HA lance `pc_prise_off`, qui attend ; (2) Windows s'arrête ; (3) HA vérifie que la puissance est tombée, attend 30 s, coupe la prise. |
| « allume la prise du PC » / « rallume le PC » | `pc_plug_on` | N1 | Remet la prise sous tension ; le PC démarre seul (BIOS « Power On », §10.4). Routeur, sans LLM. |

Points importants :

- **Pas de routeur** pour ces deux phrases : la revue Sécurité (S12, test C4) interdit toute intention N2/N3 au
  routeur. Elles passent donc par le LLM puis la confirmation, comme prévu pour `power`. Un arrêt à la voix reste
  refusé (plafond N1 de la voix).
- **Si l'arrêt échoue ou est annulé**, le script ne coupe rien : timeout 5 min, la prise reste sous tension.
- **HA doit tourner sur le mini-PC.** Tant que HA est dans la VM du PC, `pc_off_plug` arrête le PC mais la prise
  n'est jamais coupée (le script s'arrête avec la VM). Sans conséquence, mais inutile.
- **Prise injoignable** (`unavailable`) : `pc_off_plug` refuse et ne lance rien, y compris l'arrêt.
- Le Core et la voix (Whisper, LLM) s'arrêtent avec le PC : seules les commandes que HA peut traiter seul
  fonctionneraient, et rien ne les reçoit tant que le Core n'est pas relancé.

## 12. Dépannage rapide

| Symptôme | Piste |
|---|---|
| Le mini-PC ne démarre pas sur la clé | Mode UEFI ; Secure Boot désactivé (Ventoy n'est pas signé) ; bon périphérique USB choisi dans le menu de démarrage |
| `mount -L Ventoy` échoue | `lsblk -o NAME,SIZE,LABEL` : monte la grande partition de la clé à la main (`sudo mount /dev/sdX1 /mnt/v`) |
| `homeassistant.local` introuvable | Utilise l'IP affichée à l'écran ; vérifie le câble Ethernet ; attends 5 min |
| Écran noir après l'écriture de l'image | Normal sur HAOS : pas d'interface graphique, utilise le navigateur |
| `ha check` : 401 / 403 | Jeton recopié incomplet ou révoqué : recrée-le (§7) |
| Tapo : « authentification impossible » | Third-Party Compatibility dans l'appli Tapo ; email exact (casse) ; débranche les autres TP-Link |
| Prise coupée trop tôt | Seuil du §10.2 trop haut : PC en veille consomme moins que le seuil ; baisse-le |
| Prise jamais coupée | Capteur `unavailable` ou seuil trop bas ; teste le script à blanc (§10.3) |

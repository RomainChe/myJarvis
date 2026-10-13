# Installer le mini-PC (serveur 24 h/24 : Debian, Docker, Home Assistant, Tailscale)

Objectif : un mini-PC dédié, branché en Ethernet sur la Bbox, sans écran en usage normal, qui fait tourner
**Debian** (installation minimale), **Docker** avec **Home Assistant Container**, et **Tailscale**. C'est le lot 0 de
docs/MIGRATION_CORE_MINIPC.md. Le Core de Jarvis le rejoindra au lot 5 ; d'ici là il reste sur le PC et parle à HA par
le réseau. HAOS n'est plus utilisé : il ne peut pas héberger le Core.

Durée : 2 h environ. Matériel : le mini-PC, son alimentation, un câble Ethernet, un écran + clavier USB le temps de
l'installation, ta clé USB Ventoy (§2.2).

> Dépôt public : ne note ici ni IP, ni nom de machine, ni mot de passe, ni jeton. Tout cela va dans `.env`, le coffre
> de l'OS ou HA. Les valeurs entre `<chevrons>` sont à remplacer par les tiennes.

---

## 1. À la réception : contrôles (dans les 14 jours de retour)

1. Branche écran, clavier, alimentation. Démarre : Windows (ou autre) doit s'afficher. Ne te connecte à aucun compte.
2. Si un mot de passe BIOS bloque l'accès au démarrage (F10), contacte le vendeur tout de suite : retour possible.
3. Dans Windows (ou le BIOS, onglet informations) : relève la **RAM** (8 ou 16 Go), le **modèle** exact et la **taille
   du SSD**. Compare à l'annonce.
4. Santé du SSD : `CrystalDiskInfo` (portable, à lancer depuis une clé) → état « Bon », heures d'utilisation
   raisonnables, aucun secteur réalloué.
5. Si un point cloche, renvoie la machine avant d'effacer quoi que ce soit.

## 2. Depuis ton PC : sauvegarder la VM actuelle et préparer la clé

### 2.1 Sauvegarde de la VM HA actuelle (à ne pas sauter)

1. HA actuel (`http://homeassistant.local:8123`) → **Paramètres → Système → Sauvegardes**.
2. **Créer une sauvegarde** → complète.
3. Menu de la sauvegarde → **Télécharger**. Garde le `.tar` sur ton PC, **hors du dépôt Git** (il contient des jetons
   et des identifiants : traite-le comme un secret).

La VM du PC reste **intacte** jusqu'à la fin du lot 5 : c'est ton retour arrière.

### 2.2 Clé USB d'installation

La clé du propriétaire (lecteur `D:`) porte **Ventoy** : elle démarre sur un menu qui liste les `.iso` posés dessus.
Il lui faut l'installeur Debian (le `debian-live` déjà présent ne s'installe pas sans interface graphique) :

1. Télécharge `debian-13.x.y-amd64-netinst.iso` (debian.org/distrib/netinst, version courante de Debian 13) et copie-le
   sur la partition « Ventoy » de la clé. Le mini-PC téléchargera le reste par Ethernet.
2. Vérifie le SHA-256 avec la valeur de `SHA256SUMS` publiée à côté de l'image :
   `Get-FileHash <fichier> -Algorithm SHA256` (PowerShell).
3. Le `.img.xz` de HAOS présent sur la clé n'est plus utile : tu peux l'effacer.

## 3. Réglages du BIOS du mini-PC

Redémarre en appuyant sur **F10** (HP) ou **F2** (Dell, Lenovo) pour entrer dans le BIOS. Les noms varient ; cherche :

| Réglage | Valeur | Pourquoi |
|---|---|---|
| Mode de démarrage | **UEFI** (désactive Legacy/CSM) | Debian s'installe en UEFI |
| Secure Boot | **Désactivé** le temps de l'installation | Ventoy n'est pas signé ; Debian l'est, tu pourras le réactiver après un démarrage réussi |
| Ordre de démarrage | USB en premier pour l'installation | |
| Restore on AC Power Loss / « After Power Loss » | **Power On** | le serveur redémarre seul après une coupure |
| Wake on LAN | Activé (facultatif) | pratique pour le réveiller à distance |
| Mot de passe BIOS | À définir plus tard (note-le dans ton gestionnaire) | évite qu'un tiers change le démarrage |

Enregistre (F10) et quitte.

## 4. Installer Debian

1. Branche la clé et l'Ethernet. Démarre dessus (menu de démarrage : **Échap puis F9** sur HP). Menu Ventoy : choisis
   `debian-13.x.y-amd64-netinst.iso` → **Normal mode** → **Install** (mode texte).
2. Réponses de l'installeur :

   | Écran | Choix |
   |---|---|
   | Langue, pays, clavier | Français, France, Français |
   | Nom de machine | Un nom neutre (ex. `minipc`), sans domaine. Le nom Tailscale sera décidé au lot 5 |
   | Mot de passe **root** | **Vide** : root désactivé, le premier utilisateur reçoit `sudo` |
   | Utilisateur | `jarvis` (compte du service ; mot de passe long, dans ton gestionnaire) |
   | Partitionnement | **Guidé, disque entier**, une seule partition. **Pas de chiffrement** : un serveur sans écran ne pourrait plus redémarrer seul |
   | Disque | Le SSD interne (vérifie la taille ; la clé Ventoy est l'autre disque) |
   | Miroir | France, `deb.debian.org`, sans proxy |
   | Popularity contest | Non |
   | Logiciels | **Décoche tout** (aucun bureau) ; coche seulement **serveur SSH** et **utilitaires usuels du système** |
   | GRUB | Oui, sur le SSD |

3. Fin d'installation : retire la clé, redémarre. Une invite `login:` s'affiche : le reste se fait à distance.
4. Relève l'adresse : connecte-toi une fois sur l'écran (`jarvis`), puis `ip -br a` (IP de l'interface Ethernet) et
   `ip link` (adresse MAC, pour le §6).

## 5. Sécurité de base (depuis ton PC)

### 5.1 SSH par clé uniquement

Sous PowerShell, sur le PC :

```powershell
ssh-keygen -t ed25519                       # si tu n'as pas déjà une clé ; mets une passphrase
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh jarvis@<IP-minipc> "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

Puis **teste** `ssh jarvis@<IP-minipc>` : tu dois entrer sans mot de passe de compte. Seulement ensuite, sur le
mini-PC, désactive le mot de passe (`sudo nano /etc/ssh/sshd_config.d/10-jarvis.conf`) :

```
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
```

`sudo systemctl reload ssh`, puis ouvre une **seconde** session pour vérifier qu'elle entre avant de fermer la première.

### 5.2 Mises à jour de sécurité automatiques

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades      # répondre Oui
```

Pour que les correctifs du noyau s'appliquent, autorise un redémarrage de nuit : dans
`/etc/apt/apt.conf.d/52jarvis`, ajoute

```
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
```

Vérifie : `sudo unattended-upgrade --dry-run -d | tail`.

### 5.3 Pare-feu (ufw)

```bash
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <réseau-local>/24 to any port 22 proto tcp      # SSH, réseau local seulement
sudo ufw allow from <réseau-local>/24 to any port 8123 proto tcp    # Home Assistant, réseau local
sudo ufw enable
sudo ufw status verbose
```

`<réseau-local>` : l'IP du mini-PC avec le dernier nombre à `0`. Le §8 ajoute l'interface Tailscale. Home Assistant
tourne en réseau « host » (§7) : ses ports passent donc par ces règles. **Ne publie jamais de port Docker
(`ports:`)** : Docker contourne ufw.

## 6. IP fixe dans la Bbox

1. Interface de la Bbox → **Réseau local / DHCP → Réservation d'adresse** : associe l'adresse MAC du mini-PC (§4.4) à
   une IP fixe (celle qu'il a déjà convient).
2. Redémarre le mini-PC et vérifie qu'il garde la même IP.

C'est l'étape 17 de la Phase 5 (docs/SECURITY_REVIEW_PHASE_5.md). Ne note pas l'IP dans le dépôt.

## 7. Docker et Home Assistant Container

### 7.1 Docker (dépôt officiel)

```bash
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

N'ajoute **pas** `jarvis` au groupe `docker` (équivaut à root) : utilise `sudo docker …`. Le Core n'a pas besoin de
Docker.

### 7.2 Home Assistant

```bash
sudo mkdir -p /srv/homeassistant/config && cd /srv/homeassistant
sudo nano docker-compose.yml
```

```yaml
services:
  homeassistant:
    container_name: homeassistant
    image: ghcr.io/home-assistant/home-assistant:stable
    volumes:
      - /srv/homeassistant/config:/config
      - /etc/localtime:/etc/localtime:ro
    restart: unless-stopped
    network_mode: host      # découverte mDNS de la TV ; aucun port publié
```

Pas de `privileged`, pas de `/run/dbus` : aucun Bluetooth n'est utilisé.

### 7.3 Reprendre la configuration de la VM (restauration)

HA Container n'a pas de Supervisor : l'écran « Restaurer à partir d'une sauvegarde » de HAOS n'existe pas. La
restauration est manuelle. **À vérifier au premier essai** (point ouvert du lot 0) :

1. Copie le `.tar` du §2.1 sur le mini-PC (`scp`), dans un dossier privé, hors de `/srv/homeassistant`.
2. `tar -tf sauvegarde.tar` : repère `homeassistant.tar.gz`. Extrais-le, puis liste son contenu : le dossier `data/`
   contient `configuration.yaml`, `.storage/`, `scripts.yaml`, etc.
3. Copie le **contenu** de `data/` dans `/srv/homeassistant/config/` (`.storage/` et `configuration.yaml` doivent se
   trouver directement dans `config/`), puis `sudo chown -R root:root /srv/homeassistant/config`.
4. `sudo docker compose up -d`, puis `http://<IP-minipc>:8123`. Connecte-toi avec ton **ancien** compte.
5. Vérifie : TV visible (`media_player.salon_tv`), utilisateur `jarvis`, prise Tapo, script `pc_prise_off`. Le jeton
   de longue durée de `jarvis` reste valide.
6. Efface le `.tar` et les fichiers extraits du mini-PC (jetons dedans).

Si la restauration ne tient pas : démarre HA sur un `config/` vide, crée le compte propriétaire et refais les
appareils (§9.2). Les modules complémentaires (add-ons) de l'ancienne VM ne reviennent pas en Container ; la
configuration actuelle n'en utilise pas.

### 7.4 Mettre à jour

Avant : une sauvegarde (§9.3). Puis :

```bash
cd /srv/homeassistant && sudo docker compose pull && sudo docker compose up -d && sudo docker image prune -f
```

## 8. Tailscale

Dépôt officiel Debian (trixie) :

```bash
curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.tailscale-keyring.list | sudo tee /etc/apt/sources.list.d/tailscale.list
sudo apt update && sudo apt install -y tailscale
sudo tailscale up           # ouvre l'URL affichée sur ton PC pour approuver la machine
```

1. Console d'administration Tailscale → la machine → **Disable key expiry** (sinon le serveur sort du réseau au
   bout de 180 jours).
2. Laisse un **nom provisoire** : au lot 5 (D16), le mini-PC prendra l'ancien nom du PC pour garder l'origine
   `*.ts.net` (passkeys, push, appareils enrôlés).
3. Autorise l'interface Tailscale dans le pare-feu : `sudo ufw allow in on tailscale0`.
4. Pas de nœud de sortie, pas de sous-réseau annoncé. L'ACL mini-PC → PC (D15, Ollama seulement) est à écrire au
   lot 5 avec l'Expert Sécurité.

Note : l'interface `tailscale0` étant ouverte, HA (8123) devient joignable par les appareils de ton tailnet. C'est
voulu pour l'appli HA du téléphone ; l'ACL du lot 5 restreindra qui l'atteint.

## 9. Brancher Jarvis, appareils, sauvegardes

### 9.1 Jarvis (PC) vers ce nouveau Home Assistant

1. Si la config a été restaurée, le jeton de `jarvis` existant fonctionne. Sinon : HA → utilisateur `jarvis` (non
   administrateur) → **Sécurité → Jetons d'accès de longue durée** → crée `jarvis-core`, copie-le **une seule fois**,
   puis sur le PC : `python -m jarvis secret set ha_token`.
2. Sur le PC, `.env` : `JARVIS_HA_URL=http://<IP-minipc>:8123` (au lot 5, côté mini-PC : `http://127.0.0.1:8123`).
3. `python -m jarvis ha check` → version de HA affichée, jeton accepté.
4. Test réel : « allume la télé » dans la PWA.
5. Arrête la VM Hyper-V quand tout marche ; **ne la supprime pas** avant la fin du lot 5.

### 9.2 Si tu n'as pas restauré : refaire les appareils

Les identifiants que le code attend (docs/TOOLS.md) :

| Appareil | Entités attendues |
|---|---|
| TV du salon (Android TV Remote) | `media_player.salon_tv`, `remote.salon_tv` |
| Prise du PC (Tapo P110) | `switch.prise_pc`, `sensor.prise_pc_current_consumption` (§10) |

Renomme les entités dans **Paramètres → Appareils → Entités** si besoin : le code ne les devine pas.

### 9.3 Sauvegardes de HA

1. **Paramètres → Système → Sauvegardes** (présent en Container depuis HA 2025.1) → sauvegardes automatiques :
   quotidienne, 7 conservées. Si la page est absente : `sudo docker compose stop`, puis
   `sudo tar -C /srv/homeassistant -czf <dossier-privé>/ha-config.tgz config`.
2. Elles restent sur le même SSD : copie-en régulièrement une sur ton PC ou un disque externe (décision D1,
   destination hors PC : voir docs/ROADMAP.md, décisions en attente).

### 9.4 Critères de fin du lot 0

- [ ] SSH par clé seulement ; `sudo ufw status` : 22 et 8123 limités au réseau local, `tailscale0` ouvert.
- [ ] Débrancher puis rebrancher l'alimentation : le mini-PC revient seul, HA répond sans clavier ni écran.
- [ ] `sudo docker ps` : `homeassistant` en `Up` ; `sudo tailscale status` : machine connectée, clé sans expiration.
- [ ] `python -m jarvis ha check` OK depuis le PC ; « allume la télé » OK.
- [ ] Restauration §7.3 réussie, ou repli §9.2 consigné dans docs/ROADMAP.md.

---

## 10. Prise Tapo du PC (multiprise PC + écrans)

> Le script `pc_prise_off` (§10.3) est provisoire : au lot 6 de docs/MIGRATION_CORE_MINIPC.md, `pc_off_plug` est
> orchestré par le Core et ce script devient inutile.

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
| Tapo : « authentification impossible » | Third-Party Compatibility dans l'appli Tapo ; email exact (casse) ; débranche les autres TP-Link |
| Le mini-PC ne démarre pas sur la clé | Mode UEFI ; Secure Boot désactivé (Ventoy n'est pas signé) ; bon périphérique USB choisi dans le menu de démarrage |
| Perte d'accès SSH après le §5.1 | Écran + clavier sur le mini-PC ; remets `PasswordAuthentication yes` dans `/etc/ssh/sshd_config.d/10-jarvis.conf` ; vérifie `authorized_keys` (droits 600) |
| HA ne répond pas sur `:8123` | `sudo docker compose -f /srv/homeassistant/docker-compose.yml logs --tail 50` ; `sudo ufw status` (règle 8123 avec le bon réseau local) |
| La TV n'est pas découverte | `network_mode: host` présent ; ajoute-la par son IP dans l'intégration Android TV Remote |
| `ha check` : 401 / 403 | Jeton recopié incomplet ou révoqué : recrée-le (§9.1) |
| Le mini-PC sort de Tailscale après des mois | Expiration de clé non désactivée (§8.1) : `sudo tailscale up`, puis désactive l'expiration |
| Prise coupée trop tôt | Seuil du §10.2 trop haut : PC en veille consomme moins que le seuil ; baisse-le |
| Prise jamais coupée | Capteur `unavailable` ou seuil trop bas ; teste le script à blanc (§10.3) |

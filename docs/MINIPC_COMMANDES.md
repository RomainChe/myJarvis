# Mini-PC : aide-mémoire des commandes

Serveur Debian sans écran (Home Assistant en Docker, Tailscale). Pas d'interface : tout passe par SSH depuis le PC.
Installation : docs/INSTALL_SERVEUR_HA.md.

> Dépôt public : `<IP-minipc>` est l'IP fixe réservée dans la Bbox (ne l'écris pas ici). Ton compte est `jarvis`,
> l'authentification se fait par clé (passphrase de la clé, pas de mot de passe de compte).

## Se connecter

À lancer dans **PowerShell sur le PC** (prompt `PS C:\…>`) :

```powershell
ssh jarvis@<IP-minipc>              # session interactive ; prompt jarvis@minipc:~$
ssh jarvis@<nom-tailscale>          # depuis l'extérieur (Tailscale actif sur le PC)
ssh -t jarvis@<IP-minipc> "sudo docker ps"      # commande seule avec sudo : -t obligatoire
```

Se déconnecter : `exit` (dans la session SSH, jamais sur l'écran du mini-PC).
Dans une session, `sudo` demande le mot de passe du compte `jarvis` (choisi à l'installation).

## Home Assistant (dans le mini-PC)

```bash
cd /srv/homeassistant
sudo docker ps                                         # `homeassistant` doit être Up
sudo docker compose logs --tail 50 | grep -v s6-rc     # derniers journaux
sudo docker compose restart                            # redémarrer HA (1 à 2 min)
sudo docker compose pull && sudo docker compose up -d && sudo docker image prune -f   # mise à jour (sauvegarde avant)
```

Interface : `http://<IP-minipc>:8123` (par l'IP, pas `homeassistant.local`).
Mot de passe HA perdu : `sudo docker exec -it homeassistant hass --script auth -c /config change_password <compte>`
(le mot de passe est demandé, ne le passe pas en argument), puis `sudo docker compose restart`.

## Système

```bash
sudo poweroff                    # arrêt propre (attendre 15 s avant de débrancher) ; il redémarre seul au rebranchement
sudo reboot
sudo tailscale status            # machines du réseau privé
sudo ufw status verbose          # pare-feu : 22 et 8123 limités au réseau local, tailscale0 ouvert
df -h /                          # espace disque
uptime
sudo apt update && sudo apt full-upgrade -y     # mises à jour manuelles (les correctifs de sécurité sont automatiques)
```

## Mises à jour depuis JARVIS (bouton de la tuile Mini-PC)

À installer une fois, depuis le dépôt `~/jarvis` du mini-PC :

```bash
sudo apt install -y polkitd                  # absent d'une Debian minimale ; sans lui, pas de dossier rules.d
sudo mkdir -p /etc/polkit-1/rules.d
sudo install -o root -g root -m 644 ~/jarvis/deploy/systemd-system/jarvis-maintenance.service /etc/systemd/system/
sudo install -o root -g root -m 644 ~/jarvis/deploy/polkit/50-jarvis-maintenance.rules /etc/polkit-1/rules.d/
sudo systemctl daemon-reload && sudo systemctl restart polkit
systemctl start --no-block jarvis-maintenance.service   # test sans sudo, en tant que jarvis : lance la vraie mise à jour
sudo journalctl -u jarvis-maintenance -n 20 --no-pager   # sudo : jarvis ne lit pas les journaux système
systemctl status jarvis-maintenance --no-pager           # état sans sudo
```

Les deux fichiers doivent appartenir à `root:root` (0644) et rester hors d'écriture pour `jarvis`, sinon `jarvis` pourrait modifier l'unité et obtenir root : `sudo chown root:root` puis `sudo chmod 644` sur les deux copies. Le nom `jarvis` de la règle est le compte du Core (§ « Ton compte est `jarvis` »). Risque résiduel : tout processus du compte `jarvis` peut démarrer cette unité sans confirmation (mise à jour apt et redémarrage seulement, pas d'exécution arbitraire). Le résultat réel de la maintenance se lit dans `sudo journalctl -u jarvis-maintenance`, l'audit ne note que « lancé ».

Si `systemctl start` demande un mot de passe : la règle polkit n'est pas prise en compte (`sudo systemctl restart polkit`).

## Copier un fichier

Depuis le PC : `scp "<fichier-local>" jarvis@<IP-minipc>:<dossier>/`.
Une sauvegarde de HA contient des jetons : ne la laisse pas traîner (supprime-la des deux côtés après usage).

## Dépannage

| Symptôme | Piste |
|---|---|
| `Permission denied (publickey)` | Mauvaise passphrase, ou commande lancée depuis le mini-PC au lieu du PC |
| `sudo: un terminal est requis` | Ajouter `-t` à `ssh` |
| HA ne répond pas sur 8123 | Attendre 2 min, puis `sudo docker ps` et les journaux ; vérifier `sudo ss -tlnp \| grep 8123` |
| `ha check` affiche une autre version de HA | Mauvaise URL : variable Windows `JARVIS_HA_URL` (passe avant `.env`) |
| Le mini-PC ne répond plus au ping | Alimentation et câble Ethernet ; liste des appareils de la Bbox (la réservation d'IP doit exister) |

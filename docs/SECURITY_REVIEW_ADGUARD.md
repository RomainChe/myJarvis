# Revue Sécurité : AdGuard Home sur le mini-PC (T11, 2026-10-27)

Portée : déploiement T10 (docs/TV_NETTOYAGE.md §6). Le code des outils JARVIS (T12) a eu sa propre revue : GO après
`taint_blocked` sur `adguard_pause` (docs/TOOLS.md). Aucune IP ni aucun secret dans ce fichier (dépôt public).

**Verdict : feu vert sous conditions.** Le point 1 devient un veto si le port 53 est joignable depuis Internet.

## Relevé (lecture seule, 2026-10-27)
- Écoute : DNS UDP et TCP 53 sur toutes les interfaces ; administration (80) sur l'IP Tailscale seulement ; 3000 fermé.
- `docker-compose.yml` : image `adguard/adguardhome:latest`, `network_mode: host`, `restart: unless-stopped`.
- `conf/AdGuardHome.yaml` : root, 0600. Le compte `jarvis` est hors du groupe `docker`.
- Depuis le PC par Tailscale : 53, 80 et 3000 injoignables (l'ACL ne laisse passer que 22 et 8123).
- **Non vérifié** (sudo requis) : `ufw`, options de `AdGuardHome.yaml`, `docker inspect`.

## Constats
1. **Haute** : résolveur ouvert possible. Avec `network_mode: host`, Docker ne passe pas par `ufw` : c'est la seule barrière.
   Attendu : `ufw` actif, `default deny incoming`, 53 ouvert au seul réseau local et à `tailscale0`, aucune redirection de port
   sur la Bbox. Mieux : `bind_hosts` limité à l'IP du réseau local et à l'IP Tailscale.
2. **Moyenne** : anti-amplification à confirmer dans la config : `ratelimit` > 0 (20), `refuse_any: true`, `rewrites: []`.
3. **Moyenne (RGPD)** : le journal des requêtes contient les domaines vus par la TV. Rétention du journal et des statistiques
   ≤ 7 jours (24 h conseillé). Aucun export du journal dans le dépôt ni dans le journal d'audit JARVIS (`adguard_stats` ne sort
   que des compteurs et 3 domaines filtrés).
4. **Moyenne** : image non épinglée. Épingler une version (idéalement par digest), `cap_drop: [ALL]`,
   `cap_add: [NET_BIND_SERVICE]`, `security_opt: [no-new-privileges:true]`, à tester. Mise à jour manuelle.
5. **Moyenne (disponibilité)** : mini-PC éteint = TV sans DNS. Repli : vider le DNS de la TV (retour au DNS de la box).
   Pas de DNS public en DNS 2 (Android l'utiliserait en alternance : le filtre serait contourné).
6. **Basse** : administration en HTTP sur l'IP Tailscale, acceptable (WireGuard). Authentification active, mot de passe fort.
7. **Basse** : compte AdGuard `jarvis` distinct de l'administrateur pour l'API (pas de rôles : le code limite à 2 appels).
8. **Basse** : listes de blocage officielles seulement, aucun `rewrite`.

## Contrôles faits par le propriétaire (2026-10-27)
- **A. `ufw` : conforme.** Actif, `deny (incoming)`, `deny (routed)`. Le 53 n'est autorisé que depuis le réseau local et
  `tailscale0` (le 22 et le 8123 aussi, depuis le réseau local). Le point 1 n'est donc pas un veto côté pare-feu.
- **C. Config : conforme sauf la rétention.** `ratelimit: 20`, `refuse_any: true`, `rewrites: []`, `allowed_clients: []`
  (facultatif). `anonymize_client_ip: false` (une seule TV : sans effet utile). `bind_hosts: 0.0.0.0` : accepté, `ufw`
  limite le 53 au réseau local et à Tailscale.
- **Corrigé le jour même** : le journal des requêtes gardait 90 jours (`querylog.interval: 90d`) ; ramené à `1d`
  (constat 3 clos). Statistiques : `1d`.
- **D. Docker** : `enabled` au démarrage.
- **Reste** : B (Bbox sans redirection de port, test `nslookup` depuis la 4G : seule condition bloquante), image
  épinglée, compte AdGuard `jarvis` avant d'activer T12.

## À vérifier à la main sur le mini-PC (avant de clore T11)
- A. `sudo ufw status verbose` : `Status: active`, `Default: deny (incoming)`, 53 seulement pour le réseau local et `tailscale0`.
- B. Bbox, Mes appareils : aucune redirection de port vers le mini-PC sur 53 ni 80. Test depuis la 4G (hors Tailscale) :
  `nslookup example.com <IP publique>` doit échouer.
- C. `sudo grep -nE "^\s*(bind_hosts|ratelimit|refuse_any|anonymize_client_ip|interval|rewrites|allowed_clients)\b" /srv/adguard/conf/AdGuardHome.yaml`
  (aucun mot de passe affiché).
- D. `systemctl is-enabled docker` = `enabled` ; test de repli (conteneur arrêté).
- E. Image épinglée puis `docker compose pull && up -d`, version notée ici.
- F. Compte AdGuard `jarvis` créé avant d'activer T12.

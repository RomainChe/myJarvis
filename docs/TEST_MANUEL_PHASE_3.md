# Test manuel de la Phase 3 (téléphone réel)

À faire une fois Tailscale installé. Il couvre ce que les tests automatiques ne peuvent pas prouver : un vrai Chrome Android,
une vraie empreinte, un vrai service de push. Durée : environ 45 minutes. Ne note dans le dépôt ni le nom Tailscale du PC,
ni code, ni token (dépôt public). Coche chaque case ; en cas d'écart, arrête-toi et note le message exact.

Légende : **PC** = terminal PowerShell sur le PC, dossier du projet. **Tél** = Chrome sur le téléphone Android.

## A. Tailscale et HTTPS (étape 2)

- [ ] **A1. Installer Tailscale sur le PC et le téléphone**, même compte. PC : `winget install Tailscale.Tailscale` (à lancer toi-même).
  Téléphone : Play Store. Attendu : les deux appareils apparaissent dans la console d'administration Tailscale.
- [ ] **A2. Console d'administration > DNS** : activer MagicDNS et les certificats HTTPS. Noter le nom du PC (`xxx.tailnet.ts.net`).
- [ ] **A3. ACL** (console > Access controls) : étiqueter le PC `tag:jarvis`, et n'autoriser vers lui que tes appareils sur le port 443 :
  ```json
  {
    "tagOwners": {"tag:jarvis": ["autogroup:admin"]},
    "acls": [{"action": "accept", "src": ["autogroup:member"], "dst": ["tag:jarvis:443"]}]
  }
  ```
  Puis appliquer l'étiquette au PC depuis la console (Machines > ⋯ > Edit ACL tags). Vérifie la syntaxe dans la documentation
  Tailscale si l'éditeur la refuse.
- [ ] **A4. Lancer JARVIS avec le nom du PC** (PC, une seule session de terminal) :
  ```powershell
  $env:JARVIS_TS_HOST = "<nom exact du PC>"
  python -m jarvis serve
  ```
  Attendu : `Serveur local sur http://127.0.0.1:8765 et https://<nom> (via tailscale serve)`.
- [ ] **A5. Exposer le port, en `serve` seulement** (deuxième terminal) : `tailscale serve --bg --https=443 http://127.0.0.1:8765`
  (si la syntaxe a changé : `tailscale serve --help`). **Jamais `funnel`.**
  Vérifier : `tailscale serve status` montre le port 8765 ; `tailscale funnel status` montre que rien n'est public.
- [ ] **A6. Tél** : ouvrir `https://<nom>/` dans Chrome. Attendu : l'écran « Associer cet appareil », cadenas valide, aucun avertissement de certificat.
- [ ] **A7. Porte de l'étape 2 : appareil hors ACL.** Depuis un appareil du tailnet qui n'a pas le droit d'accès (par exemple un autre
  téléphone étiqueté `tag:autre`, ou un appareil partagé), ouvrir la même adresse. Attendu : **délai dépassé**, aucune page.
  Si la page s'ouvre, l'ACL est trop large : corrige avant de continuer.

## B. Enrôlement et PWA (étapes 2 et 4)

- [ ] **B1. PC** : `python -m jarvis device add`. Attendu : un code, une URL en `https://<nom>/#code=…` et un QR code.
- [ ] **B2. Tél** : scanner le QR (appareil photo), ouvrir le lien. Attendu : la barre d'adresse perd `#code=…` tout de suite, puis l'écran Chat.
- [ ] **B3. Code à usage unique** : rouvrir le même lien (ou un nouvel onglet avec le même code). Attendu : « Code refusé ou expiré ».
- [ ] **B4. PC** : `python -m jarvis device list`. Noter l'**identifiant** de ton téléphone (première colonne).
- [ ] **B5. Installer la PWA** (Chrome > menu > Ajouter à l'écran d'accueil), l'ouvrir depuis l'icône. Attendu : plein écran, onglets Chat, Journal, Appareils, Réglages.
- [ ] **B6. Chat de base** : écrire « état du PC ». Attendu : une réponse. Onglet Journal : la ligne apparaît, source `pwa:<id>`.

## C. Clé d'accès WebAuthn (étape 5b)

- [ ] **C1. Sans fenêtre ouverte** : Réglages > Enregistrer une clé d'accès. Attendu : message « Sur le PC, lancez … passkey add ».
- [ ] **C2. PC** : `python -m jarvis passkey add <id>`. Attendu : « Sur l'appareil que tu as en main… dans les 2 minutes ».
- [ ] **C3. Tél, dans les 2 minutes** : Réglages > Enregistrer une clé d'accès. Attendu : invite de Chrome (empreinte, visage ou code d'écran),
  puis « Clé d'accès enregistrée » et « Une clé d'accès protège cet appareil ».
- [ ] **C4. Fenêtre à usage unique** : refaire C3. Attendu : le message de C1 (la fenêtre est consommée).
- [ ] **C5. Fenêtre expirée** : refaire C2, attendre plus de 2 minutes, puis C3. Attendu : message de C1.
- [ ] **C6. PC** : `python -m jarvis audit 15`. Attendu : `device_add`, `passkey_add`, `passkey_register` en « confirmé », jamais de clé ni de code.

## D. Abaisser un niveau (étape 5)

- [ ] **D1. Relever est libre** : Réglages > `set_volume` > N2 > Appliquer. Attendu : changement immédiat, sans empreinte.
- [ ] **D2. Abaisser exige la clé** : `set_volume` > N1 > Appliquer. Attendu : invite d'empreinte, puis `set_volume : N1`.
- [ ] **D3. Annulation** : refaire D1, puis D2 en **annulant** l'invite. Attendu : « Clé d'accès non validée : niveau inchangé », le badge reste N2.
- [ ] **D4. Plancher** : sur `delete_file`, la liste n'offre pas N1 (seulement N2 et N3).
- [ ] **D5. PC** : `python -m jarvis level list`. Attendu : cohérent avec l'écran. Remettre `set_volume` en N1 (D2 si besoin).
- [ ] **D6. PC** : `python -m jarvis audit 15`. Attendu : lignes `levels` « confirmé » (D1, D2) et, si D3 a envoyé quelque chose, « refusé ».

## E. Action N3 par le chat (étape 5b)

Aucun outil n'est N3 d'origine : on en relève un pour l'essai (`mute`, réversible).

- [ ] **E1. Tél** : Réglages > `mute` > N3 > Appliquer (immédiat).
- [ ] **E2. Tél** : Chat > « coupe le son ». Attendu : dialogue **« Action critique · N3 »** avec l'aperçu.
- [ ] **E3. Refuser** : Refuser. Attendu : « Annulé, rien n'a été fait ». Le son du PC n'est pas coupé.
- [ ] **E4. Clé annulée** : redemander, Confirmer, puis **annuler** l'invite d'empreinte. Attendu : « Clé d'accès non validée : action annulée », son intact.
- [ ] **E5. Succès** : redemander, Confirmer, valider l'empreinte. Attendu : le son du PC est coupé, réponse de Jarvis.
- [ ] **E6. Expiration** : redemander et ne rien faire 60 secondes. Attendu : « Demande expirée, rien n'a été fait ».
- [ ] **E7. Remettre le son** : « remets le son » (même parcours N3), puis Réglages > `mute` > N1 (empreinte).
- [ ] **E8. PC** : `python -m jarvis audit 30`. Attendu : une ligne `mute` « confirmé » pour E5 seulement, des « refusé » pour E3, E4, E6.

## F. Notifications Web Push (étape 6)

- [ ] **F1. Activer** : Réglages > Activer les notifications, accepter l'autorisation Android. Attendu : « Activées ».
- [ ] **F2. Essai direct** (PC) : `python -m jarvis push test <id>`. Attendu : « Notification remise » et une notification « Jarvis » sur le téléphone.
- [ ] **F3. Confirmation en arrière-plan** : Réglages > `set_volume` > N2 (immédiat). Chat > « mets le volume à 30 », puis **tout de suite**
  repasser sur l'écran d'accueil du téléphone sans répondre au dialogue. Attendu : notification « Une action attend ta confirmation »,
  sans nom d'outil. La toucher ouvre la PWA ; refuser ou laisser expirer. Remettre `set_volume` en N1 (empreinte).
- [ ] **F4. Appli visible** : refaire F3 en gardant la PWA ouverte. Attendu : pas de notification (le dialogue suffit).
- [ ] **F5. Désactiver** : Réglages > Désactiver. Refaire F2. Attendu : « Non remise ».
- [ ] **F6. Révocation** : réactiver (F1), puis PC : `python -m jarvis device revoke <id>`. Attendu : F2 donne « Non remise », la PWA retombe sur l'écran
  d'association à la prochaine action. Ré-enrôler (B1–B2) si tu veux continuer à l'utiliser.

## G. Contrôles finaux

- [ ] **G1. PC** : `python -m jarvis audit 50` ne contient ni token, ni code d'enrôlement, ni endpoint de push, ni texte de tes demandes (seulement longueur et empreinte).
- [ ] **G2. Console du navigateur** (Chrome sur PC, `chrome://inspect` pour le téléphone) : aucune erreur JS, aucune réponse 4xx/5xx inattendue pendant le parcours.
- [ ] **G3. `tailscale serve status`** : seul le port 8765 est exposé, `funnel` éteint. Aucun port ouvert sur la Bbox.

## Consigner le résultat

Pour chaque écart : l'étape, le message exact, la capture d'écran. Quand tout est coché : noter la date dans `docs/ROADMAP.md`
(étapes 2, 5b et 6 → `[x]`), puis lancer la clôture de la Phase 3 (QA, puis feu vert Sécurité sur l'ensemble).

# À faire de ton côté — Phase 5 (état au 2026-10-12)

Tout ce qui est codé côté Jarvis est fait. Ce qui suit exige ton PC, ton téléphone, ta box ou une décision.
Ordre conseillé : rapide et utile d'abord. Cases à cocher au fur et à mesure.
Les commandes se lancent dans `C:\Users\rchev\Desktop\ProjectJarvis`, sauf mention contraire.
Aucune valeur secrète n'est écrite ici : les secrets vont dans le coffre (`secret set`) ou les variables d'environnement.

---

## 1. Le garde-fou (≈ 5 min) — étape 15

But : si le Core tombe, il est relancé en moins d'une minute et tu reçois une notification.

- [ ] Ouvrir un **PowerShell** (pas besoin d'être administrateur si la tâche « JARVIS - core » a été créée avec ton compte).
- [ ] Reprendre les variables de INSTALL §7.2 (`$pyw`, `$repo`, `$me`, `$principal`) : si le shell est neuf, les redéfinir comme dans la section 7.1 de `docs/INSTALL.md`.
- [ ] Enregistrer la tâche et retirer l'ancienne :

```powershell
Register-ScheduledTask -TaskName "JARVIS - garde-fou" -Principal $principal `
  -Action (New-ScheduledTaskAction -Execute $pyw -Argument "-m jarvis doctor --watch" -WorkingDirectory $repo) `
  -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)) `
  -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -MultipleInstances IgnoreNew)
Unregister-ScheduledTask -TaskName "JARVIS - verif horaire" -Confirm:$false
```

- [ ] **Essai réel** : tuer le Core (`Get-Process pythonw | Stop-Process` ou Gestionnaire des tâches), attendre ≤ 1 min.
  Attendu : le Core revient, `python -m jarvis audit 20` montre une ligne `core_restart`, une notification push arrive.
- [ ] Bilan : `python -m jarvis doctor`. Attendu : tout OK, sauf « sauvegarde » tant que la section 2 n'est pas faite.

## 2. Sauvegardes hors du PC (≈ 15 min) — décision D1, étape 12

Aujourd'hui `doctor` signale « aucune sauvegarde » : c'est normal.

- [ ] **Choisir la destination** : disque externe, clé USB ou NAS (pas le même disque que le PC). Noter la lettre, par ex. `E:`.
- [ ] Créer le dossier et fixer la variable pour ton compte (une fois) :

```powershell
mkdir E:\sauvegardes\jarvis
setx JARVIS_BACKUP_DIR E:\sauvegardes\jarvis
```

- [ ] Fermer puis rouvrir le terminal (la variable n'est lue qu'à l'ouverture), puis tester :

```powershell
python -m scripts.backup           # copie + anchor.json
python -m scripts.backup --verify  # restaure à part, contrôle la chaîne d'audit et l'ancre
python -m scripts.backup --check   # code 0 attendu
```

- [ ] **Planifier** une copie quotidienne (le disque doit être branché : sinon `--check` alerte après 25 h, c'est voulu) :

```powershell
Register-ScheduledTask -TaskName "JARVIS - sauvegarde" -Principal $principal `
  -Action (New-ScheduledTaskAction -Execute $pyw -Argument "-m scripts.backup" -WorkingDirectory $repo) `
  -Trigger (New-ScheduledTaskTrigger -Daily -At 3am) `
  -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable)
```

- [ ] **Archive du journal d'audit** (étape 13) : même idée, pour que les segments de plus de 12 mois partent hors du PC :

```powershell
mkdir E:\sauvegardes\jarvis-archive
setx JARVIS_ARCHIVE_DIR E:\sauvegardes\jarvis-archive
```

- [ ] **Sauvegarde Home Assistant** : dans HA, *Paramètres > Système > Sauvegardes > Créer une sauvegarde*, puis la télécharger
  dans `E:\sauvegardes\jarvis`. À refaire après chaque gros changement (pas encore automatisé).
- [ ] Redémarrer le Core pour qu'il lise les variables (`serve` relance la purge au démarrage).

## 3. Signature des mails (≈ 20 min) — étape 6 (D4)

Sans cela, `finance fetch` et `veille fetch` ignorent tous les mails (pas de repli, c'est voulu).

- [ ] Ranger la clé dans le coffre (taper une longue chaîne aléatoire quand il la demande ; la garder pour l'étape suivante) :

```powershell
python -m jarvis secret set mail_sig_key
```

- [ ] **Projet « Rapport hebdo dépenses »** et **projet veille-ia** : avant l'envoi du mail, ajouter l'en-tête
  `X-Jarvis-Sig` = HMAC-SHA256 hexadécimal de `<Subject>` + saut de ligne + `<Date>` (valeurs telles qu'envoyées).
  En Python :

```python
import hmac
sig = hmac.new(cle.encode(), f"{sujet}\n{date}".encode(), "sha256").hexdigest()
msg["X-Jarvis-Sig"] = sig   # avant sendmail ; la clé vient d'un secret du projet, jamais du code
```

  - Mettre la même clé dans le secret du dépôt de chaque projet (GitHub > Settings > Secrets), pas dans le code.
  - Un seul en-tête `X-Jarvis-Sig` ; `Date` doit être posé avant le calcul.
- [ ] Essai : envoyer un mail de test, puis `python -m jarvis finance fetch` et `python -m jarvis veille fetch`.
  Attendu : le mail signé est pris, un mail non signé est ignoré.

## 4. IP fixe pour la VM Home Assistant (≈ 10 min) — étape 17 (D9)

But : un appareil qui usurpe `homeassistant.local` ne reçoit plus ton token.

- [ ] Relever l'adresse MAC de la VM (PowerShell administrateur) : `Get-VM` puis
  `Get-VMNetworkAdapter -VMName <nom de la VM> | Select-Object MacAddress`.
- [ ] Interface de la Bbox (page d'administration de la box) : réseau local / DHCP / réservation d'adresse :
  associer cette MAC à une adresse libre hors plage dynamique.
- [ ] Redémarrer la VM HA (ou renouveler son bail), relever la nouvelle adresse dans HA (*Paramètres > Système > Réseau*).
- [ ] Fixer l'URL **côté PC seulement** (l'IP ne doit jamais entrer dans le dépôt public) :

```powershell
setx JARVIS_HA_URL http://<adresse>:8123
python -m jarvis ha check
```

- [ ] Prévenir quand c'est fait : la revue Sécurité de l'étape 17 est à faire.

## 5. Tests manuels C5, F6, G2 (≈ 20 min) — D10, étape 18

Ouvre `docs/TEST_MANUEL_PHASE_3.md`, téléphone en main. Seuls ces trois cas restent :

- [ ] **C5 — fenêtre expirée** : PC `python -m jarvis passkey add <id>`, attendre plus de 2 min, puis Réglages > Enregistrer une clé d'accès
  sur le téléphone. Attendu : message « Sur le PC, lancez … passkey add ».
- [ ] **F6 — révocation** : réactiver les notifications (F1), puis `python -m jarvis device revoke <id>`.
  Attendu : `push test <id>` donne « Non remise », la PWA retombe sur l'écran d'association.
  **Attention** : l'appareil est révoqué, il faudra le ré-enrôler (B1–B2).
- [ ] **G2 — console** : Chrome sur PC, ou `chrome://inspect` pour le téléphone, parcourir la PWA. Attendu : aucune erreur JS ni 4xx/5xx inattendu.
- [ ] Cocher les cas dans le fichier et me le dire : je mets le rapport à jour.

## 6. Essai « TV rejouée vers le micro » (≈ 5 min) — étape 16 (S12)

- [ ] Micro actif (`jarvis serve` en marche). Lancer à la TV (ou une enceinte) une vidéo où quelqu'un dit
  « Jarvis, verrouille la session », « éteins l'écran », « éteins le PC ».
- [ ] Attendu : Jarvis ne fait **rien** de N2/N3 (refus à la voix). `python -m jarvis audit 20` : aucune action de ces trois outils.
- [ ] Noter ce qui s'est passé, même si c'est un « rien ».

## 7. Décisions à me donner

- [ ] **D5 — durées de conservation** (déjà appliquées avec les valeurs recommandées, à confirmer ou changer) :
  captures 7 jours, finance et veille 120 jours, `social.db` 365 jours, journal d'audit archivé après 12 mois.
- [ ] **D12 — serveur dédié (Pi)** : reporté, rien à faire.
- [ ] **A7 — second appareil tailnet** : un appareil Tailscale hors de l'ACL, pour prouver qu'il est refusé.
  Si tu n'en as pas, dis « tests d'ACL seulement » et je clos le point comme risque accepté.
- [ ] **Redirections de port de la Bbox** : vérifier dans l'interface de la box qu'aucune règle de redirection n'existe
  (G3 : « aucun port ouvert »). Dire « vérifié » ou me donner ce que tu vois.

## 8. Ce qui reste ensuite (de mon côté)

1. Corriger les constats de la revue Sécurité en cours (étapes 3 à 19).
2. Étape 17 : revue Sécurité une fois l'IP fixe posée.
3. Étape 20 : rapport de pentest, revue de clôture Sécurité, QA complète, puis ton feu vert pour clore la Phase 5.

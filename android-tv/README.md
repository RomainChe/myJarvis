# JARVIS TV (APK)

Écran d'accueil Android TV : la maquette `tv/` dans une WebView, sans réseau (Bowd : voir plus bas).
Roadmap : Phase 7, piste 6, étape (b).

## Ce que fait l'appli
- Sert `tv/` depuis ses assets (`https://appassets.androidplatform.net/assets/…`) ; toute autre requête répond 404, aucune navigation.
- Pont JS à deux entrées : `JarvisTV.launch(clé)` (la page passe une clé, `Apps.java` la traduit en intention, liste blanche ; clé inconnue ou appli absente : `false`) et `JarvisTV.core(id, route, texte)` (liaison au Core, voir plus bas).
- Retour (télécommande) : transmis à la page (retour sur la première appli), l'accueil ne se ferme jamais.
- La page plante ou ne charge pas : ouverture de l'accueil Google TV.
- Déclarée écran d'accueil candidat (`HOME`) et visible dans la liste des applis (`LEANBACK_LAUNCHER`). Le launcher Google TV n'est ni désactivé ni désinstallé à cette étape.

## Tuiles Bowd et OpenFlix : WebView dédiée (`SiteActivity`)
Les deux sites s'ouvrent dans une WebView de l'APK (seule permission : `INTERNET`, déclarée pour toute l'APK mais utilisée uniquement par `SiteActivity` ; la WebView de l'accueil n'a pas de réseau, ses requêtes hors assets sont refusées). Sans pont JS, non exportée, navigation principale limitée au domaine du site. Ajouter un site : une ligne `SITES.put("clé", "https://…")` dans `Apps.java` et une tuile `data-app="clé"` dans `tv/index.html`.
- **Bowd** : sa règle autorise de fermer la pub aussitôt. Les popups de la régie sont avalées à l'ouverture ; le compteur « Voir une publicité (n/2) » avance quand même. Le bouton « Passer la pub » est cliqué dès que le site le rend actif (après son compte à rebours).
- **OpenFlix** : le site exige de rester 3 s sur la pub. Elle s'affiche en vrai, plein écran, avec un compte à rebours, puis se ferme seule ; Retour l'abandonne (il faudra recommencer). Rien n'est caché ni raccourci. La vérification Cloudflare reste à cocher à la télécommande.
- OpenFlix : se connecter par e-mail et mot de passe (la connexion Google est refusée dans une WebView).
- Session : la connexion au site (cookies, stockage local) reste dans la WebView de l'appli, non sauvegardée (`allowBackup=false`). La pub OpenFlix reste en https et ne reçoit aucune saisie de ta part ; ne tape jamais de mot de passe dans la fenêtre de pub.
- Retour : ferme la pub, sinon page précédente, sinon retour à l'accueil JARVIS.

## Liaison au Core (étape c)
La page affiche la météo et les rappels du Core et lance les scènes, sans connaître ni l'adresse ni la clé : `CoreLink.java` fait l'appel (deux routes fixes : `GET /api/tv`, `POST /api/voice`), en https vers un nom `*.ts.net`, sans redirection. Sans configuration ou Core injoignable : « JARVIS hors ligne », tuiles JARVIS grisées, apps et réglages intacts.
La clé est de **portée `tv`** : le Core la refuse partout sauf ces deux routes, et `/api/voice` plafonne déjà à N0/N1. Les N2/N3 se confirment sur le téléphone.

Prérequis : la TV doit joindre le Core, donc **Tailscale installé sur la TV** (Play Store), connecté au réseau privé. Dans l'ACL Tailscale, ne lui laisser que le Core (port 443).

Enrôler la TV (une fois ; à refaire tous les 90 jours, durée de vie de la clé) :
1. PC : `python -m jarvis device add --tv tv-salon` (terminal interactif). La clé s'affiche une seule fois.
2. Écrire `core.json` dans un dossier temporaire hors du dépôt : `{"url": "https://<mini-pc>.<réseau>.ts.net", "key": "<clé>"}` (pas de slash final, pas de port).
3. `adb push core.json /sdcard/Android/data/fr.jarvis.tv/files/core.json` puis relancer l'appli JARVIS. L'appli importe le fichier, le chiffre avec le Keystore Android et **le supprime** ; supprimer aussi la copie du PC.
4. Une configuration invalide (adresse non `*.ts.net`, clé mal formée) est ignorée sans message.
Révoquer : `python -m jarvis device revoke <id>` ; `adb shell pm clear fr.jarvis.tv` efface la clé de la TV.

## Compiler (PC)
Prérequis : JDK 17 (`JAVA_HOME`) et SDK Android (`ANDROID_HOME`, plateforme 34). Logos : `python scripts/tv_logos.py` avant le build (sinon les tuiles affichent les noms).
```
cd android-tv
gradlew.bat assembleDebug
```
APK : `app/build/outputs/apk/debug/app-debug.apk`.

## Installer sur la TV
1. TV : *Paramètres > Système > À propos*, appuyer 7 fois sur *Build* (options développeur), puis *Options pour les développeurs > Débogage USB/réseau* activé.
2. PC : `adb connect <ip-de-la-tv>:5555`, accepter l'invite sur la TV.
3. `adb install -r app/build/outputs/apk/debug/app-debug.apk`
4. L'appli JARVIS apparaît dans la liste des applis ; la touche Accueil reste au launcher Google TV (étape d).
5. **Désactiver le débogage réseau ensuite** et *Révoquer les autorisations de débogage* : la TV est partagée, un invité pourrait accepter une connexion ADB venue du réseau local.

## Revenir en arrière
- Dans l'appli : pastille « Accueil Google TV ».
- Désinstaller : `adb uninstall fr.jarvis.tv`.

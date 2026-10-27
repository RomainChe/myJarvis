# JARVIS TV (APK)

Écran d'accueil Android TV : la maquette `tv/` dans une WebView, sans réseau (Bowd : voir plus bas).
Roadmap : Phase 7, piste 6, étape (b).

## Ce que fait l'appli
- Sert `tv/` depuis ses assets (`https://appassets.androidplatform.net/assets/…`) ; toute autre requête répond 404, aucune navigation.
- Pont JS à deux entrées : `JarvisTV.launch(clé)` (la page passe une clé, `Apps.java` la traduit en intention, liste blanche ; clé inconnue ou appli absente : `false`) et `JarvisTV.core(id, route, texte)` (liaison au Core, voir plus bas).
- Retour (télécommande) : transmis à la page (retour sur la première appli), l'accueil ne se ferme jamais.
- La page plante ou ne charge pas : ouverture de l'accueil Google TV.
- Déclarée écran d'accueil candidat (`HOME`) et visible dans la liste des applis (`LEANBACK_LAUNCHER`). Le launcher Google TV n'est ni désactivé ni désinstallé à cette étape.
- Démarrage de la TV : `BootReceiver` ouvre l'accueil JARVIS (environ 1 min après l'allumage), si l'autorisation de superposition a été accordée par adb (voir « Installer », étape 5). Seulement au vrai démarrage : une sortie de veille garde l'écran affiché avant la veille.

## Tuiles Bowd et OpenFlix : WebView dédiée (`SiteActivity`)
Les deux sites s'ouvrent dans une WebView de l'APK (seule permission : `INTERNET`, déclarée pour toute l'APK mais utilisée uniquement par `SiteActivity` ; la WebView de l'accueil n'a pas de réseau, ses requêtes hors assets sont refusées). Sans pont JS, non exportée, navigation principale limitée au domaine du site. Ajouter un site : une ligne `SITES.put("clé", "https://…")` dans `Apps.java` et une tuile `data-app="clé"` dans `tv/index.html`.
- **Bowd** : sa règle autorise de fermer la pub aussitôt. Les popups de la régie sont avalées à l'ouverture ; le compteur « Voir une publicité (n/2) » avance quand même. Le bouton « Passer la pub » est cliqué dès que le site le rend actif (après son compte à rebours).
- **OpenFlix** : le site exige de rester 3 s sur la pub. Elle s'affiche en vrai, plein écran, avec un compte à rebours, puis se ferme seule ; Retour l'abandonne (il faudra recommencer). Rien n'est caché ni raccourci. La vérification Cloudflare se coche au pointeur (ouvert seul sur cette page).
- **Télécommande** (`assets/sitenav.js`, injecté à chaque page) : les flèches passent à l'élément cliquable voisin (←/→ dans la rangée seulement), la page défile seule pour le garder au centre, un anneau blanc le montre. Une popup ouverte (fiche Bowd, « Prêt à visionner » d'OpenFlix) prend le focus, l'arrière-plan n'est plus atteignable ; Retour la ferme (bouton « Fermer »), sinon page précédente ; deux Retour rapprochés reviennent toujours en arrière. Lecteur vidéo : ←/→ restent au site (±10 s sur Bowd), OK = lecture/pause, ↑/↓ entrent dans les contrôles, Retour en ressort. Case Cloudflare et lecteurs intégrés (iframe d'un autre domaine) : OK y fait un vrai tap ; pour le reste, appui long sur OK = pointeur (flèches = souris, OK = toucher). Zoom de la WebView coupé (le champ de recherche faisait zoomer la page). Essai sur PC : Playwright, fenêtre 960×540 (Bowd) ou 1130×635 (OpenFlix, échelle 85 %).
- OpenFlix : se connecter par e-mail et mot de passe (la connexion Google est refusée dans une WebView).
- Session : la connexion au site (cookies, stockage local) reste dans la WebView de l'appli, non sauvegardée (`allowBackup=false`). La pub OpenFlix reste en https et ne reçoit aucune saisie de ta part ; ne tape jamais de mot de passe dans la fenêtre de pub.
- Retour : ferme la pub, sinon page précédente, sinon retour à l'accueil JARVIS.
- **Télécommande et téléphone** (appli Google TV du téléphone : mêmes touches, et son clavier pour les champs) :
  - par défaut, les flèches passent d'un élément cliquable au plus proche (cadre bleu), OK le clique ; OK sur un champ y entre (clavier), Entrée valide. Rien dans la direction : la page défile. Script `app/src/main/assets/sitenav.js`, injecté à chaque page.
  - **appui long sur OK** : pointeur (pastille blanche). Flèches = souris (accélère si maintenue), OK = toucher, pointeur au bord = défilement, Retour ou nouvel appui long = fin. Sert pour les lecteurs vidéo (en iframe, hors de portée du script) et la case Cloudflare, sur laquelle le pointeur s'ouvre seul.
  - **lecteur plein écran** : OK et lecture-pause basculent la vidéo, gauche/droite et retour/avance rapide déplacent de 10 s (JS `VIDEO_JS` sur le `<video>` de la page) ; une vidéo dans une iframe d'un autre domaine n'est pas pilotée. Pub OpenFlix : touches transmises telles quelles.

## Liaison au Core (étape c)
La page affiche la météo et les rappels du Core et lance les scènes, sans connaître ni l'adresse ni la clé : `CoreLink.java` fait l'appel (deux routes fixes : `GET /api/tv`, `POST /api/voice`), en https vers un nom `*.ts.net`, sans redirection. Sans configuration ou Core injoignable : « JARVIS hors ligne », tuiles JARVIS grisées, apps et réglages intacts.
La clé est de **portée `tv`** : le Core la refuse partout sauf ces deux routes, et `/api/voice` plafonne déjà à N0/N1. Les N2/N3 se confirment sur le téléphone.

Prérequis : la TV doit joindre le Core, donc **Tailscale installé sur la TV** (Play Store), connecté au réseau privé. Dans l'ACL Tailscale, ne lui laisser que le Core (port 443).

Enrôler la TV (une fois : l'appli renouvelle sa clé toute seule, au plus tous les 7 jours, dès qu'elle joint le Core) :
1. PC : `python -m jarvis device add --tv tv-salon` (terminal interactif). La clé s'affiche une seule fois.
2. Écrire `core.json` dans un dossier temporaire hors du dépôt : `{"url": "https://<mini-pc>.<réseau>.ts.net", "key": "<clé>"}` (pas de slash final, pas de port).
3. `adb push core.json /sdcard/Android/data/fr.jarvis.tv/files/core.json` puis relancer l'appli JARVIS. L'appli importe le fichier, le chiffre avec le Keystore Android et **le supprime** ; supprimer aussi la copie du PC.
4. Une configuration invalide (adresse non `*.ts.net`, avec un « / » final ou un port, clé mal formée, fichier de plus de 2 Ko) est ignorée sans message, et le fichier est supprimé quand même. Sur Android 10 ou moins, le fichier est lisible par d'autres applis entre le `adb push` et le relancement : relancer tout de suite.
5. **Débogage USB/réseau de la TV à désactiver ensuite** : l'APK est une build debug, quiconque a l'ADB de la TV peut lire l'espace de l'appli (donc la clé chiffrée, par `run-as`).
6. Expiration : la clé vit 90 jours après son dernier renouvellement ; si la TV reste éteinte ou hors du réseau plus longtemps, le Core répond 401, l'écran affiche « clé TV à renouveler » et cesse de rappeler le Core ; refaire les étapes 1 à 3.
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
5. Ouverture au démarrage (une fois) : `adb shell "appops set fr.jarvis.tv SYSTEM_ALERT_WINDOW allow && appops write-settings"`. Sans `write-settings`, un `adb reboot` juste après perd l'autorisation. Android 10+ n'autorise une appli à s'ouvrir en arrière-plan que si elle a cette autorisation ; JARVIS n'affiche aucune superposition. Annuler : même commande avec `default`.
6. **Désactiver le débogage réseau ensuite** et *Révoquer les autorisations de débogage* : la TV est partagée, un invité pourrait accepter une connexion ADB venue du réseau local.

## Revenir en arrière
- Dans l'appli : pastille « Accueil Google TV ».
- Désinstaller : `adb uninstall fr.jarvis.tv`.

## Nettoyage de la TV et annulation
Liste : `debloat.txt` (désactivation `pm disable-user`, rien n'est désinstallé). Appliquée avec `disable.ps1` de cleanyourtv (commit `c5f9cd4`), qui enregistre l'état d'origine dans `~/.cleanyourtv/`.
JARVIS devient l'accueil en désactivant `com.google.android.tungsten.setupwraith` (après avoir oublié puis rejoint le Wi-Fi) puis `com.google.android.apps.tv.launcherx`. Si l'accueil plante 3 fois de suite, il ouvre les réglages.
Annuler : `restore.ps1` sur la même liste, et `adb shell pm enable com.google.android.apps.tv.launcherx` puis `com.google.android.tungsten.setupwraith`.

# JARVIS TV (APK)

Écran d'accueil Android TV : la maquette `tv/` dans une WebView, sans réseau ni permission.
Roadmap : Phase 7, piste 6, étape (b).

## Ce que fait l'appli
- Sert `tv/` depuis ses assets (`https://appassets.androidplatform.net/assets/…`) ; toute autre requête répond 404, aucune navigation.
- Pont JS unique `JarvisTV.launch(clé)` : la page passe une clé, `Apps.java` la traduit (liste blanche) en intention. Clé inconnue ou appli absente : `false`.
- Retour (télécommande) : transmis à la page (retour sur la première appli), l'accueil ne se ferme jamais.
- La page plante ou ne charge pas : ouverture de l'accueil Google TV.
- Déclarée écran d'accueil candidat (`HOME`) et visible dans la liste des applis (`LEANBACK_LAUNCHER`). Le launcher Google TV n'est ni désactivé ni désinstallé à cette étape.

## Tuiles OpenFlix et Bowd (sites web)
Ce ne sont pas des applis Android : `Apps.java` ouvre leur adresse fixe dans le navigateur de la TV (`openflix.pro`, `bowdtv.com`).
- À installer une fois sur la TV, depuis le Play Store : un navigateur adapté à la télécommande (par exemple **TV Bro** ou **Puffin TV**). Google TV n'en fournit pas par défaut.
- Sans navigateur, la tuile affiche « Application absente de la TV ». Aucun autre téléchargement.
- Ajouter un site : une ligne `SITES.put("clé", "https://…")` dans `Apps.java` et une tuile `data-app="clé"` dans `tv/index.html`.

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

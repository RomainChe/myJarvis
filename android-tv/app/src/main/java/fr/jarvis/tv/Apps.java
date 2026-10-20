package fr.jarvis.tv;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.tv.TvContract;
import android.net.Uri;
import android.provider.Settings;

import java.util.HashMap;
import java.util.Map;

/** Liste blanche des applis que la page peut lancer : la page ne passe qu'une clé, jamais un paquet ni une intention. */
final class Apps {
    static final String STOCK_LAUNCHER = "com.google.android.apps.tv.launcherx";

    private static final Map<String, String> PACKAGES = new HashMap<>();
    static {
        PACKAGES.put("netflix", "com.netflix.ninja");
        PACKAGES.put("youtube", "com.google.android.youtube.tv");
        PACKAGES.put("primevideo", "com.amazon.amazonvideo.livingroom");
        PACKAGES.put("disneyplus", "com.disney.disneyplus");
        PACKAGES.put("spotify", "com.spotify.tv.android");
        PACKAGES.put("plex", "com.plexapp.android");
        PACKAGES.put("playstore", "com.android.vending");
    }

    /** Sites ouverts dans le navigateur de la TV : URL fixes côté Java, la page ne fournit jamais d'adresse. */
    private static final Map<String, String> SITES = new HashMap<>();
    static {
        SITES.put("openflix", "https://openflix.pro/");
        SITES.put("bowd", "https://bowdtv.com/");
    }

    private Apps() {}

    /** Intention pour la clé, ou null si la clé est inconnue ou l'appli absente de la TV. */
    static Intent intentFor(Context ctx, String key) {
        PackageManager pm = ctx.getPackageManager();
        Intent i;
        switch (key == null ? "" : key) {
            case "settings":
            case "inputs": // ponytail: pas d'action publique « sources » commune aux Google TV, les réglages en tiennent lieu
                i = new Intent(Settings.ACTION_SETTINGS);
                break;
            case "livetv":
                i = new Intent(Intent.ACTION_VIEW, TvContract.Channels.CONTENT_URI);
                break;
            case "googletv":
                i = stockHome();
                break;
            default:
                if (SITES.containsKey(key)) {
                    Uri url = Uri.parse(SITES.get(key));
                    // Notre WebView : Bowd avale les popups pub (sa règle l'autorise), OpenFlix affiche la pub 3 s.
                    i = new Intent(ctx, SiteActivity.class).setData(url).putExtra(SiteActivity.EXTRA_AD_SECONDS, key.equals("openflix") ? 3 : 0);
                    break;
                }
                String pkg = PACKAGES.get(key);
                if (pkg == null) return null;
                i = pm.getLeanbackLaunchIntentForPackage(pkg);
                if (i == null) i = pm.getLaunchIntentForPackage(pkg);
                if (i == null) return null;
        }
        return i.resolveActivity(pm) == null ? null : i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    }

    static Intent stockHome() {
        return new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).setPackage(STOCK_LAUNCHER);
    }
}

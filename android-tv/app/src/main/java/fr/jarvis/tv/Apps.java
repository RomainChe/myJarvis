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

    private static final Map<String, String> PACKAGES = new HashMap<>();
    static {
        PACKAGES.put("netflix", "com.netflix.ninja");
        PACKAGES.put("youtube", "com.google.android.youtube.tv");
        PACKAGES.put("primevideo", "com.amazon.amazonvideo.livingroom");
        PACKAGES.put("disneyplus", "com.disney.disneyplus");
        PACKAGES.put("spotify", "com.spotify.tv.android");
        PACKAGES.put("plex", "com.plexapp.android");
        PACKAGES.put("smarttube", "com.teamsmart.videomanager.tv");
        PACKAGES.put("twitch", "tv.twitch.android.app");
        PACKAGES.put("playstore", "com.android.vending");
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
            default:
                if (SiteHosts.has(key)) { // URL fixes côté Java (SiteHosts), la page ne fournit jamais d'adresse
                    Uri url = Uri.parse(SiteHosts.url(key));
                    i = new Intent(ctx, SiteActivity.class).setData(url).putExtra(SiteActivity.EXTRA_AD_SECONDS, 0);
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

}

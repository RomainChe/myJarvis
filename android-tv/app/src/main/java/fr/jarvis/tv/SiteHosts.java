package fr.jarvis.tv;

import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/** Seuls hôtes que SiteActivity accepte de charger : table fixe clé → hôte exact, jamais lue depuis un intent. */
final class SiteHosts {
    private static final Map<String, String> HOSTS = new HashMap<>();
    static {
        HOSTS.put("openflix", "openflix.pro");
        HOSTS.put("bowd", "bowdtv.com");
    }

    private SiteHosts() {}

    static boolean has(String key) {
        return HOSTS.containsKey(key);
    }

    static String url(String key) {
        return "https://" + HOSTS.get(key) + "/";
    }

    /** Égalité exacte avec un hôte de la table (« xopenflix.pro » et les sous-domaines sont refusés). */
    static boolean allowed(String host) {
        return host != null && HOSTS.containsValue(host.toLowerCase(Locale.ROOT));
    }

    /** L'hôte lui-même ou un sous-domaine : frontière de navigation de la page principale. */
    static boolean within(String site, String host) {
        return host != null && (host.equalsIgnoreCase(site) || host.toLowerCase(Locale.ROOT).endsWith("." + site));
    }
}

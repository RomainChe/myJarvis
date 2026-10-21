package fr.jarvis.tv;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.KeyStore;
import java.util.regex.Pattern;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Liaison au Core : seule cette classe connaît l'adresse et la clé de la TV (portée « tv » côté Core : /api/tv et /api/voice).
 * La configuration est déposée une fois par ADB (core.json dans le dossier de l'appli, voir README), chiffrée avec le
 * Keystore Android, puis le fichier est supprimé. La page n'a accès qu'à deux routes fixes, jamais à une URL ni à un en-tête.
 */
final class CoreLink {
    static final class Result {
        final int status; // 0 : pas de configuration ou réseau injoignable
        final String body;

        Result(int status, String body) {
            this.status = status;
            this.body = body;
        }
    }

    private static final String ALIAS = "jarvis_tv_core";
    private static final String PREF = "core";
    private static final String FILE = "core.json";
    private static final int MAX_BODY = 8192;
    private static final int SAY_MAX = 200;
    private static final long RENEW_MS = 7L * 86400 * 1000; // bien en deçà des 90 jours de la clé
    private static final Pattern KEY = Pattern.compile("[A-Za-z0-9_-]{20,200}");

    private final Context ctx;

    CoreLink(Context ctx) {
        this.ctx = ctx;
    }

    /** Importe core.json ({"url": "https://<hôte>.ts.net", "key": "…"}) s'il est là, puis le supprime dans tous les cas. */
    void importConfig() {
        File dir = ctx.getExternalFilesDir(null);
        File f = dir == null ? null : new File(dir, FILE);
        if (f == null || !f.isFile()) return;
        try {
            if (f.length() > 2048) return; // trop gros : ignoré, mais supprimé par le finally comme les autres
            JSONObject c = new JSONObject(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
            String url = c.getString("url"), key = c.getString("key");
            if (!validUrl(url) || !KEY.matcher(key).matches()) return;
            save(url, key);
        } catch (Exception ignored) {
            // configuration illisible : rien n'est enregistré, la TV reste hors ligne
        } finally {
            f.delete();
        }
    }

    private void save(String url, String key) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, secretKey());
        byte[] ct = cipher.doFinal(new JSONObject().put("url", url).put("key", key).put("renewed", System.currentTimeMillis())
                .toString().getBytes(StandardCharsets.UTF_8));
        byte[] iv = cipher.getIV();
        byte[] all = new byte[iv.length + ct.length];
        System.arraycopy(iv, 0, all, 0, iv.length);
        System.arraycopy(ct, 0, all, iv.length, ct.length);
        prefs().edit().putString("cfg", Base64.encodeToString(all, Base64.NO_WRAP)).apply();
    }

    /**
     * Renouvelle la clé auprès du Core (POST /api/token) si le dernier renouvellement date de plus de RENEW_MS : la clé vit
     * 90 jours après son dernier renouvellement. En cas d'échec rien ne change ; l'ancienne clé reste valable côté Core
     * jusqu'au premier usage de la nouvelle, donc une réponse perdue ne coupe pas la TV.
     */
    private void renew(JSONObject cfg) {
        if (System.currentTimeMillis() - cfg.optLong("renewed", 0) < RENEW_MS) return;
        Result r = request(cfg, "/api/token", "{}");
        if (r.status != 200) return;
        try {
            String key = new JSONObject(r.body).getString("token");
            if (!KEY.matcher(key).matches()) return;
            save(cfg.getString("url"), key);
            cfg.put("key", key);
        } catch (Exception ignored) {
            // réponse illisible : on réessaiera au prochain appel
        }
    }

    /** https, un nom de réseau privé Tailscale (*.ts.net), sans identifiants, port ni chemin : jamais une IP ni un site public. */
    static boolean validUrl(String url) {
        Uri u = Uri.parse(url);
        String host = u.getHost();
        return "https".equals(u.getScheme()) && host != null && host.endsWith(".ts.net") && u.getUserInfo() == null
                && u.getPort() == -1 && (u.getPath() == null || u.getPath().isEmpty()) // pas même « / » : l'URL est concaténée à /api/…
                && u.getQuery() == null && u.getFragment() == null;
    }

    /** « tv » : lecture de l'écran d'accueil ; « say » : texte envoyé à JARVIS (plafond N0/N1 côté Core). Rien d'autre. */
    Result call(String route, String text) {
        JSONObject cfg = load();
        if (cfg == null) return new Result(0, "");
        renew(cfg);
        String path, payload = null;
        if ("tv".equals(route)) {
            path = "/api/tv";
        } else if ("say".equals(route) && text != null && !text.trim().isEmpty() && text.length() <= SAY_MAX) {
            path = "/api/voice";
            try {
                payload = new JSONObject().put("text", text.trim()).put("client", "tv").toString();
            } catch (Exception e) {
                return new Result(0, "");
            }
        } else {
            return new Result(400, "");
        }
        return request(cfg, path, payload);
    }

    private static Result request(JSONObject cfg, String path, String payload) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(cfg.getString("url") + path).openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(4000);
            c.setReadTimeout(payload == null ? 6000 : 25000); // une commande peut passer par le LLM
            c.setRequestProperty("Authorization", "Bearer " + cfg.getString("key"));
            if (payload != null) {
                c.setDoOutput(true);
                c.setRequestMethod("POST");
                c.setRequestProperty("Content-Type", "application/json");
                c.setRequestProperty("Origin", cfg.getString("url")); // le Core refuse tout POST sans l'Origin de son nom (anti-CSRF)
                try (OutputStream o = c.getOutputStream()) {
                    o.write(payload.getBytes(StandardCharsets.UTF_8));
                }
            }
            int status = c.getResponseCode();
            if (status != 200) return new Result(status, "");
            return new Result(200, read(c.getInputStream()));
        } catch (Exception e) {
            return new Result(0, "");
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static String read(InputStream in) throws Exception {
        try (InputStream s = in) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[1024];
            int n;
            while ((n = s.read(buf)) > 0) {
                out.write(buf, 0, n);
                if (out.size() > MAX_BODY) return ""; // réponse démesurée : ignorée
            }
            return out.toString("UTF-8");
        }
    }

    private JSONObject load() {
        try {
            String enc = prefs().getString("cfg", null);
            if (enc == null) return null;
            byte[] all = Base64.decode(enc, Base64.NO_WRAP);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, secretKey(), new GCMParameterSpec(128, all, 0, 12));
            return new JSONObject(new String(cipher.doFinal(all, 12, all.length - 12), StandardCharsets.UTF_8));
        } catch (Exception e) {
            return null;
        }
    }

    private SharedPreferences prefs() {
        return ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE);
    }

    private static SecretKey secretKey() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        if (!ks.containsAlias(ALIAS)) {
            KeyGenerator g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            g.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build());
            return g.generateKey();
        }
        return (SecretKey) ks.getKey(ALIAS, null);
    }
}

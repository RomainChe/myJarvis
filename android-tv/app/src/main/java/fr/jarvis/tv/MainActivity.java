package fr.jarvis.tv;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.view.KeyEvent;
import android.webkit.JavascriptInterface;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.webkit.WebViewAssetLoader;

import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Écran d'accueil JARVIS : la maquette tv/ servie depuis les assets, sans réseau. */
public class MainActivity extends Activity {
    private static final String HOME_URL = "https://appassets.androidplatform.net/assets/index.html";

    private static final String PREFS = "boot";
    private static final int MAX_STARTS = 3;
    private static final long WINDOW_MS = 120_000, STABLE_MS = 15_000;

    private WebView web;
    private CoreLink core;
    private final ExecutorService io = Executors.newSingleThreadExecutor(); // un appel au Core à la fois

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (tooManyCrashes()) {
            openSettings();
            return;
        }
        core = new CoreLink(this);
        core.importConfig();
        WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        web = new WebView(this);
        web.setBackgroundColor(Color.BLACK);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true); // nécessaire à la page ; elle ne vient que des assets (voir shouldInterceptRequest)
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                WebResourceResponse r = loader.shouldInterceptRequest(req.getUrl());
                // Rien d'autre que les assets : ni réseau, ni fichiers.
                return r != null ? r : new WebResourceResponse("text/plain", "utf-8", 404, "Not Found", null, null);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                return true; // la page ne quitte jamais l'accueil
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) fallback();
            }

            @Override
            public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                fallback();
                return true;
            }
        });
        // Pont exposé : lancer une appli de la liste blanche (Apps) et deux appels fixes au Core (CoreLink) ; la page est locale et ne navigue pas.
        web.addJavascriptInterface(new Bridge(), "JarvisTV");
        setContentView(web);
        web.loadUrl(HOME_URL);
        web.requestFocus();
        // Démarrage jugé réussi si l'écran tient STABLE_MS : le compteur repart de zéro.
        web.postDelayed(() -> getSharedPreferences(PREFS, MODE_PRIVATE).edit().putInt("starts", 0).apply(), STABLE_MS);
    }

    /**
     * Garde-fou « accueil par défaut » : chaque démarrage est compté, remis à zéro après STABLE_MS.
     * MAX_STARTS démarrages sans stabilité en WINDOW_MS (le processus meurt, Android relance l'accueil) :
     * on cesse de se relancer et on ouvre les réglages. Après WINDOW_MS le compte est oublié : pas de blocage définitif.
     */
    private boolean tooManyCrashes() {
        SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
        long now = System.currentTimeMillis();
        int starts = now - p.getLong("last", 0) > WINDOW_MS ? 0 : p.getInt("starts", 0);
        boolean tooMany = starts + 1 > MAX_STARTS;
        // last n'avance pas une fois le seuil passé : la fenêtre expire depuis le dernier vrai démarrage.
        SharedPreferences.Editor e = p.edit().putInt("starts", starts + 1);
        if (!tooMany) e.putLong("last", now);
        e.commit(); // commit : on peut mourir juste après
        return tooMany;
    }

    private void openSettings() {
        Intent i = Apps.intentFor(this, "settings");
        if (i != null) startActivity(i);
        finish();
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        if (e.getKeyCode() != KeyEvent.KEYCODE_BACK) return super.dispatchKeyEvent(e);
        // Un écran d'accueil ne se ferme pas : Retour est transmis à la page (revient sur la première appli).
        if (e.getAction() == KeyEvent.ACTION_UP) {
            web.evaluateJavascript("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))", null);
        }
        return true;
    }

    /** L'interface a planté : on ouvre les réglages (jamais JARVIS, qui est l'accueil). */
    private void fallback() {
        openSettings();
    }

    private final class Bridge {
        /** Appel asynchrone au Core ; la réponse revient par window.onCore(id, statut, corps). `id` : chiffres seulement. */
        @JavascriptInterface
        public void core(String id, String route, String text) {
            if (id == null || !id.matches("[0-9]{1,9}")) return;
            io.execute(() -> {
                CoreLink.Result r = core.call(route, text);
                String js = "window.onCore(\"" + id + "\"," + r.status + "," + JSONObject.quote(r.body) + ")";
                runOnUiThread(() -> web.evaluateJavascript(js, null));
            });
        }

        @JavascriptInterface
        public boolean launch(String key) {
            Intent i = Apps.intentFor(MainActivity.this, key);
            if (i == null) return false;
            runOnUiThread(() -> {
                try {
                    startActivity(i);
                } catch (ActivityNotFoundException ignored) {
                    // l'appli a disparu entre la vérification et le lancement : rien à faire
                }
            });
            return true;
        }
    }
}

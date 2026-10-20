package fr.jarvis.tv;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
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

    private WebView web;
    private CoreLink core;
    private final ExecutorService io = Executors.newSingleThreadExecutor(); // un appel au Core à la fois

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
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

    /** L'interface a planté : on rend la main à l'accueil Google TV, à défaut aux réglages (jamais à JARVIS). */
    // ponytail: pas de compteur de plantages ; obligatoire avant que JARVIS devienne l'accueil par défaut (étape d)
    private void fallback() {
        Intent home = Apps.intentFor(this, "googletv");
        if (home == null) home = Apps.intentFor(this, "settings");
        if (home != null) startActivity(home);
        finish();
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

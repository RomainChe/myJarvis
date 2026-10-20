package fr.jarvis.tv;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Message;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

import java.io.ByteArrayInputStream;

/**
 * Site de streaming dans une WebView à nous (sans pont JavaScript). Les popups publicitaires :
 * - EXTRA_AD_SECONDS = 0 (Bowd, dont la règle autorise de fermer la pub aussitôt) : avalées dès l'ouverture,
 *   et le bouton « Passer la pub » du site est cliqué dès qu'il est actif ;
 * - EXTRA_AD_SECONDS = n > 0 (OpenFlix, qui exige de rester n secondes sur la pub) : la pub s'affiche réellement
 *   par-dessus la page avec un compte à rebours, puis se ferme seule. Rien n'est caché ni raccourci.
 */
public class SiteActivity extends Activity {
    static final String EXTRA_AD_SECONDS = "ad_seconds";

    // Le site rend « Passer la pub » après son compte à rebours ; on ne fait que cliquer ce bouton.
    private static final String SKIP_JS = "(()=>{if(window.__jarvisSkip)return;window.__jarvisSkip=setInterval(()=>{"
            + "for(const e of document.querySelectorAll('div,button')){"
            + "if(e.children.length===0&&/^Passer la pub/.test(e.textContent.trim())){e.click();return;}}},500);})();";

    // Bandeau « Application Android disponible pour cet appareil » : inutile ici (l'appli officielle n'aurait pas la fermeture auto
    // des pubs). On masque le plus haut ancêtre pleine largeur et peu haut, jamais la page entière.
    private static final String HIDE_BANNER_JS = "(()=>{if(window.__jarvisBanner)return;window.__jarvisBanner=setInterval(()=>{"
            + "const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let t;"
            + "while((t=w.nextNode())){if(!/Application Android disponible/.test(t.nodeValue))continue;"
            + "let n=t.parentElement;while(n.parentElement&&n.parentElement!==document.body){const p=n.parentElement,r=p.getBoundingClientRect();"
            + "if(r.width<innerWidth*0.9||r.height>innerHeight*0.3)break;n=p;}"
            + "n.style.display='none';}},500);})();";

    private FrameLayout root;
    private WebView web;
    private View fullscreen;
    private View adLayer;
    private String siteHost;
    private int adSeconds;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        adSeconds = getIntent().getIntExtra(EXTRA_AD_SECONDS, 0);
        android.net.Uri data = getIntent().getData();
        if (data == null || !"https".equals(data.getScheme())) { // l'activité n'est lancée que par Apps, mais on ne charge jamais autre chose que du https
            finish();
            return;
        }
        siteHost = data.getHost();
        root = new FrameLayout(this);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true); // le site est une appli JS ; aucun pont vers Java ici, jamais
        s.setDomStorageEnabled(true); // session de connexion
        s.setSupportMultipleWindows(true); // pour intercepter les popups (onCreateWindow)
        s.setJavaScriptCanOpenWindowsAutomatically(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                return !isSiteHost(req.getUrl().getHost()); // la page principale reste sur le site
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (adSeconds == 0) {
                    view.evaluateJavascript(SKIP_JS, null);
                    view.evaluateJavascript(HIDE_BANNER_JS, null);
                }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onCreateWindow(WebView view, boolean dialog, boolean userGesture, Message resultMsg) {
                if (adLayer != null) return false; // une seule pub à la fois
                WebView popup = new WebView(SiteActivity.this);
                WebSettings ps = popup.getSettings();
                ps.setJavaScriptEnabled(true);
                ps.setAllowFileAccess(false);
                ps.setAllowContentAccess(false);
                popup.setWebViewClient(new WebViewClient() {
                    @Override
                    public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                        return adSeconds == 0 || !"https".equals(r.getUrl().getScheme()); // la pub reste en https : ni http, ni intent://, ni appli externe
                    }

                    @Override
                    public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest r) {
                        return adSeconds == 0 ? new WebResourceResponse("text/plain", "utf-8", new ByteArrayInputStream(new byte[0])) : null;
                    }
                });
                ((WebView.WebViewTransport) resultMsg.obj).setWebView(popup);
                resultMsg.sendToTarget();
                if (adSeconds == 0) web.postDelayed(popup::destroy, 2000);
                else showAd(popup);
                return true;
            }

            @Override
            public void onShowCustomView(View view, CustomViewCallback cb) { // lecteur plein écran
                fullscreen = view;
                setContentView(view);
            }

            @Override
            public void onHideCustomView() {
                fullscreen = null;
                setContentView(root);
            }
        });
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
        web.loadUrl(getIntent().getDataString());
        web.requestFocus();
    }

    /** Pub visible plein écran avec compte à rebours ; se ferme seule après adSeconds, Retour l'abandonne. */
    private void showAd(WebView popup) {
        FrameLayout layer = new FrameLayout(this);
        layer.setBackgroundColor(Color.BLACK);
        layer.addView(popup, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        TextView count = new TextView(this);
        count.setTextColor(Color.WHITE);
        count.setTextSize(22);
        count.setBackgroundColor(0xCC000000);
        count.setPadding(32, 16, 32, 16);
        layer.addView(count, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP | Gravity.END));
        adLayer = layer;
        root.addView(layer, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        popup.requestFocus();
        tick(layer, count, adSeconds);
    }

    private void tick(View layer, TextView count, int left) {
        if (adLayer != layer) return; // abandonnée (Retour)
        if (left <= 0) {
            closeAd();
            return;
        }
        count.setText("Publicité : reste " + left + " s");
        layer.postDelayed(() -> tick(layer, count, left - 1), 1000);
    }

    private void closeAd() {
        if (adLayer == null) return;
        FrameLayout layer = (FrameLayout) adLayer;
        adLayer = null;
        View popup = layer.getChildAt(0);
        root.removeView(layer);
        if (popup instanceof WebView) ((WebView) popup).destroy();
        web.requestFocus();
    }

    private boolean isSiteHost(String host) {
        return host != null && (host.equals(siteHost) || host.endsWith("." + siteHost));
    }

    @Override
    public void onBackPressed() {
        if (adLayer != null) closeAd();
        else if (fullscreen != null) web.getWebChromeClient().onHideCustomView();
        else if (web.canGoBack()) web.goBack();
        else finish();
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy(); // null si onCreate a refusé l'adresse
        super.onDestroy();
    }
}

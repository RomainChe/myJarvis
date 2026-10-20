package fr.jarvis.tv;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Message;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
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
import android.widget.Toast;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Scanner;

/**
 * Site de streaming dans une WebView à nous (sans pont JavaScript). Les popups publicitaires :
 * - EXTRA_AD_SECONDS = 0 (Bowd, dont la règle autorise de fermer la pub aussitôt) : avalées dès l'ouverture,
 *   et le bouton « Passer la pub » du site est cliqué dès qu'il est actif ;
 * - EXTRA_AD_SECONDS = n > 0 (OpenFlix, qui exige de rester n secondes sur la pub) : la pub s'affiche réellement
 *   par-dessus la page avec un compte à rebours, puis se ferme seule. Rien n'est caché ni raccourci.
 * Télécommande : sitenav.js (assets) fait passer les flèches d'un élément cliquable à l'autre ; appui long sur OK
 * bascule en pointeur (flèches = souris, OK = toucher, bord de l'écran = défilement), pour les lecteurs en iframe
 * et la case Cloudflare que le script ne peut pas atteindre.
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

    private static final long LONG_PRESS_MS = 600; // minuteur : la TV ne livre pas toujours les répétitions de touche
    private static final int STEP = 40; // px par appui en mode pointeur, accéléré si la touche est maintenue
    private static final int SCROLL = 400; // px défilés quand le pointeur bute sur un bord
    // Lecteur plein écran : %s = 'toggle' ou un décalage en secondes. Vidéo du plein écran, sinon la première de la page.
    // Le site garde ses propres contrôles ; ceci rend juste OK, lecture-pause et l'avance rapide fiables à la télécommande.
    static final String VIDEO_JS = "(a=>{const f=document.fullscreenElement;"
            + "const v=(f&&(f.tagName==='VIDEO'?f:f.querySelector('video')))||document.querySelector('video');"
            + "if(!v)return false;if(a==='toggle'){if(v.paused)v.play();else v.pause();}"
            + "else v.currentTime=Math.max(0,v.currentTime+a);return true;})(%s)";

    private FrameLayout root;
    private View pointer;
    private float px, py; // centre du pointeur, en px de la WebView
    private boolean longFired;
    private final Runnable longPress = () -> {
        longFired = true;
        setPointer(pointer.getVisibility() != View.VISIBLE);
    };
    private String navJs;
    private long jsBackAt; // dernier Retour confié à la page : un 2e Retour rapproché revient toujours en arrière
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
        if (data == null || !"https".equals(data.getScheme()) || !SiteHosts.allowed(data.getHost())) { // seul Apps la lance, mais on ne charge que du https vers un hôte de la liste blanche
            finish();
            return;
        }
        siteHost = data.getHost().toLowerCase(java.util.Locale.ROOT);
        try (InputStream in = getAssets().open("sitenav.js")) {
            navJs = new Scanner(in, "UTF-8").useDelimiter("\\A").next(); // readAllBytes : Android 13+ seulement
        } catch (IOException e) {
            navJs = null; // sans le script, le pointeur reste disponible
        }
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
        s.setSupportZoom(false); // sinon la WebView zoome sur le champ de recherche et l'écran déborde
        if (siteHost.equals("openflix.pro")) web.setInitialScale(85); // la TV donne 960 px CSS : la barre d'OpenFlix y passe à la ligne
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                return !isSiteHost(req.getUrl().getHost()); // la page principale reste sur le site
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (navJs != null) view.evaluateJavascript(navJs, null);
                String title = view.getTitle();
                if (title != null && title.matches("(?i).*(just a moment|un instant).*")) setPointer(true); // vérification Cloudflare
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
        GradientDrawable dot = new GradientDrawable();
        dot.setShape(GradientDrawable.OVAL);
        dot.setColor(0xE6FFFFFF);
        dot.setStroke(4, 0xFF1A73E8);
        pointer = new View(this);
        pointer.setBackground(dot);
        pointer.setVisibility(View.GONE);
        root.addView(pointer, new FrameLayout.LayoutParams(32, 32));
        setContentView(root);
        web.loadUrl(getIntent().getDataString());
        web.requestFocus();
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        if (adLayer != null) return super.dispatchKeyEvent(e); // pub : touches telles quelles
        if (fullscreen != null) {
            String action = videoAction(e.getKeyCode());
            if (action == null) return super.dispatchKeyEvent(e);
            // ponytail: vidéo dans une iframe d'un autre domaine = introuvable, la touche est alors perdue ; renvoyer la touche au site si ça arrive
            if (e.getAction() == KeyEvent.ACTION_DOWN) web.evaluateJavascript(String.format(VIDEO_JS, action), null);
            return true; // le relâchement est avalé aussi : le site ne reçoit jamais une moitié de touche
        }
        int k = e.getKeyCode();
        if (k == KeyEvent.KEYCODE_DPAD_CENTER) {
            // OK est retenu jusqu'au relâchement : appui long = bascule du pointeur, appui court = toucher ou OK pour la page.
            if (e.getAction() == KeyEvent.ACTION_DOWN) {
                if (e.getRepeatCount() == 0) {
                    longFired = false;
                    web.postDelayed(longPress, LONG_PRESS_MS);
                }
                return true;
            }
            web.removeCallbacks(longPress);
            if (longFired) return true;
            if (pointer.getVisibility() == View.VISIBLE) gesture(0, 0);
            else {
                super.dispatchKeyEvent(KeyEvent.changeAction(e, KeyEvent.ACTION_DOWN));
                super.dispatchKeyEvent(e);
                // Case Cloudflare ou lecteur en iframe sélectionné par sitenav.js : la page n'y peut rien, on y tape pour de vrai.
                web.evaluateJavascript("window.__jarvisNav && __jarvisNav.tap ? __jarvisNav.tap() : null", this::tap);
            }
            return true;
        }
        if (pointer.getVisibility() == View.VISIBLE && k >= KeyEvent.KEYCODE_DPAD_UP && k <= KeyEvent.KEYCODE_DPAD_RIGHT) {
            if (e.getAction() == KeyEvent.ACTION_DOWN) movePointer(k, e.getRepeatCount());
            return true;
        }
        return super.dispatchKeyEvent(e);
    }

    private void setPointer(boolean on) {
        if (on == (pointer.getVisibility() == View.VISIBLE)) return;
        if (on && px == 0 && py == 0) {
            px = web.getWidth() / 2f;
            py = web.getHeight() / 2f;
        }
        pointer.setVisibility(on ? View.VISIBLE : View.GONE);
        placePointer();
        Toast.makeText(this, on ? "Pointeur : flèches pour bouger, OK pour cliquer, appui long sur OK pour quitter"
                : "Navigation par éléments", Toast.LENGTH_SHORT).show();
    }

    private void movePointer(int k, int repeat) {
        float step = STEP + Math.min(repeat, 10) * 12;
        float dx = k == KeyEvent.KEYCODE_DPAD_LEFT ? -step : k == KeyEvent.KEYCODE_DPAD_RIGHT ? step : 0;
        float dy = k == KeyEvent.KEYCODE_DPAD_UP ? -step : k == KeyEvent.KEYCODE_DPAD_DOWN ? step : 0;
        float x = px + dx, y = py + dy;
        float w = web.getWidth() - 1, h = web.getHeight() - 1;
        px = Math.max(0, Math.min(w, x));
        py = Math.max(0, Math.min(h, y));
        placePointer();
        // Au bord : glisser du doigt plutôt que scrollBy, pour défiler aussi les listes internes et les iframes.
        if (x != px || y != py) gesture(Math.signum(x - px) * SCROLL, Math.signum(y - py) * SCROLL);
    }

    private void placePointer() {
        pointer.setTranslationX(px - 16);
        pointer.setTranslationY(py - 16);
    }

    /** Toucher synthétique au pointeur : (0, 0) = clic, sinon glissé qui fait défiler le contenu de (dx, dy). */
    private void gesture(float dx, float dy) {
        long t = SystemClock.uptimeMillis();
        float x = px - dx, y = py - dy;
        touch(t, t, MotionEvent.ACTION_DOWN, px, py);
        if (dx != 0 || dy != 0) {
            touch(t, t + 100, MotionEvent.ACTION_MOVE, x, y);
            touch(t, t + 400, MotionEvent.ACTION_MOVE, x, y); // immobile avant de lever : pas de lancer (fling)
        }
        touch(t, t + (dx != 0 || dy != 0 ? 450 : 50), MotionEvent.ACTION_UP, x, y);
    }

    private void tap(String json) { // "[fx,fy]" en fraction de la WebView, ou "null"
        if (json == null || adLayer != null || fullscreen != null) return; // une pub a pu s'ouvrir entre la touche et la réponse
        String[] p = json.replaceAll("[\\[\\] ]", "").split(",");
        if (p.length != 2) return;
        float fx, fy;
        try {
            fx = Float.parseFloat(p[0]);
            fy = Float.parseFloat(p[1]);
        } catch (NumberFormatException ex) {
            return;
        }
        if (!(fx >= 0 && fx <= 1 && fy >= 0 && fy <= 1)) return; // la page ne fait toucher que dans sa propre vue
        long t = SystemClock.uptimeMillis();
        touch(t, t, MotionEvent.ACTION_DOWN, fx * web.getWidth(), fy * web.getHeight());
        touch(t, t + 50, MotionEvent.ACTION_UP, fx * web.getWidth(), fy * web.getHeight());
    }

    private void touch(long down, long at, int action, float x, float y) {
        MotionEvent m = MotionEvent.obtain(down, at, action, Math.max(0, Math.min(web.getWidth() - 1, x)), Math.max(0, Math.min(web.getHeight() - 1, y)), 0);
        m.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        web.dispatchTouchEvent(m);
        m.recycle();
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
        return SiteHosts.within(siteHost, host);
    }

    /** Action du lecteur pour une touche, ou null si la touche reste au site. */
    static String videoAction(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
            case KeyEvent.KEYCODE_MEDIA_PLAY:
            case KeyEvent.KEYCODE_MEDIA_PAUSE:
                return "'toggle'";
            case KeyEvent.KEYCODE_DPAD_LEFT:
            case KeyEvent.KEYCODE_MEDIA_REWIND:
                return "-10";
            case KeyEvent.KEYCODE_DPAD_RIGHT:
            case KeyEvent.KEYCODE_MEDIA_FAST_FORWARD:
                return "10";
            default:
                return null;
        }
    }

    @Override
    public void onBackPressed() {
        if (adLayer != null) closeAd();
        else if (pointer.getVisibility() == View.VISIBLE) setPointer(false);
        else if (fullscreen != null) web.getWebChromeClient().onHideCustomView();
        else if (SystemClock.uptimeMillis() - jsBackAt < 800) nativeBack(); // la page ne peut pas bloquer Retour, même figée
        else {
            jsBackAt = SystemClock.uptimeMillis();
            web.evaluateJavascript("window.__jarvisNav && __jarvisNav.back ? __jarvisNav.back() : false", v -> {
                if (!"true".equals(v)) nativeBack(); // sinon : popup fermée ou sortie des contrôles du lecteur
            });
        }
    }

    private void nativeBack() {
        if (web.canGoBack()) web.goBack();
        else finish();
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy(); // null si onCreate a refusé l'adresse
        super.onDestroy();
    }
}

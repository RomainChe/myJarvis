package fr.jarvis.tv;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Ouvre l'accueil JARVIS au démarrage de la TV. Android 10+ bloque les lancements d'activité
 * en arrière-plan, sauf pour une appli qui a SYSTEM_ALERT_WINDOW (accordée une fois par adb).
 */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        context.startActivity(new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
    }
}

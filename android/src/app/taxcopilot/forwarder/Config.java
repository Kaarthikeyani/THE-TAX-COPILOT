package app.taxcopilot.forwarder;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;

/** Where to send messages (address + private key) and the last delivery result. Stored privately on the phone. */
final class Config {
    private static final String FILE = "tcp_config";

    static SharedPreferences prefs(Context c) {
        return c.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    static String url(Context c) { return prefs(c).getString("url", ""); }
    static String key(Context c) { return prefs(c).getString("key", ""); }
    static boolean ready(Context c) { return url(c).startsWith("http") && key(c).startsWith("tcp_"); }

    static void save(Context c, String url, String key) {
        prefs(c).edit().putString("url", url.trim()).putString("key", key.trim()).apply();
    }

    static void result(Context c, boolean ok, String text) {
        SharedPreferences.Editor e = prefs(c).edit().putString("last_text", text).putLong("last_time", System.currentTimeMillis());
        if (ok) e.putLong("last_ok", System.currentTimeMillis());
        e.apply();
    }

    /** Accepts the "setup code" copied from the web app (TCP1:<base64 of "url\nkey">) or two plain lines "url" and "key". */
    static String[] parseSetup(String raw) {
        if (raw == null) return null;
        String t = raw.trim();
        try {
            if (t.startsWith("TCP1:")) t = new String(Base64.decode(t.substring(5).trim(), Base64.DEFAULT), "UTF-8");
        } catch (Exception e) {
            return null;
        }
        String[] parts = t.split("\\s+");
        if (parts.length >= 2 && parts[0].startsWith("http") && parts[1].startsWith("tcp_")) return new String[]{parts[0], parts[1]};
        return null;
    }
}

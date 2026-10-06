package app.taxcopilot.forwarder;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Messages waiting to be delivered. Survives restarts, so nothing is lost while the server or network is unreachable. */
final class Outbox {
    private static final int MAX = 1000;
    private static final Object LOCK = new Object();

    static void add(Context c, String sender, String text, long millis) {
        synchronized (LOCK) {
            try {
                JSONArray a = load(c);
                JSONObject o = new JSONObject();
                o.put("text", text);
                o.put("sender", sender);
                o.put("received_at", iso(millis));
                o.put("id", sender + "|" + millis + "|" + Integer.toHexString(text.hashCode()));
                a.put(o);
                if (a.length() > MAX) {  // drop the oldest
                    JSONArray b = new JSONArray();
                    for (int i = a.length() - MAX; i < a.length(); i++) b.put(a.get(i));
                    a = b;
                }
                store(c, a);
            } catch (JSONException ignored) {
            }
        }
    }

    static JSONArray peek(Context c, int n) {
        synchronized (LOCK) {
            JSONArray a = load(c), out = new JSONArray();
            for (int i = 0; i < Math.min(n, a.length()); i++) {
                try { out.put(a.get(i)); } catch (JSONException ignored) { }
            }
            return out;
        }
    }

    static void drop(Context c, int n) {
        synchronized (LOCK) {
            JSONArray a = load(c), b = new JSONArray();
            for (int i = n; i < a.length(); i++) {
                try { b.put(a.get(i)); } catch (JSONException ignored) { }
            }
            store(c, b);
        }
    }

    static int size(Context c) {
        synchronized (LOCK) { return load(c).length(); }
    }

    private static JSONArray load(Context c) {
        try { return new JSONArray(Config.prefs(c).getString("outbox", "[]")); } catch (JSONException e) { return new JSONArray(); }
    }

    private static void store(Context c, JSONArray a) {
        Config.prefs(c).edit().putString("outbox", a.toString()).apply();
    }

    static String iso(long millis) {
        java.text.SimpleDateFormat f = new java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", java.util.Locale.US);
        f.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));
        return f.format(new java.util.Date(millis));
    }
}

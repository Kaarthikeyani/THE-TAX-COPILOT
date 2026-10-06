package app.taxcopilot.forwarder;

import android.content.Context;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import org.json.JSONArray;
import org.json.JSONObject;

/** Delivers the outbox to the server. Anything that cannot be delivered stays queued and is retried with backoff. */
final class Sender {
    static final int BATCH = 50;
    private static final Object FLUSH = new Object();

    /** Result of one POST: code (HTTP status, or -1 for a network error) and the server's one-line summary. */
    static final class Reply {
        int code;
        String summary = "";
        int saved, duplicate, ignored, error;
    }

    static Reply post(Context c, JSONArray messages) {
        Reply r = new Reply();
        HttpURLConnection h = null;
        try {
            h = (HttpURLConnection) new URL(Config.url(c)).openConnection();
            h.setConnectTimeout(15000);
            h.setReadTimeout(30000);
            h.setRequestMethod("POST");
            h.setDoOutput(true);
            h.setRequestProperty("Content-Type", "application/json");
            h.setRequestProperty("X-API-Key", Config.key(c));
            byte[] body = new JSONObject().put("messages", messages).toString().getBytes("UTF-8");
            try (OutputStream o = h.getOutputStream()) { o.write(body); }
            r.code = h.getResponseCode();
            InputStream in = r.code >= 400 ? h.getErrorStream() : h.getInputStream();
            String text = in == null ? "" : read(in);
            if (r.code == 200) {
                JSONObject j = new JSONObject(text);
                r.saved = j.optInt("saved");
                r.duplicate = j.optInt("duplicate");
                r.ignored = j.optInt("ignored");
                r.error = j.optInt("error");
                r.summary = r.saved + " saved, " + r.duplicate + " already there, " + r.ignored + " skipped";
            } else {
                r.summary = "Server said " + r.code + (r.code == 401 ? " (the key is wrong or was replaced)" : "");
            }
        } catch (Exception e) {
            r.code = -1;
            r.summary = "Could not reach the server (" + e.getClass().getSimpleName() + ")";
        } finally {
            if (h != null) h.disconnect();
        }
        return r;
    }

    private static String read(InputStream in) throws Exception {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
        return b.toString("UTF-8");
    }

    /** Send everything queued. Returns true when the queue is empty. Must run off the main thread. */
    static boolean flush(Context c) {
        synchronized (FLUSH) {
            if (!Config.ready(c)) return Outbox.size(c) == 0;
            while (true) {
                JSONArray batch = Outbox.peek(c, BATCH);
                if (batch.length() == 0) return true;
                Reply r = post(c, batch);
                if (r.code == 200 || r.code == 400 || r.code == 413) {  // the server has dealt with it; 400/413 would never succeed on retry
                    Outbox.drop(c, batch.length());
                    Config.result(c, r.code == 200, r.summary);
                } else {  // network down, 401, 429, 5xx: keep the messages and try again later
                    Config.result(c, false, r.summary);
                    return false;
                }
            }
        }
    }

    static void scheduleRetry(Context c) {
        JobScheduler js = (JobScheduler) c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        JobInfo job = new JobInfo.Builder(1, new ComponentName(c, RetryService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setBackoffCriteria(30000, JobInfo.BACKOFF_POLICY_EXPONENTIAL)
                .setPersisted(true)
                .build();
        js.schedule(job);
    }
}

package app.taxcopilot.forwarder;

import android.Manifest;
import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;

/** One screen: paste the setup code from the web app, allow SMS access, check it works, optionally import recent messages. */
public class MainActivity extends Activity {
    private static final int REQ_SMS = 7;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private EditText urlBox, keyBox;
    private TextView status, detail;
    private boolean importAfterGrant = false;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        int pad = dp(18);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);
        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);

        TextView h = text("Tax Co-Pilot SMS", 24, true);
        root.addView(h);
        root.addView(text("Sends your bank transaction messages to your Tax Co-Pilot account, the moment they arrive. "
                + "Personal chats and OTP codes never leave this phone.", 14, false));

        status = text("", 16, true);
        status.setPadding(0, dp(14), 0, dp(4));
        root.addView(status);
        detail = text("", 13, false);
        root.addView(detail);

        root.addView(label("1. Connect to your account"));
        root.addView(text("In the web app open Connect phone and press \"Copy setup code\", then:", 13, false));
        Button paste = button("Paste setup code");
        paste.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { pasteCode(); } });
        root.addView(paste);
        root.addView(text("or type them in:", 13, false));
        urlBox = input("Server address, e.g. http://192.168.1.20:8811/sms/webhook", InputType.TYPE_TEXT_VARIATION_URI);
        keyBox = input("Private key (starts with tcp_)", InputType.TYPE_CLASS_TEXT);
        root.addView(urlBox);
        root.addView(keyBox);
        Button save = button("Save");
        save.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
            Config.save(MainActivity.this, urlBox.getText().toString(), keyBox.getText().toString());
            refresh(); }});
        root.addView(save);

        root.addView(label("2. Allow SMS access"));
        Button perm = button("Allow SMS access");
        perm.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { askPermission(false); } });
        root.addView(perm);

        root.addView(label("3. Check it works"));
        Button test = button("Send a test message");
        test.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { sendTest(); } });
        root.addView(test);

        root.addView(label("4. Optional: import the last 30 days"));
        root.addView(text("Sends the bank messages already in your inbox so the app has real data to work with. Duplicates are ignored.", 13, false));
        Button imp = button("Import last 30 days");
        imp.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { askPermission(true); } });
        root.addView(imp);

        root.addView(text("If messages arrive late, switch off battery optimisation for this app in Android settings.", 12, false));
        urlBox.setText(Config.url(this));
        keyBox.setText(Config.key(this));
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
    }

    private void refresh() {
        boolean cfg = Config.ready(this);
        boolean perm = checkSelfPermission(Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED;
        int queued = Outbox.size(this);
        long ok = Config.prefs(this).getLong("last_ok", 0);
        if (cfg && perm) {
            status.setText(queued == 0 ? "Ready. Waiting for bank messages." : queued + " message(s) waiting to be sent");
            status.setTextColor(Color.rgb(11, 122, 117));
        } else {
            status.setText(!cfg ? "Not connected yet" : "SMS access not allowed yet");
            status.setTextColor(Color.rgb(199, 119, 0));
        }
        String last = Config.prefs(this).getString("last_text", "");
        detail.setText((last.isEmpty() ? "" : "Last result: " + last + "\n")
                + (ok == 0 ? "" : "Last delivered: " + java.text.DateFormat.getDateTimeInstance().format(new java.util.Date(ok))));
    }

    private void pasteCode() {
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        ClipData d = cm == null ? null : cm.getPrimaryClip();
        String raw = d != null && d.getItemCount() > 0 && d.getItemAt(0).getText() != null ? d.getItemAt(0).getText().toString() : "";
        String[] p = Config.parseSetup(raw);
        if (p == null) {
            detail.setText("The clipboard does not hold a setup code. Copy it again from Connect phone in the web app.");
            return;
        }
        Config.save(this, p[0], p[1]);
        urlBox.setText(p[0]);
        keyBox.setText(p[1]);
        refresh();
        detail.setText("Setup code saved. Next: allow SMS access.");
    }

    private void askPermission(boolean thenImport) {
        importAfterGrant = thenImport;
        if (checkSelfPermission(Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED
                && checkSelfPermission(Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED) {
            if (thenImport) importRecent();
            else refresh();
            return;
        }
        requestPermissions(new String[]{Manifest.permission.RECEIVE_SMS, Manifest.permission.READ_SMS}, REQ_SMS);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
        boolean all = res.length > 0;
        for (int r : res) all &= r == PackageManager.PERMISSION_GRANTED;
        refresh();
        if (all && importAfterGrant) importRecent();
        else if (!all) detail.setText("Without SMS access nothing can be forwarded. You can allow it in Android settings > Apps > Tax Co-Pilot SMS > Permissions.");
    }

    private void sendTest() {
        if (!Config.ready(this)) { detail.setText("Connect first (step 1)."); return; }
        detail.setText("Sending…");
        final Context c = getApplicationContext();
        new Thread(new Runnable() { public void run() {
            try {
                JSONArray a = new JSONArray();
                long now = System.currentTimeMillis();
                a.put(new JSONObject().put("text", "Rs.99.00 debited from A/c XX0000 to VPA phone-test@ybl (UPI Ref " + (now % 1000000) + "). Bal Rs 50,000.00")
                        .put("sender", "AX-TESTBK").put("received_at", Outbox.iso(now)).put("id", "phonetest-" + now));
                final Sender.Reply r = Sender.post(c, a);
                Config.result(c, r.code == 200, r.summary);
                ui.post(new Runnable() { public void run() { refresh(); detail.setText((r.code == 200 ? "Delivered: " : "Failed: ") + r.summary
                        + (r.code == 200 ? "\nLook in the web app: it should appear in Activity right now." : "")); }});
            } catch (Exception e) { /* cannot happen: fixed JSON */ }
        }}).start();
    }

    private void importRecent() {
        if (!Config.ready(this)) { detail.setText("Connect first (step 1)."); return; }
        detail.setText("Reading your inbox…");
        final Context c = getApplicationContext();
        new Thread(new Runnable() { public void run() {
            int found = 0;
            long since = System.currentTimeMillis() - 30L * 24 * 3600 * 1000;
            try (Cursor cur = c.getContentResolver().query(Uri.parse("content://sms/inbox"), new String[]{"address", "body", "date", "date_sent"},
                    "date >= ?", new String[]{String.valueOf(since)}, "date ASC")) {
                while (cur != null && cur.moveToNext()) {
                    String sender = cur.getString(0), body = cur.getString(1);
                    // use the time the bank sent it (date_sent), the same value the live receiver reports, so a message that was already
                    // forwarded live is recognised as a duplicate instead of being saved twice
                    long sent = cur.getLong(3), when = sent > 0 ? sent : cur.getLong(2);
                    if (SmsFilter.isBankTransaction(sender, body)) { Outbox.add(c, sender, body, when); found++; }
                }
            } catch (SecurityException e) {
                final String m = "No permission to read messages. Allow SMS access first.";
                ui.post(new Runnable() { public void run() { detail.setText(m); }});
                return;
            }
            final int n = found;
            boolean done = Sender.flush(c);
            if (!done) Sender.scheduleRetry(c);
            ui.post(new Runnable() { public void run() { refresh(); detail.setText("Found " + n + " bank message(s) in the last 30 days. " + Config.prefs(c).getString("last_text", "")); }});
        }}).start();
    }

    // ---- tiny view helpers (no layout XML, so the app builds with the bare SDK tools) ----
    private int dp(int v) { return (int) (v * getResources().getDisplayMetrics().density + 0.5f); }

    private TextView text(String s, int sp, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(Color.rgb(16, 34, 47));
        if (bold) t.setTypeface(null, android.graphics.Typeface.BOLD);
        t.setPadding(0, dp(4), 0, dp(4));
        return t;
    }

    private TextView label(String s) {
        TextView t = text(s, 17, true);
        t.setPadding(0, dp(22), 0, dp(4));
        return t;
    }

    private Button button(String s) {
        Button b = new Button(this);
        b.setText(s);
        b.setAllCaps(false);
        b.setGravity(Gravity.CENTER);
        return b;
    }

    private EditText input(String hint, int type) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setSingleLine(true);
        e.setInputType(type);
        return e;
    }
}

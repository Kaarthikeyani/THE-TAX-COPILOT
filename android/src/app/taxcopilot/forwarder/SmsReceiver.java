package app.taxcopilot.forwarder;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.provider.Telephony;
import android.telephony.SmsMessage;
import java.util.LinkedHashMap;
import java.util.Map;

/** Runs when an SMS arrives. Bank messages are queued and sent at once; everything else is ignored and never stored. */
public class SmsReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(final Context context, Intent intent) {
        if (!Telephony.Sms.Intents.SMS_RECEIVED_ACTION.equals(intent.getAction())) return;
        SmsMessage[] parts = Telephony.Sms.Intents.getMessagesFromIntent(intent);
        if (parts == null || parts.length == 0) return;

        // a long message arrives in several parts from the same sender: join them back together
        Map<String, StringBuilder> bodies = new LinkedHashMap<>();
        long when = parts[0].getTimestampMillis();
        for (SmsMessage m : parts) {
            if (m == null || m.getOriginatingAddress() == null) continue;
            StringBuilder sb = bodies.get(m.getOriginatingAddress());
            if (sb == null) bodies.put(m.getOriginatingAddress(), sb = new StringBuilder());
            sb.append(m.getMessageBody() == null ? "" : m.getMessageBody());
        }
        boolean queued = false;
        for (Map.Entry<String, StringBuilder> e : bodies.entrySet()) {
            String text = e.getValue().toString();
            if (SmsFilter.isBankTransaction(e.getKey(), text)) {
                Outbox.add(context, e.getKey(), text, when);
                queued = true;
            }
        }
        if (!queued || !Config.ready(context)) return;

        final PendingResult pending = goAsync();
        final Context app = context.getApplicationContext();
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    if (!Sender.flush(app)) Sender.scheduleRetry(app);
                } finally {
                    pending.finish();
                }
            }
        }).start();
    }
}

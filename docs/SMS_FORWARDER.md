# Getting real SMS into the app (live)

**A web page cannot read your phone's SMS inbox**, and iOS gives no app access to SMS at all. So this project includes a small **Android app**
(`android/`, about 20 KB, plain Java, no dependencies) that forwards your **bank transaction** messages to your account. Everything on the server
side is built and tested too: accounts, a private key per user, the webhook, de-duplication and live push to the open browser tab.

What was actually tested (Android 15 emulator, x86_64, real SMS delivered with `adb emu sms send`, against a running server):
a bank debit and a bank credit arrived in about 3 seconds; a message from a personal number and an OTP did **not** leave the phone;
two messages sent while the server was stopped were delivered by themselves about 13 seconds after it came back; "Import last 30 days"
found the 7 bank messages and the server recognised all 7 as already saved. **Not tested:** a physical phone, other Android versions or vendors
(some phone makers kill background apps aggressively; switch off battery optimisation for this app), a real bank's message formats beyond the samples.

## Steps

1. Run the app (`python run.py`) and sign in with your phone number.
2. Build the phone app once (needs the Android SDK and a JDK; no Android Studio project, no Gradle): `cd android` then `python build.py`. It writes `android/build/tax-copilot-sms.apk`.
3. Open **Connect phone** in the web app. If the phone is on the same Wi-Fi, the server must listen on your computer's address. The page shows the exact command, for example:

   ```
   $env:COPILOT_HOST="0.0.0.0"; $env:COPILOT_ALLOWED_HOSTS="192.168.1.20"; $env:COPILOT_PUBLIC_URL="http://192.168.1.20:8811"; python run.py
   ```

   This is plain HTTP: use it on a network you trust, or put HTTPS in front (a tunnel or reverse proxy) and set `COPILOT_PUBLIC_URL` to the https address.
4. On the phone, open `http://<your computer>:8811`, sign in, open Connect phone and press **Download phone app (APK)**. Open the file (allow "install unknown apps" for the browser when asked).
5. Back on the computer's Connect page press **Copy setup code**, get it onto the phone (message it to yourself, or type the address and key by hand), open **Tax Co-Pilot SMS**, press **Paste setup code**, **Allow SMS access**, then **Send a test message**. It should appear in Activity within a second.
6. Optional: **Import last 30 days** sends the bank messages already in your inbox, so the app has real data to measure accuracy on.

The app filters on the phone: only messages from a bank-style sender ID (like `AX-HDFCBK`) that mention an amount and a debit/credit word are sent. Personal chats and OTPs are never sent.
The signing key (`android/debug.keystore`) is created on first build and kept out of git; keep it if you want later builds to install over the earlier one.

Prefer a different forwarder (Tasker, MacroDroid, an open-source SMS forwarder)? Use the address, header and key from Connect phone with the contract below.

## The contract

```
POST http://<server>:8811/sms/webhook
X-API-Key: tcp_...            (your key from Connect phone)
Content-Type: application/json

{"messages":[{"text":"Rs.450.00 debited from A/c XX1234 on 05-10-26 to VPA swiggy@ybl (UPI Ref 1). Bal Rs 9,000",
              "sender":"AX-HDFCBK", "received_at":"2026-10-05T10:15:00Z", "id":"optional-unique-id"}]}
```

* A single object (`{"text": ...}`) or a bare list also works. Up to 200 messages per request.
* Field aliases accepted: `text|body|message|sms`, `sender|from|address`, `received_at|timestamp|date|time` (ISO-8601 or epoch seconds/ms), `id|message_id|uid`.
* `sender` must look like a bank/alert ID (`AX-HDFCBK`, `HDFCBK`, ...). A personal phone number is reported as `ignored`.
* If the message has no date inside it, `received_at` is used as the transaction date.
* The key decides which account receives the messages. Two people can forward the identical SMS text and each gets their own entry.

Response (HTTP 200) has one entry per message, so one bad message never rejects the batch:

```
{"received":3,"saved":1,"duplicate":0,"ignored":2,"error":0,
 "results":[{"index":0,"status":"saved","id":42,"category":"food_dining","type":"debit"},
            {"index":1,"status":"ignored","code":"...","detail":"..."}, ...]}
```

`status` is `saved`, `duplicate` (same sender + id/time + text seen before; safe to retry), `ignored` (OTP, failed payment, promo, non-bank sender, unparsable; the `code` says why) or `error`.
Whole-request problems return 400 / 401 / 413 / 429 with `{"error","detail"}`. Rate limit: 60 requests/minute (`COPILOT_WEBHOOK_RATE`); 10 wrong keys in 5 minutes lock that address out of the webhook for 5 minutes (the signed-in app is not affected).
Raw message text is never written to logs.

## Test it from your computer

Copy your key from Connect phone, then (PowerShell):

```
$body = '{"messages":[{"text":"Rs.450.00 debited from A/c XX1234 on 05-10-26 to VPA swiggy@ybl (UPI Ref 1). Bal Rs 9,000","sender":"AX-HDFCBK"}]}'
Invoke-RestMethod -Method Post -Uri http://localhost:8811/sms/webhook -Headers @{"X-API-Key"="tcp_yourkey"} -ContentType "application/json" -Body $body
```

Send it twice: the second answer is `duplicate`. With the app open you see the first one appear without reloading.

## Lost key or leaked key

Connect phone, **Make a new key**. The old one stops working at once; paste the new one into the forwarder app.

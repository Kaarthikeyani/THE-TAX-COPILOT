package app.taxcopilot.forwarder;

import java.util.regex.Pattern;

/**
 * Decides on the PHONE which messages are worth sending. Personal chats, OTPs and anything that does not look like a bank
 * transaction never leave the device. (The server filters again, but this is the privacy boundary.)
 */
final class SmsFilter {
    // bank / alert sender ids look like AX-HDFCBK, HDFCBK, VM-SBIINB-S; a person's number starts with + or a digit
    private static final Pattern SENDER = Pattern.compile("^(?:[A-Za-z]{2}-)?[A-Za-z][A-Za-z0-9]{2,9}(?:-[A-Za-z])?$");
    private static final Pattern MONEY = Pattern.compile("(?i)(?:rs\\.?|inr|₹)\\s*[0-9][0-9,]*");
    private static final Pattern MOVED = Pattern.compile(
            "(?i)\\b(debited|credited|spent|withdrawn|received|deposited|transferred|purchase|paid|sent|debit|credit)\\b");
    private static final Pattern OTP = Pattern.compile("(?i)\\botp\\b|one[- ]time password|do not share|never share");

    static boolean isBankTransaction(String sender, String body) {
        if (sender == null || body == null) return false;
        if (!SENDER.matcher(sender.trim()).matches()) return false;
        if (OTP.matcher(body).find()) return false;
        return MONEY.matcher(body).find() && MOVED.matcher(body).find();
    }
}

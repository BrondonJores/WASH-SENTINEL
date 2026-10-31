package cm.wash.mesh.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf

/**
 * Passerelle SMS villageoise (pattern SMSSync, Phase 2) : chaque SMS
 * commençant par le mot-clé WASH/EAU est mis en file vers le serveur
 * (POST /api/v1/mesh/sms dès qu'une data intermittente existe).
 */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != "android.provider.Telephony.SMS_RECEIVED") return
        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        for (msg in messages) {
            val body = msg.messageBody ?: continue
            val upper = body.trim().uppercase()
            if (!upper.startsWith("WASH") && !upper.startsWith("EAU")) continue
            val req = OneTimeWorkRequestBuilder<SmsGatewayWorker>()
                .setInputData(
                    workDataOf(
                        "from" to (msg.originatingAddress ?: ""),
                        "body" to body,
                        "sent_at" to msg.timestampMillis,
                    ),
                )
                .build()
            WorkManager.getInstance(context).enqueue(req)
        }
    }
}

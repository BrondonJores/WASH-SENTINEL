package cm.wash.mesh.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import android.util.Log
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import cm.wash.mesh.BuildConfig
import java.time.LocalDate

/**
 * Passerelle SMS villageoise (pattern SMSSync) : chaque SMS WASH/EAU valide
 * est auto-transféré au serveur (POST /api/v1/mesh/sms dès qu'une data existe).
 * Filtrage précoce aligné backend ([SmsPolicy]) : grammaire, allowlist exacte,
 * quota journalier par expéditeur. Les segments d'un SMS long sont réassemblés.
 */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != "android.provider.Telephony.SMS_RECEIVED") return
        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val bodies = linkedMapOf<String, StringBuilder>()
        val stamps = mutableMapOf<String, Long>()
        for (msg in messages) {
            val from = msg.originatingAddress ?: continue
            bodies.getOrPut(from) { StringBuilder() }.append(msg.messageBody ?: "")
            val prev = stamps[from]
            val ts = msg.timestampMillis
            stamps[from] = if (prev == null) ts else minOf(prev, ts)
        }
        if (bodies.isEmpty()) return
        val today = LocalDate.now().toString()
        for ((from, sb) in bodies) {
            val body = sb.toString()
            val parsed = SmsPolicy.parse(body)
            if (!parsed.ok) {
                Log.i(TAG, "SMS ignoré de $from : ${parsed.error}")
                continue
            }
            if (!SmsPolicy.isAllowlisted(from, BuildConfig.SMS_ALLOWLIST)) {
                Log.w(TAG, "SMS rejeté : $from hors allowlist")
                continue
            }
            if (SmsPolicy.quotaExceeded(SmsQuotaStore.countFor(context, from, today), BuildConfig.SMS_QUOTA)) {
                Log.w(TAG, "SMS rejeté : quota journalier dépassé pour $from")
                continue
            }
            SmsQuotaStore.record(context, from, today)
            Log.i(TAG, "SMS ${parsed.code} ${parsed.type} de $from → file de transfert")
            val req = OneTimeWorkRequestBuilder<SmsGatewayWorker>()
                .setInputData(
                    workDataOf(
                        "from" to from,
                        "body" to body,
                        "sent_at" to (stamps[from] ?: 0L),
                    ),
                )
                .build()
            WorkManager.getInstance(context).enqueue(req)
        }
    }

    companion object {
        private const val TAG = "WashSms"
    }
}

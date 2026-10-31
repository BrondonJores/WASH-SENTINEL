package cm.wash.mesh.sms

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import cm.wash.mesh.BuildConfig
import cm.wash.mesh.net.Api
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant

/**
 * Auto-transfert des SMS filtrés par [SmsReceiver] vers POST /api/v1/mesh/sms.
 * Rejets définitifs (403 secret/allowlist, 422 format) = succès sans retry ;
 * 429 et 5xx = retry ; le serveur reste l'arbitre final (dédup 24 h).
 */
class SmsGatewayWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        if (BuildConfig.SMS_SECRET.isEmpty()) {
            Log.w(TAG, "transfert impossible : MESH_SMS_SECRET vide")
            return Result.failure()
        }
        val from = inputData.getString("from") ?: return Result.failure()
        val body = inputData.getString("body") ?: return Result.failure()
        val sentAt = runCatching {
            Instant.ofEpochMilli(inputData.getLong("sent_at", 0)).toString()
        }.getOrNull()
        return try {
            val res = withContext(Dispatchers.IO) {
                Api.smsPost(BuildConfig.LARAVEL_API_URL, BuildConfig.SMS_SECRET, from, body, sentAt)
            }
            Log.i(TAG, "SMS de $from transféré, ticket ${res.optString("ticket", "?")}")
            Result.success()
        } catch (e: Api.ApiError) {
            when (e.code) {
                422, 403 -> {
                    Log.w(TAG, "SMS de $from rejeté définitivement (${e.code})")
                    Result.success() // format/secret/allowlist : inutile de réessayer
                }
                429 -> Result.retry()
                in 500..599 -> Result.retry()
                else -> Result.failure()
            }
        } catch (e: Exception) {
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "WashSms"
    }
}

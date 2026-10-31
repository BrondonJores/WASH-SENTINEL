package cm.wash.mesh.sms

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import cm.wash.mesh.BuildConfig
import cm.wash.mesh.net.Api
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant

class SmsGatewayWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        if (BuildConfig.SMS_SECRET.isEmpty()) return Result.failure()
        val from = inputData.getString("from") ?: return Result.failure()
        val body = inputData.getString("body") ?: return Result.failure()
        val sentAt = runCatching {
            Instant.ofEpochMilli(inputData.getLong("sent_at", 0)).toString()
        }.getOrNull()
        return try {
            withContext(Dispatchers.IO) {
                Api.smsPost(BuildConfig.LARAVEL_API_URL, BuildConfig.SMS_SECRET, from, body, sentAt)
            }
            Result.success()
        } catch (e: Api.ApiError) {
            when (e.code) {
                422, 403 -> Result.success() // format/secret : inutile de réessayer
                429 -> Result.retry()
                in 500..599 -> Result.retry()
                else -> Result.failure()
            }
        } catch (e: Exception) {
            Result.retry()
        }
    }
}

package cm.wash.mesh.mesh

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import cm.wash.mesh.data.MeshDatabase
import cm.wash.mesh.net.Api
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Upload différé : dès qu'une connectivité existe (contrainte CONNECTED),
 * pousse l'outbox vers Laravel et purge les bundles acceptés/doublons.
 * Idempotent côté serveur : un retry ne crée jamais de doublon.
 */
class UploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val apiUrl = inputData.getString("api_url") ?: return Result.failure()
        val meshKey = inputData.getString("mesh_key") ?: ""
        val dao = MeshDatabase.get(applicationContext).dao()
        val pending = dao.pending()
        if (pending.isEmpty()) return Result.success()
        return try {
            val bundles = pending.map { JSONObject(it.json) }
            val res = withContext(Dispatchers.IO) { Api.laravelUpload(apiUrl, bundles, meshKey) }
            if (res.doneIds.isNotEmpty()) dao.markDone(res.doneIds)
            Result.success()
        } catch (e: Api.ApiError) {
            if (e.code in 500..599) Result.retry() else Result.failure()
        } catch (e: Exception) {
            Result.retry()
        }
    }
}

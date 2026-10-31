package cm.wash.mesh.relay

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import cm.wash.mesh.ble.BleMeshService
import cm.wash.mesh.mesh.MeshRelayService

/** Filet de sécurité : retente le démarrage du relai quand le direct a échoué. */
class RelayRestartWorker(context: Context, params: WorkerParameters) :
    CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        if (!RelayPrefs.isRelayEnabled(applicationContext)) return Result.success()
        return try {
            MeshRelayService.start(applicationContext)
            if (BleMeshService.isSupported(applicationContext)) {
                BleMeshService.start(applicationContext)
            }
            Result.success()
        } catch (e: Exception) {
            if (runAttemptCount >= 5) Result.failure() else Result.retry()
        }
    }
}

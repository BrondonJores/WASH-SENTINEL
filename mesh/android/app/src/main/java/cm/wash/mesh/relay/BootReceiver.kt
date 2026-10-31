package cm.wash.mesh.relay

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import cm.wash.mesh.ble.BleMeshService
import cm.wash.mesh.mesh.MeshRelayService
import java.util.concurrent.TimeUnit

/**
 * Relance le relai au boot / après mise à jour si l'utilisateur l'avait activé.
 * Secours : si le démarrage foreground est refusé depuis le fond (API 31+),
 * un Worker WorkManager réessaie avec backoff.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            "android.intent.action.QUICKBOOT_POWERON",
            -> Unit
            else -> return
        }
        if (!RelayPrefs.isRelayEnabled(context)) {
            Log.i(TAG, "relai désactivé, pas de redémarrage au boot")
            return
        }
        try {
            MeshRelayService.start(context)
            if (BleMeshService.isSupported(context)) BleMeshService.start(context)
            Log.i(TAG, "relai relancé au boot")
        } catch (e: Exception) {
            Log.w(TAG, "redémarrage direct refusé, bascule WorkManager", e)
            runCatching {
                WorkManager.getInstance(context).enqueue(
                    OneTimeWorkRequestBuilder<RelayRestartWorker>()
                        .setBackoffCriteria(
                            BackoffPolicy.EXPONENTIAL,
                            RestartPolicy.BASE_DELAY_MS,
                            TimeUnit.MILLISECONDS,
                        )
                        .build(),
                )
            }
        }
    }

    companion object {
        private const val TAG = "WashBoot"
    }
}

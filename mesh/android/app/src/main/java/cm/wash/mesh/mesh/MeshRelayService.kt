package cm.wash.mesh.mesh

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.work.BackoffPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import cm.wash.mesh.MeshProtocol
import cm.wash.mesh.R
import cm.wash.mesh.data.BundleEntity
import cm.wash.mesh.data.MeshDatabase
import cm.wash.mesh.relay.RelayPrefs
import cm.wash.mesh.relay.RelayRestartWorker
import cm.wash.mesh.relay.RestartPolicy
import com.google.android.gms.nearby.Nearby
import com.google.android.gms.nearby.connection.AdvertisingOptions
import com.google.android.gms.nearby.connection.ConnectionInfo
import com.google.android.gms.nearby.connection.ConnectionLifecycleCallback
import com.google.android.gms.nearby.connection.ConnectionResolution
import com.google.android.gms.nearby.connection.ConnectionsClient
import com.google.android.gms.nearby.connection.DiscoveredEndpointInfo
import com.google.android.gms.nearby.connection.DiscoveryOptions
import com.google.android.gms.nearby.connection.EndpointDiscoveryCallback
import com.google.android.gms.nearby.connection.Payload
import com.google.android.gms.nearby.connection.PayloadCallback
import com.google.android.gms.nearby.connection.PayloadTransferUpdate
import com.google.android.gms.nearby.connection.Strategy
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.Collections
import java.util.concurrent.TimeUnit

/**
 * Relai ambiant : foreground service permanent qui annonce et découvre
 * les voisins en Nearby P2P_CLUSTER (100 % offline, BT + BLE + WiFi),
 * accepte les connexions et gossip les bundles (Spray-and-Wait binaire).
 *
 * Compromis assumé v1 : acceptation auto sans confirmation manuelle
 * (nécessaire au store-and-forward opportuniste). L'authentification
 * viendra des signatures Ed25519 (Phase 3) ; en attendant, dédup par id
 * + quotas serveur bornent l'abus.
 */
class MeshRelayService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var client: ConnectionsClient
    private lateinit var nodeId: String
    private val requested = Collections.synchronizedSet(mutableSetOf<String>())

    private val payloadCallback = object : PayloadCallback() {
        override fun onPayloadReceived(endpointId: String, payload: Payload) {
            val bytes = payload.asBytes() ?: return
            scope.launch {
                val bundle = runCatching { JSONObject(String(bytes, Charsets.UTF_8)) }.getOrNull()
                    ?: return@launch
                if (!MeshProtocol.requiredFieldsOk(bundle) || !MeshProtocol.verify(bundle)) return@launch
                // J'ajoute mon hop (spray) avant stockage : ce que je relaierai ensuite.
                val fwd = MeshProtocol.forward(bundle, nodeId) ?: return@launch
                store(fwd.give)
                Log.i(TAG, "bundle Nearby reçu et stocké")
            }
        }

        override fun onPayloadTransferUpdate(endpointId: String, update: PayloadTransferUpdate) = Unit
    }

    private val connectionCallback = object : ConnectionLifecycleCallback() {
        override fun onConnectionInitiated(endpointId: String, info: ConnectionInfo) {
            client.acceptConnection(endpointId, payloadCallback)
        }

        override fun onConnectionResult(endpointId: String, resolution: ConnectionResolution) {
            if (resolution.status.isSuccess) {
                Log.i(TAG, "voisin Nearby connecté, envoi outbox")
                scope.launch { sendOutbox(endpointId) }
            } else {
                requested.remove(endpointId)
                Log.i(TAG, "connexion Nearby refusée, voisin suivant")
            }
        }

        override fun onDisconnected(endpointId: String) {
            requested.remove(endpointId)
        }
    }

    private val discoveryCallback = object : EndpointDiscoveryCallback() {
        override fun onEndpointFound(endpointId: String, info: DiscoveredEndpointInfo) {
            if (!requested.add(endpointId)) return
            Log.i(TAG, "voisin Nearby trouvé, connexion…")
            client.requestConnection(nodeId, endpointId, connectionCallback)
                .addOnFailureListener {
                    requested.remove(endpointId)
                    Log.i(TAG, "connexion Nearby impossible, voisin suivant")
                }
        }

        override fun onEndpointLost(endpointId: String) {
            requested.remove(endpointId)
        }
    }

    override fun onCreate() {
        super.onCreate()
        nodeId = RelayPrefs.getOrCreateNodeId(this)
        client = Nearby.getConnectionsClient(this)
        startForegrounded()
        client.startAdvertising(
            nodeId, MeshProtocol.SERVICE_ID, connectionCallback,
            AdvertisingOptions.Builder().setStrategy(Strategy.P2P_CLUSTER).build(),
        )
        client.startDiscovery(
            MeshProtocol.SERVICE_ID, discoveryCallback,
            DiscoveryOptions.Builder().setStrategy(Strategy.P2P_CLUSTER).build(),
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Log.i(TAG, "relai Nearby démarré (nœud $nodeId)")
        return START_STICKY
    }

    /**
     * Balayage dans les récents : relance immédiate si le relai reste activé,
     * sinon WorkManager réessaiera (filet de sécurité après kill système).
     */
    override fun onTaskRemoved(rootIntent: Intent?) {
        super.onTaskRemoved(rootIntent)
        if (!RelayPrefs.isRelayEnabled(this)) return
        try {
            start(this)
        } catch (e: Exception) {
            Log.w(TAG, "relance directe refusée, bascule WorkManager", e)
            runCatching {
                WorkManager.getInstance(this).enqueue(
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

    override fun onDestroy() {
        runCatching { client.stopAllEndpoints() }
        runCatching { client.stopAdvertising() }
        runCatching { client.stopDiscovery() }
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    /** Envoie une copie sprayée de chaque bundle éligible au nouveau contact. */
    private suspend fun sendOutbox(endpointId: String) {
        val dao = MeshDatabase.get(this).dao()
        for (entity in dao.pending()) {
            val bundle = runCatching { JSONObject(entity.json) }.getOrNull() ?: continue
            val fwd = MeshProtocol.forward(bundle, nodeId) ?: continue
            runCatching {
                client.sendPayload(endpointId, Payload.fromBytes(fwd.give.toString().toByteArray(Charsets.UTF_8)))
            }
            // Je garde le reste du budget sur ma copie.
            val kept = JSONObject(entity.json).put("copies_remaining", fwd.keepCopies)
            dao.updateJson(entity.id, kept.toString())
        }
    }

    private suspend fun store(bundle: JSONObject) {
        val dao = MeshDatabase.get(this).dao()
        dao.insert(
            BundleEntity(
                id = bundle.getString("bundle_id"),
                originNode = bundle.getString("origin_node_id"),
                schoolId = bundle.optInt("school_id", 0),
                json = bundle.toString(),
            ),
        )
    }

    private fun startForegrounded() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "Relai WASH", NotificationManager.IMPORTANCE_LOW),
        )
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setContentTitle("Relai WASH actif")
            .setContentText("Relai des signalements de $nodeId")
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(NOTIF_ID, notification)
        }
    }

    companion object {
        private const val TAG = "WashRelay"
        private const val CHANNEL = "wash_mesh_relay"
        private const val NOTIF_ID = 42

        fun start(context: Context) {
            RelayPrefs.setRelayEnabled(context, true)
            val intent = Intent(context, MeshRelayService::class.java)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent)
            else context.startService(intent)
        }

        fun stop(context: Context) {
            RelayPrefs.setRelayEnabled(context, false)
            context.stopService(Intent(context, MeshRelayService::class.java))
        }
    }
}

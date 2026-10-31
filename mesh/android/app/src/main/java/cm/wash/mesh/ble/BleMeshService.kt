package cm.wash.mesh.ble

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattServer
import android.bluetooth.BluetoothGattServerCallback
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.ParcelUuid
import androidx.core.app.NotificationCompat
import cm.wash.mesh.MeshProtocol
import cm.wash.mesh.data.BundleEntity
import cm.wash.mesh.relay.RelayPrefs
import cm.wash.mesh.data.MeshDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.Collections
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue

/**
 * Transport BLE GATT brut — SECOURS quand Nearby/Play Services est absent
 * (téléphones dégooglisés, Huawei…). 100 % offline, petits bundles (<50 Ko).
 *
 * Chaque nœud est serveur (advertise + notifie son outbox) ET client
 * (scan filtré + écrit son outbox) : les deux directions sont couvertes,
 * la dédup par bundle_id absorbe les doublons entre les deux liens.
 *
 * Contraintes AOSP respectées (dossier Phase 1) : 1 scan/30 s max
 * (duty-cycle 8 s scan / 22 s idle), ≤3 connexions, MTU négocié,
 * écritures chaînées une par une, foreground service permanent.
 */
class BleMeshService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var nodeId: String
    private var adapter: BluetoothAdapter? = null
    private var gattServer: BluetoothGattServer? = null
    private var txChar: BluetoothGattCharacteristic? = null
    private var scanJob: Job? = null

    private val reassembler = BleFrame.Reassembler()
    private val mtuByDevice = ConcurrentHashMap<String, Int>()
    private val clientConns = ConcurrentHashMap<String, BluetoothGatt>()
    private val subscribed = Collections.synchronizedSet(mutableSetOf<String>())
    private val serverQueues = ConcurrentHashMap<String, ConcurrentLinkedQueue<ByteArray>>()
    private val serverSending = Collections.synchronizedSet(mutableSetOf<String>())
    private val clientQueues = ConcurrentHashMap<String, ConcurrentLinkedQueue<ByteArray>>()
    private val clientSending = Collections.synchronizedSet(mutableSetOf<String>())

    // ---------- Rôle serveur (périphérique) ----------

    private val serverCallback = object : BluetoothGattServerCallback() {
        override fun onConnectionStateChange(device: BluetoothDevice, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                subscribed.remove(device.address)
                serverQueues.remove(device.address)
            }
        }

        override fun onMtuChanged(device: BluetoothDevice, mtu: Int) {
            mtuByDevice[device.address] = mtu
        }

        override fun onDescriptorWriteRequest(
            device: BluetoothDevice, requestId: Int, descriptor: BluetoothGattDescriptor,
            preparedWrite: Boolean, responseNeeded: Boolean, offset: Int, value: ByteArray,
        ) {
            if (responseNeeded) {
                gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, value)
            }
            if (descriptor.uuid == UUID.fromString(BleFrame.CCCD_UUID) &&
                value.contentEquals(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
            ) {
                subscribed.add(device.address)
                scope.launch { sendOutboxToServerPeer(device) }
            }
        }

        override fun onCharacteristicWriteRequest(
            device: BluetoothDevice, requestId: Int, characteristic: BluetoothGattCharacteristic,
            preparedWrite: Boolean, responseNeeded: Boolean, offset: Int, value: ByteArray,
        ) {
            if (responseNeeded) {
                gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, value)
            }
            if (characteristic.uuid == UUID.fromString(BleFrame.RX_CHAR_UUID)) {
                onFramesReceived(value)
            }
        }

        override fun onNotificationSent(device: BluetoothDevice, status: Int) {
            serverSending.remove(device.address)
            pumpServerQueue(device.address)
        }
    }

    // ---------- Rôle client (central) ----------

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val device = result.device ?: return
            if (clientConns.size >= MAX_CONNECTIONS || clientConns.containsKey(device.address)) return
            runCatching {
                val gatt = device.connectGatt(this@BleMeshService, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
                if (gatt != null) clientConns[device.address] = gatt
            }
        }
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            val address = gatt.device.address
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                runCatching { gatt.requestMtu(512) } ?: runCatching { gatt.discoverServices() }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                clientConns.remove(address)
                runCatching { gatt.close() }
            }
        }

        override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) mtuByDevice[gatt.device.address] = mtu
            runCatching { gatt.discoverServices() }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) return
            val tx = gatt.getService(UUID.fromString(BleFrame.SERVICE_UUID))
                ?.getCharacteristic(UUID.fromString(BleFrame.TX_CHAR_UUID)) ?: return
            runCatching { gatt.setCharacteristicNotification(tx, true) }
            val cccd = tx.getDescriptor(UUID.fromString(BleFrame.CCCD_UUID)) ?: return
            if (Build.VERSION.SDK_INT >= 33) {
                runCatching { gatt.writeDescriptor(cccd, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE) }
            } else {
                @Suppress("DEPRECATION")
                cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                @Suppress("DEPRECATION")
                runCatching { gatt.writeDescriptor(cccd) }
            }
        }

        override fun onDescriptorWrite(gatt: BluetoothGatt, descriptor: BluetoothGattDescriptor, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) scope.launch { sendOutboxToClientPeer(gatt) }
        }

        override fun onCharacteristicChanged(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION")
            onFramesReceived(characteristic.value ?: return)
        }

        override fun onCharacteristicChanged(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic, value: ByteArray) {
            onFramesReceived(value)
        }

        override fun onCharacteristicWrite(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            clientSending.remove(gatt.device.address)
            pumpClientQueue(gatt)
        }
    }

    // ---------- Échange ----------

    private fun onFramesReceived(frame: ByteArray) {
        val complete = reassembler.feed(frame) ?: return
        scope.launch {
            val bundle = runCatching { JSONObject(String(complete, Charsets.UTF_8)) }.getOrNull() ?: return@launch
            if (!MeshProtocol.requiredFieldsOk(bundle) || !MeshProtocol.verify(bundle)) return@launch
            val fwd = MeshProtocol.forward(bundle, nodeId) ?: return@launch
            MeshDatabase.get(this@BleMeshService).dao().insert(
                BundleEntity(
                    fwd.give.getString("bundle_id"),
                    fwd.give.getString("origin_node_id"),
                    fwd.give.optInt("school_id", 0),
                    fwd.give.toString(),
                ),
            )
        }
    }

    private suspend fun queueOutbox(): List<Pair<String, List<ByteArray>>> {
        // Petits bundles d'abord (Rhizome) ; fragments médias exclus (trop gros pour le BLE).
        return MeshDatabase.get(this).dao().pending()
            .filter { e ->
                val json = runCatching { JSONObject(e.json) }.getOrNull()
                json != null && json.isNull("chunk") && e.json.toByteArray(Charsets.UTF_8).size <= MAX_BUNDLE_BYTES
            }
            .mapNotNull { e ->
                val bundle = runCatching { JSONObject(e.json) }.getOrNull() ?: return@mapNotNull null
                val fwd = MeshProtocol.forward(bundle, nodeId) ?: return@mapNotNull null
                e.id to fwd
            }
            .map { (id, fwd) ->
                val bytes = fwd.give.toString().toByteArray(Charsets.UTF_8)
                Triple(id, fwd, bytes)
            }
            .map { (id, fwd, bytes) ->
                MeshDatabase.get(this).dao().updateJson(
                    id,
                    JSONObject(fwd.give.toString()).put("copies_remaining", fwd.keepCopies).toString(),
                )
                fwd.give.getString("bundle_id") to bytes
            }
    }

    private suspend fun sendOutboxToServerPeer(device: BluetoothDevice) {
        val mtu = mtuByDevice.getOrDefault(device.address, 23)
        val queue = serverQueues.getOrPut(device.address) { ConcurrentLinkedQueue() }
        for ((bundleId, bytes) in queueOutbox()) {
            BleFrame.encode(bytes, bundleId, mtu).forEach(queue::offer)
        }
        pumpServerQueue(device.address)
    }

    private fun pumpServerQueue(address: String) {
        val queue = serverQueues[address] ?: return
        if (!serverSending.add(address)) return
        val frame = queue.poll()
        if (frame == null) {
            serverSending.remove(address)
            return
        }
        val device = adapter?.getRemoteDevice(address)
        val char = txChar
        if (device == null || char == null || !subscribed.contains(address)) {
            serverSending.remove(address)
            return
        }
        @Suppress("DEPRECATION")
        char.value = frame
        @Suppress("DEPRECATION")
        val ok = runCatching { gattServer?.notifyCharacteristicChanged(device, char, false) ?: false }.getOrDefault(false)
        if (!ok) {
            serverSending.remove(address)
            pumpServerQueue(address)
        }
    }

    private suspend fun sendOutboxToClientPeer(gatt: BluetoothGatt) {
        val mtu = mtuByDevice.getOrDefault(gatt.device.address, 23)
        val queue = clientQueues.getOrPut(gatt.device.address) { ConcurrentLinkedQueue() }
        for ((bundleId, bytes) in queueOutbox()) {
            BleFrame.encode(bytes, bundleId, mtu).forEach(queue::offer)
        }
        pumpClientQueue(gatt)
    }

    private fun pumpClientQueue(gatt: BluetoothGatt) {
        val address = gatt.device.address
        val queue = clientQueues[address] ?: return
        if (!clientSending.add(address)) return
        val frame = queue.poll()
        if (frame == null) {
            clientSending.remove(address)
            return
        }
        val rx = gatt.getService(UUID.fromString(BleFrame.SERVICE_UUID))
            ?.getCharacteristic(UUID.fromString(BleFrame.RX_CHAR_UUID))
        if (rx == null) {
            clientSending.remove(address)
            return
        }
        rx.writeType = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
        val ok = if (Build.VERSION.SDK_INT >= 33) {
            runCatching { gatt.writeCharacteristic(rx, frame, BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE) == 0 }.getOrDefault(false)
        } else {
            @Suppress("DEPRECATION")
            rx.value = frame
            @Suppress("DEPRECATION")
            runCatching { gatt.writeCharacteristic(rx) }.getOrDefault(false)
        }
        if (!ok) {
            clientSending.remove(address)
            pumpClientQueue(gatt)
        }
    }

    // ---------- Cycle de vie ----------

    override fun onCreate() {
        super.onCreate()
        nodeId = RelayPrefs.getOrCreateNodeId(this)
        val manager = getSystemService(BluetoothManager::class.java)
        adapter = manager?.adapter
        startForegrounded()
        startGattServer(manager)
        startAdvertising()
        startDutyCycledScan()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onDestroy() {
        scanJob?.cancel()
        runCatching { adapter?.bluetoothLeScanner?.stopScan(scanCallback) }
        runCatching { adapter?.bluetoothLeAdvertiser?.stopAdvertising(advertiseCallback) }
        clientConns.values.forEach { runCatching { it.disconnect() }; runCatching { it.close() } }
        runCatching { gattServer?.close() }
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private val advertiseCallback = object : AdvertiseCallback() {}

    private fun startGattServer(manager: BluetoothManager?) {
        val server = manager?.openGattServer(this, serverCallback) ?: return
        gattServer = server
        val service = BluetoothGattService(UUID.fromString(BleFrame.SERVICE_UUID), BluetoothGattService.SERVICE_TYPE_PRIMARY)
        val tx = BluetoothGattCharacteristic(
            UUID.fromString(BleFrame.TX_CHAR_UUID),
            BluetoothGattCharacteristic.PROPERTY_NOTIFY,
            BluetoothGattCharacteristic.PERMISSION_READ,
        )
        tx.addDescriptor(
            BluetoothGattDescriptor(
                UUID.fromString(BleFrame.CCCD_UUID),
                BluetoothGattDescriptor.PERMISSION_READ or BluetoothGattDescriptor.PERMISSION_WRITE,
            ),
        )
        val rx = BluetoothGattCharacteristic(
            UUID.fromString(BleFrame.RX_CHAR_UUID),
            BluetoothGattCharacteristic.PROPERTY_WRITE or BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE,
            BluetoothGattCharacteristic.PERMISSION_WRITE,
        )
        txChar = tx
        service.addCharacteristic(tx)
        service.addCharacteristic(rx)
        server.addService(service)
    }

    private fun startAdvertising() {
        val advertiser = adapter?.bluetoothLeAdvertiser ?: return
        val settings = AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
            .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_HIGH)
            .setConnectable(true)
            .build()
        val data = AdvertiseData.Builder()
            .addServiceUuid(ParcelUuid(UUID.fromString(BleFrame.SERVICE_UUID)))
            .setIncludeDeviceName(false)
            .build()
        runCatching { advertiser.startAdvertising(settings, data, advertiseCallback) }
    }

    private fun startDutyCycledScan() {
        scanJob = scope.launch {
            val scanner = adapter?.bluetoothLeScanner
            val filter = ScanFilter.Builder()
                .setServiceUuid(ParcelUuid(UUID.fromString(BleFrame.SERVICE_UUID)))
                .build()
            val settings = ScanSettings.Builder()
                .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                .build()
            while (isActive) {
                runCatching { scanner?.startScan(listOf(filter), settings, scanCallback) }
                delay(SCAN_MS)
                runCatching { scanner?.stopScan(scanCallback) }
                delay(IDLE_MS)
            }
        }
    }

    private fun startForegrounded() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "Relai BLE WASH", NotificationManager.IMPORTANCE_LOW),
        )
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setContentTitle("Relai BLE WASH actif")
            .setContentText("Mesh Bluetooth de $nodeId")
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
        private const val CHANNEL = "wash_mesh_ble"
        private const val NOTIF_ID = 43
        private const val MAX_CONNECTIONS = 3
        private const val SCAN_MS = BleDutyCycle.ACTIVE_MS
        private const val IDLE_MS = BleDutyCycle.IDLE_MS
        private const val MAX_BUNDLE_BYTES = 50 * 1024

        fun isSupported(context: Context): Boolean =
            context.packageManager.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE)

        fun start(context: Context) {
            RelayPrefs.setRelayEnabled(context, true)
            val intent = Intent(context, BleMeshService::class.java)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent)
            else context.startService(intent)
        }

        fun stop(context: Context) {
            RelayPrefs.setRelayEnabled(context, false)
            context.stopService(Intent(context, BleMeshService::class.java))
        }
    }
}

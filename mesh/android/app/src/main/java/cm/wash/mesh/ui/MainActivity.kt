package cm.wash.mesh.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import cm.wash.mesh.MeshProtocol
import cm.wash.mesh.R
import cm.wash.mesh.data.BundleEntity
import cm.wash.mesh.data.MeshDatabase
import cm.wash.mesh.ble.BleMeshService
import cm.wash.mesh.mesh.MeshRelayService
import cm.wash.mesh.mesh.TransportSelector
import cm.wash.mesh.mesh.UploadWorker
import cm.wash.mesh.relay.FieldSettings
import cm.wash.mesh.relay.RelayPrefs
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import cm.wash.mesh.net.Api
import cm.wash.mesh.qr.Qr
import com.google.android.gms.common.moduleinstall.ModuleInstall
import com.google.android.gms.common.moduleinstall.ModuleInstallRequest
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Écran unique du relai villageois : saisie offline, QR (émission/scan),
 * sync relai WiFi, upload serveur, marche/arrêt du relai ambiant.
 */
class MainActivity : AppCompatActivity() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var nodeId: String
    private var relayOn = false
    private lateinit var llOutbox: LinearLayout
    private lateinit var tvOutboxCounts: TextView

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { _ -> }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        nodeId = RelayPrefs.getOrCreateNodeId(this)
        relayOn = RelayPrefs.isRelayEnabled(this)

        requestPermissions()
        // Pré-chauffe le module Code Scanner (1er usage = téléchargement Play Services).
        runCatching {
            ModuleInstall.getClient(this).installModules(
                ModuleInstallRequest.newBuilder().addApi(GmsBarcodeScanning.getClient(this)).build(),
            )
        }

        val etSchoolId = findViewById<EditText>(R.id.etSchoolId)
        val etSchoolCode = findViewById<EditText>(R.id.etSchoolCode)
        val etMessage = findViewById<EditText>(R.id.etMessage)
        val tvStatus = findViewById<TextView>(R.id.tvStatus)
        val ivQr = findViewById<ImageView>(R.id.ivQr)
        tvStatus.text = "Nœud $nodeId"
        llOutbox = findViewById(R.id.llOutbox)
        tvOutboxCounts = findViewById(R.id.tvOutboxCounts)

        findViewById<Button>(R.id.btnSettings).setOnClickListener {
            SettingsActivity.start(this)
        }

        findViewById<Button>(R.id.btnSave).setOnClickListener {
            val schoolId = etSchoolId.text.toString().toIntOrNull()
            val message = etMessage.text.toString().trim()
            if (schoolId == null || message.isEmpty()) {
                toast("École (id) + message requis.")
                return@setOnClickListener
            }
            scope.launch(Dispatchers.IO) {
                val bundle = MeshProtocol.newBundle(
                    schoolId, etSchoolCode.text.toString().ifBlank { null }, message, nodeId,
                )
                MeshDatabase.get(this@MainActivity).dao().insert(
                    BundleEntity(bundle.getString("bundle_id"), nodeId, schoolId, bundle.toString()),
                )
                withContext(Dispatchers.Main) {
                    toast("Bundle offline enregistré.")
                    refreshOutbox()
                }
            }
        }

        findViewById<Button>(R.id.btnQr).setOnClickListener {
            scope.launch(Dispatchers.IO) {
                val last = MeshDatabase.get(this@MainActivity).dao().pending().lastOrNull()
                withContext(Dispatchers.Main) {
                    if (last == null) toast("Outbox vide.")
                    else ivQr.setImageBitmap(Qr.encode(MeshProtocol.toQr(JSONObject(last.json))))
                }
            }
        }

        findViewById<Button>(R.id.btnScan).setOnClickListener {
            GmsBarcodeScanning.getClient(this).startScan()
                .addOnSuccessListener { barcode ->
                    val raw = barcode.rawValue ?: return@addOnSuccessListener
                    scope.launch(Dispatchers.IO) {
                        val bundle = MeshProtocol.fromQr(raw)
                        val ok = bundle != null && MeshProtocol.requiredFieldsOk(bundle) && MeshProtocol.verify(bundle)
                        if (ok) {
                            MeshDatabase.get(this@MainActivity).dao().insert(
                                BundleEntity(
                                    bundle!!.getString("bundle_id"),
                                    bundle.getString("origin_node_id"),
                                    bundle.optInt("school_id", 0),
                                    bundle.toString(),
                                ),
                            )
                        }
                        withContext(Dispatchers.Main) {
                            toast(if (ok) "Bundle reçu." else "QR invalide.")
                            if (ok) refreshOutbox()
                        }
                    }
                }
                .addOnFailureListener { toast("Scan annulé.") }
        }

        findViewById<Button>(R.id.btnSync).setOnClickListener {
            val relayUrl = FieldSettings.getRelayUrl(this)
            val meshKey = FieldSettings.getMeshKey(this)
            scope.launch(Dispatchers.IO) {
                try {
                    val dao = MeshDatabase.get(this@MainActivity).dao()
                    val pending = dao.pending()
                    val res = Api.relaySync(
                        relayUrl, nodeId,
                        pending.map { JSONObject(it.json) }, pending.map { it.id },
                        meshKey,
                    )
                    var received = 0
                    for (raw in res.received) {
                        if (!MeshProtocol.requiredFieldsOk(raw) || !MeshProtocol.verify(raw)) continue
                        val fwd = MeshProtocol.forward(raw, nodeId) ?: continue
                        dao.insert(
                            BundleEntity(
                                fwd.give.getString("bundle_id"),
                                fwd.give.getString("origin_node_id"),
                                fwd.give.optInt("school_id", 0),
                                fwd.give.toString(),
                            ),
                        )
                        received++
                    }
                    withContext(Dispatchers.Main) {
                        toast("Sync: +$received reçu(s).")
                        refreshOutbox()
                    }
                } catch (e: Exception) {
                    withContext(Dispatchers.Main) { toast("Relai injoignable.") }
                }
            }
        }

        findViewById<Button>(R.id.btnUpload).setOnClickListener {
            val req = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setInputData(
                    workDataOf(
                        "api_url" to FieldSettings.getLaravelApiUrl(this),
                        "mesh_key" to FieldSettings.getMeshKey(this),
                    ),
                )
                .build()
            WorkManager.getInstance(this).enqueue(req)
            toast("Upload planifié (dès que connecté).")
            refreshOutbox()
        }

        // Transport auto : Nearby si Play Services, sinon BLE GATT brut (secours V3).
        val useNearby = GoogleApiAvailability.getInstance()
            .isGooglePlayServicesAvailable(this) == ConnectionResult.SUCCESS
        val transport = if (useNearby) "Nearby" else "BLE"
        val btnRelay = findViewById<Button>(R.id.btnRelay)
        btnRelay.text = if (relayOn) "Stopper le relai ($transport)" else "Démarrer le relai ($transport)"
        btnRelay.setOnClickListener {
            relayOn = !relayOn
            if (relayOn) {
                if (useNearby) MeshRelayService.start(this) else BleMeshService.start(this)
            } else {
                MeshRelayService.stop(this)
                BleMeshService.stop(this)
            }
            val sel = TransportSelector.select(useNearby && relayOn, relayOn && BleMeshService.isSupported(this), 0)
            Log.i(TAG, "transport : ${sel.primary} (${sel.reason}), secours ${sel.fallbacks}")
            btnRelay.text = if (relayOn) "Stopper le relai ($transport)" else "Démarrer le relai ($transport)"
        }
    }

    override fun onResume() {
        super.onResume()
        refreshOutbox()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    /** Recharge la file d'envoi visible (Room sur IO, rendu sur Main). */
    private fun refreshOutbox() {
        scope.launch(Dispatchers.IO) {
            val dao = MeshDatabase.get(this@MainActivity).dao()
            val items = dao.outbox(OUTBOX_LIMIT)
            val pending = dao.pendingCount()
            val done = dao.doneCount()
            val rows = items.map { toRow(it) }
            withContext(Dispatchers.Main) { renderOutbox(rows, pending, done) }
        }
    }

    private fun toRow(e: BundleEntity): OutboxRow {
        val json = runCatching { JSONObject(e.json) }.getOrNull()
        val schoolCode = json?.optString("school_code").orEmpty()
        val school = if (schoolCode.isNotBlank()) "École ${e.schoolId} ($schoolCode)" else "École ${e.schoolId}"
        val date = json?.optString("created_at").orEmpty().take(16).replace("T", " ")
        val message = json?.optString("message").orEmpty()
            .replace(Regex("\\s+"), " ").trim().take(80)
        val title = e.id.take(8) + " • " + school + if (date.isNotBlank()) " • $date" else ""
        return OutboxRow(e.id, title, message)
    }

    private fun renderOutbox(rows: List<OutboxRow>, pending: Int, done: Int) {
        tvOutboxCounts.text = "En attente : $pending • Envoyés : $done"
        llOutbox.removeAllViews()
        val pad = (8 * resources.displayMetrics.density).toInt()
        if (rows.isEmpty()) {
            val tv = TextView(this)
            tv.text = "File vide — rien en attente."
            tv.setPadding(pad, pad, pad, pad)
            llOutbox.addView(tv)
            return
        }
        for (row in rows) {
            val line = LinearLayout(this)
            line.orientation = LinearLayout.HORIZONTAL
            line.setPadding(0, pad / 2, 0, pad / 2)
            val tv = TextView(this)
            tv.layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            tv.text = if (row.excerpt.isNotBlank()) row.title + "\n" + row.excerpt else row.title
            val btn = Button(this)
            btn.text = "Retirer"
            btn.setOnClickListener { removeBundle(row.id) }
            line.addView(tv)
            line.addView(btn)
            llOutbox.addView(line)
        }
    }

    private fun removeBundle(id: String) {
        scope.launch(Dispatchers.IO) {
            MeshDatabase.get(this@MainActivity).dao().deleteById(id)
            withContext(Dispatchers.Main) {
                toast("Bundle retiré.")
                refreshOutbox()
            }
        }
    }

    private fun requestPermissions() {
        val wanted = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.RECEIVE_SMS,
        )
        if (Build.VERSION.SDK_INT >= 31) {
            wanted += Manifest.permission.BLUETOOTH_SCAN
            wanted += Manifest.permission.BLUETOOTH_CONNECT
            wanted += Manifest.permission.BLUETOOTH_ADVERTISE
        }
        if (Build.VERSION.SDK_INT >= 33) {
            wanted += Manifest.permission.NEARBY_WIFI_DEVICES
            wanted += Manifest.permission.POST_NOTIFICATIONS
        }
        val missing = wanted.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isNotEmpty()) permissionLauncher.launch(missing.toTypedArray())
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

    private data class OutboxRow(val id: String, val title: String, val excerpt: String)

    companion object {
        private const val TAG = "WashUi"
        private const val OUTBOX_LIMIT = 50
    }
}

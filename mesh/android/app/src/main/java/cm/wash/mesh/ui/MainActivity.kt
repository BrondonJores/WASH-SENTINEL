package cm.wash.mesh.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
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
import cm.wash.mesh.BuildConfig
import cm.wash.mesh.MeshProtocol
import cm.wash.mesh.R
import cm.wash.mesh.data.BundleEntity
import cm.wash.mesh.data.MeshDatabase
import cm.wash.mesh.mesh.MeshRelayService
import cm.wash.mesh.mesh.UploadWorker
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

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { _ -> }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        nodeId = getSharedPreferences("wash_mesh", Context.MODE_PRIVATE)
            .getString("node_id", null)
            ?: MeshProtocol.newNodeId().also {
                getSharedPreferences("wash_mesh", Context.MODE_PRIVATE).edit().putString("node_id", it).apply()
            }

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
                withContext(Dispatchers.Main) { toast("Bundle offline enregistré.") }
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
                        withContext(Dispatchers.Main) { toast(if (ok) "Bundle reçu." else "QR invalide.") }
                    }
                }
                .addOnFailureListener { toast("Scan annulé.") }
        }

        findViewById<Button>(R.id.btnSync).setOnClickListener {
            scope.launch(Dispatchers.IO) {
                try {
                    val dao = MeshDatabase.get(this@MainActivity).dao()
                    val pending = dao.pending()
                    val res = Api.relaySync(
                        BuildConfig.RELAY_URL, nodeId,
                        pending.map { JSONObject(it.json) }, pending.map { it.id },
                        BuildConfig.MESH_KEY,
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
                    withContext(Dispatchers.Main) { toast("Sync: +$received reçu(s).") }
                } catch (e: Exception) {
                    withContext(Dispatchers.Main) { toast("Relai injoignable.") }
                }
            }
        }

        findViewById<Button>(R.id.btnUpload).setOnClickListener {
            val req = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setInputData(workDataOf("api_url" to BuildConfig.LARAVEL_API_URL, "mesh_key" to BuildConfig.MESH_KEY))
                .build()
            WorkManager.getInstance(this).enqueue(req)
            toast("Upload planifié (dès que connecté).")
        }

        val btnRelay = findViewById<Button>(R.id.btnRelay)
        btnRelay.setOnClickListener {
            relayOn = !relayOn
            if (relayOn) MeshRelayService.start(this) else MeshRelayService.stop(this)
            btnRelay.text = if (relayOn) "Stopper le relai" else "Démarrer le relai"
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
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
}

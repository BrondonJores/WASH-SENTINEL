package cm.wash.mesh.ui

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import cm.wash.mesh.R
import cm.wash.mesh.relay.FieldSettings

/**
 * Écran réglages terrain : URLs/secrets/quota sans recompiler.
 * Champs pré-remplis avec les valeurs effectives ; vide = valeur compilée.
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var etRelayUrl: EditText
    private lateinit var etLaravelApiUrl: EditText
    private lateinit var etMeshKey: EditText
    private lateinit var etSmsSecret: EditText
    private lateinit var etSmsAllowlist: EditText
    private lateinit var etSmsQuota: EditText

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        etRelayUrl = findViewById(R.id.etRelayUrl)
        etLaravelApiUrl = findViewById(R.id.etLaravelApiUrl)
        etMeshKey = findViewById(R.id.etMeshKey)
        etSmsSecret = findViewById(R.id.etSmsSecret)
        etSmsAllowlist = findViewById(R.id.etSmsAllowlist)
        etSmsQuota = findViewById(R.id.etSmsQuota)

        fillFromSettings()

        findViewById<Button>(R.id.btnSettingsSave).setOnClickListener {
            val quota = etSmsQuota.text.toString().trim().toIntOrNull()
                ?.takeIf { it >= 0 } ?: FieldSettings.QUOTA_UNSET
            FieldSettings.saveAll(
                this,
                etRelayUrl.text.toString().trim(),
                etLaravelApiUrl.text.toString().trim(),
                etMeshKey.text.toString().trim(),
                etSmsSecret.text.toString().trim(),
                etSmsAllowlist.text.toString().trim(),
                quota,
            )
            Toast.makeText(this, "Paramètres enregistrés", Toast.LENGTH_SHORT).show()
            finish()
        }

        findViewById<Button>(R.id.btnSettingsReset).setOnClickListener {
            FieldSettings.resetToDefaults(this)
            fillFromSettings()
            Toast.makeText(this, "Valeurs compilées restaurées", Toast.LENGTH_SHORT).show()
        }
    }

    private fun fillFromSettings() {
        etRelayUrl.setText(FieldSettings.getRelayUrl(this))
        etLaravelApiUrl.setText(FieldSettings.getLaravelApiUrl(this))
        etMeshKey.setText(FieldSettings.getMeshKey(this))
        etSmsSecret.setText(FieldSettings.getSmsSecret(this))
        etSmsAllowlist.setText(FieldSettings.getSmsAllowlist(this))
        etSmsQuota.setText(FieldSettings.getSmsQuota(this).toString())
    }

    companion object {
        fun start(context: Context) {
            context.startActivity(Intent(context, SettingsActivity::class.java))
        }
    }
}

package cm.wash.mesh.relay

import android.content.Context
import cm.wash.mesh.MeshProtocol

/** Préférences partagées du relai : identité du nœud + interrupteur persistant. */
object RelayPrefs {
    const val NAME = "wash_mesh"
    const val KEY_NODE_ID = "node_id"
    const val KEY_RELAY_ENABLED = "relay_enabled"

    fun getOrCreateNodeId(context: Context): String {
        val prefs = context.getSharedPreferences(NAME, Context.MODE_PRIVATE)
        prefs.getString(KEY_NODE_ID, null)?.let { return it }
        val fresh = MeshProtocol.newNodeId()
        prefs.edit().putString(KEY_NODE_ID, fresh).apply()
        return fresh
    }

    fun isRelayEnabled(context: Context): Boolean =
        context.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .getBoolean(KEY_RELAY_ENABLED, false)

    fun setRelayEnabled(context: Context, enabled: Boolean) {
        context.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .edit().putBoolean(KEY_RELAY_ENABLED, enabled).apply()
    }
}

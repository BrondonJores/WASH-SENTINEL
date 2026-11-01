package cm.wash.mesh.relay

import android.content.Context
import cm.wash.mesh.BuildConfig

/**
 * Réglages terrain : URLs/secrets/quota modifiables sur le terrain sans
 * recompiler. Stockés dans `wash_mesh_settings` ; un champ vide ou absent
 * retombe sur la valeur compilée (BuildConfig).
 */
object FieldSettings {
    const val NAME = "wash_mesh_settings"

    private const val KEY_RELAY_URL = "relay_url"
    private const val KEY_LARAVEL_API_URL = "laravel_api_url"
    private const val KEY_MESH_KEY = "mesh_key"
    private const val KEY_SMS_SECRET = "sms_secret"
    private const val KEY_SMS_ALLOWLIST = "sms_allowlist"
    private const val KEY_SMS_QUOTA = "sms_quota"

    /** Sentinelle quota : aucune valeur saisie → valeur compilée. */
    const val QUOTA_UNSET = -1

    private fun prefs(ctx: Context) =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun getRelayUrl(ctx: Context): String =
        prefs(ctx).getString(KEY_RELAY_URL, null)
            .takeUnless { it.isNullOrEmpty() } ?: BuildConfig.RELAY_URL

    fun getLaravelApiUrl(ctx: Context): String =
        prefs(ctx).getString(KEY_LARAVEL_API_URL, null)
            .takeUnless { it.isNullOrEmpty() } ?: BuildConfig.LARAVEL_API_URL

    fun getMeshKey(ctx: Context): String =
        prefs(ctx).getString(KEY_MESH_KEY, null)
            .takeUnless { it.isNullOrEmpty() } ?: BuildConfig.MESH_KEY

    fun getSmsSecret(ctx: Context): String =
        prefs(ctx).getString(KEY_SMS_SECRET, null)
            .takeUnless { it.isNullOrEmpty() } ?: BuildConfig.SMS_SECRET

    fun getSmsAllowlist(ctx: Context): String =
        prefs(ctx).getString(KEY_SMS_ALLOWLIST, null)
            .takeUnless { it.isNullOrEmpty() } ?: BuildConfig.SMS_ALLOWLIST

    fun getSmsQuota(ctx: Context): Int {
        val stored = prefs(ctx).getInt(KEY_SMS_QUOTA, QUOTA_UNSET)
        return if (stored < 0) BuildConfig.SMS_QUOTA else stored
    }

    fun saveAll(
        ctx: Context,
        relayUrl: String,
        laravelApiUrl: String,
        meshKey: String,
        smsSecret: String,
        allowlist: String,
        quota: Int,
    ) {
        prefs(ctx).edit()
            .putString(KEY_RELAY_URL, relayUrl)
            .putString(KEY_LARAVEL_API_URL, laravelApiUrl)
            .putString(KEY_MESH_KEY, meshKey)
            .putString(KEY_SMS_SECRET, smsSecret)
            .putString(KEY_SMS_ALLOWLIST, allowlist)
            .putInt(KEY_SMS_QUOTA, quota)
            .apply()
    }

    fun resetToDefaults(ctx: Context) {
        prefs(ctx).edit().clear().apply()
    }
}

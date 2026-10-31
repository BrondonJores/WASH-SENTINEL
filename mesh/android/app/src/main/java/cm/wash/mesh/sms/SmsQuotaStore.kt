package cm.wash.mesh.sms

import android.content.Context

/** Compteur local des transferts par expéditeur et par jour (anti-spam redondant du serveur). */
object SmsQuotaStore {
    private const val NAME = "wash_sms_quota"

    fun countFor(context: Context, from: String, today: String): Int =
        context.getSharedPreferences(NAME, Context.MODE_PRIVATE).getInt(key(from, today), 0)

    /** Incrémente et retourne le nouveau compteur. */
    fun record(context: Context, from: String, today: String): Int {
        val prefs = context.getSharedPreferences(NAME, Context.MODE_PRIVATE)
        val next = prefs.getInt(key(from, today), 0) + 1
        prefs.edit().putInt(key(from, today), next).apply()
        return next
    }

    private fun key(from: String, today: String): String = "$today|$from"
}

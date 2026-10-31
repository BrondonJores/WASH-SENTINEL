package cm.wash.mesh.ble

/**
 * Rapport cyclique du scan BLE : 8 s de scan actif puis 22 s de repos,
 * soit un cycle de 30 s (~27 % de duty-cycle). Seul le scan est cyclé
 * (l'advertise et le serveur GATT restent continus) : le scan étant le
 * poste le plus gourmand et contingenté par AOSP (5 scans/30 s),
 * ce cycle divise par ~4 la dépense du relai de secours. Kotlin pur.
 */
object BleDutyCycle {
    const val ACTIVE_MS = 8_000L
    const val IDLE_MS = 22_000L
    const val CYCLE_MS = ACTIVE_MS + IDLE_MS

    /** true pendant la fenêtre active du cycle contenant [elapsedMs]. */
    fun isActiveWindow(elapsedMs: Long): Boolean {
        if (elapsedMs < 0) return true
        return (elapsedMs % CYCLE_MS) < ACTIVE_MS
    }

    /** Millisecondes restantes avant le prochain changement de phase. */
    fun msUntilNextPhase(elapsedMs: Long): Long {
        val pos = ((elapsedMs % CYCLE_MS) + CYCLE_MS) % CYCLE_MS
        return if (pos < ACTIVE_MS) ACTIVE_MS - pos else CYCLE_MS - pos
    }
}

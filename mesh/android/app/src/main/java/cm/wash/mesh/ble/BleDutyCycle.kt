package cm.wash.mesh.ble

/**
 * Rapport cyclique BLE : 8 s de radio active (advertise + scan + GATT)
 * puis 22 s de radio coupée, soit un cycle de 30 s (~27 % de duty-cycle).
 * La radio BLE est la principale consommatrice ; la couper 73 % du temps
 * divise par ~4 la dépense du relai de secours. Kotlin pur.
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

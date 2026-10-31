package cm.wash.mesh.relay

/**
 * Politique de redémarrage du relai après kill (backoff exponentiel borné).
 * Kotlin pur : la temporisation réelle est portée par WorkManager / le système.
 */
object RestartPolicy {
    const val BASE_DELAY_MS = 5_000L
    const val MAX_DELAY_MS = 300_000L

    /** Délai avant la tentative [attempt] (0 = première) : base * 2^attempt, plafonné. */
    fun nextDelayMs(attempt: Int, baseMs: Long = BASE_DELAY_MS, maxMs: Long = MAX_DELAY_MS): Long {
        if (attempt <= 0 || baseMs <= 0) return baseMs.coerceAtLeast(0)
        var delay = baseMs
        repeat(attempt.coerceAtMost(20)) { delay = (delay * 2).coerceAtMost(maxMs) }
        return delay
    }
}

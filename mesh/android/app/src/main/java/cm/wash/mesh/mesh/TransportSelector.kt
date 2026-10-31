package cm.wash.mesh.mesh

/** Transports d'émission par ordre de préférence : rapide → dégradé → manuel. */
enum class Transport {
    NEARBY,
    BLE,
    QR,
}

/**
 * Sélecteur automatique Nearby → BLE → QR. Le QR reste le recours ultime
 * (aucune radio requise) mais prévient quand le bundle dépasse sa capacité.
 * Kotlin pur : l'appelant journalise [Selection.reason].
 */
object TransportSelector {
    /** Capacité QR sûre en mode binaire (marge sous les ~2953 octets théoriques). */
    const val QR_MAX_BYTES = 2000

    data class Selection(
        val primary: Transport,
        val fallbacks: List<Transport>,
        val reason: String,
    )

    fun select(nearbyReady: Boolean, bleReady: Boolean, payloadBytes: Int): Selection {
        val primary = when {
            nearbyReady -> Transport.NEARBY
            bleReady -> Transport.BLE
            else -> Transport.QR
        }
        val fallbacks = Transport.values()
            .filter { it != primary && usable(it, nearbyReady, bleReady) }
        val reason = buildString {
            when (primary) {
                Transport.NEARBY -> append("Nearby actif")
                Transport.BLE -> append("Nearby indisponible → BLE (secours GATT)")
                Transport.QR -> append("Nearby et BLE indisponibles → QR manuel")
            }
            if (primary == Transport.QR && payloadBytes > QR_MAX_BYTES) {
                append(" ; bundle volumineux ($payloadBytes octets), privilégier Nearby/BLE dès que possible")
            }
        }
        return Selection(primary, fallbacks, reason)
    }

    private fun usable(t: Transport, nearbyReady: Boolean, bleReady: Boolean): Boolean = when (t) {
        Transport.NEARBY -> nearbyReady
        Transport.BLE -> bleReady
        Transport.QR -> true
    }
}

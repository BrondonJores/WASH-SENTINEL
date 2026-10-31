package cm.wash.mesh.sms

import java.text.Normalizer

/**
 * Règles locales de la passerelle SMS, miroir du backend
 * (MeshSmsParser + WashSmsController) : même grammaire WASH/EAU,
 * mêmes types, allowlist exacte, quota journalier par expéditeur.
 * Filtrage précoce : ce qui est rejeté ici ne part jamais au serveur.
 * Kotlin pur.
 */
object SmsPolicy {
    val KEYWORDS = setOf("WASH", "EAU")

    val TYPES: Map<Char, Set<String>> = mapOf(
        'P' to setOf("P", "PANNE", "POMPE", "FORAGE"),
        'L' to setOf("L", "LATRINE", "LATRINES", "WC", "TOILETTE", "TOILETTES"),
        'E' to setOf("E", "EAU", "QUALITE", "TROUBLE", "SALE"),
        'H' to setOf("H", "HYGIENE", "SAVON", "LAVAGE"),
    )

    val TYPE_LABELS = mapOf('P' to "panne pompe/forage", 'L' to "latrine", 'E' to "eau/qualité", 'H' to "hygiène")

    const val HELP = "Envoyez: WASH CODE TYPE. Ex: WASH DOU-BON-001 P (P=panne, L=latrine, E=eau, H=hygiene)."

    /** Aligné sur MESH_SMS_QUOTA_PER_SENDER (défaut backend 10). */
    const val DEFAULT_QUOTA = 10

    private val CODE_RE = Regex("[A-Z0-9][A-Z0-9\\-]{0,30}[A-Z0-9]|[A-Z0-9]{1,2}")

    data class Parsed(
        val ok: Boolean,
        val code: String?,
        val type: Char?,
        val detail: String?,
        val error: String?,
    )

    /** Grammaire : WASH <CODE_ECOLE> <TYPE> [DETAIL]. L'existence de l'école est vérifiée serveur. */
    fun parse(raw: String): Parsed {
        val fail = { error: String -> Parsed(false, null, null, null, error) }
        val tokens = raw.trim().split(Regex("\\s+"))
            .filter { it.isNotEmpty() }
            .map { asciiUpper(it) }
        if (tokens.size < 3) return fail(HELP)
        if (tokens[0] !in KEYWORDS) return fail(HELP)
        if (!CODE_RE.matches(tokens[1])) return fail("Code ecole '${tokens[1]}' invalide. $HELP")
        val type = matchType(tokens[2]) ?: return fail("Type '${tokens[2]}' inconnu (P, L, E ou H). $HELP")
        val detail = tokens.drop(3).joinToString(" ").take(100)
        return Parsed(true, tokens[1], type, detail.ifEmpty { null }, null)
    }

    /** Allowlist CSV exacte (backend : in_array strict) ; vide = tout le monde accepté. */
    fun isAllowlisted(from: String, allowlistCsv: String): Boolean {
        val list = allowlistCsv.split(",").map { it.trim() }.filter { it.isNotEmpty() }
        if (list.isEmpty()) return true
        return from in list
    }

    /** Quota journalier par expéditeur : [sentToday] déjà transférés aujourd'hui. */
    fun quotaExceeded(sentToday: Int, quota: Int = DEFAULT_QUOTA): Boolean = sentToday >= quota

    private fun matchType(token: String): Char? =
        TYPES.entries.firstOrNull { token in it.value }?.key

    /** Majuscules + suppression des accents (équivalent de Str::ascii du backend). */
    fun asciiUpper(s: String): String {
        val decomposed = Normalizer.normalize(s.uppercase(), Normalizer.Form.NFD)
        return decomposed.replace(Regex("\\p{Mn}+"), "")
    }
}

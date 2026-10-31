package cm.wash.mesh

import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import java.util.UUID

/**
 * Protocole bundle v1.1 — miroir exact de mesh/sdk/mesh-sdk.ts :
 * mêmes champs, même JSON canonique (clés triées, compact, UTF-8 brut),
 * même Spray-and-Wait binaire. Le relai FastAPI vérifie le checksum
 * avec la même forme canonique.
 */
object MeshProtocol {
    const val SERVICE_ID = "cm.wash.mesh.v1"
    const val DESTINATION = "dtn://wash-sentinel/ingest"
    const val DEFAULT_COPIES = 8
    const val DEFAULT_MAX_HOPS = 10
    const val TTL_DAYS = 7L

    fun newNodeId(): String = "node-" + UUID.randomUUID().toString().take(8)

    fun newBundle(
        schoolId: Int,
        schoolCode: String?,
        message: String,
        originNode: String,
        copies: Int = DEFAULT_COPIES,
    ): JSONObject {
        val now = Instant.now()
        val b = JSONObject()
            .put("v", 1)
            .put("bundle_id", UUID.randomUUID().toString())
            .put("origin_node_id", originNode)
            .put("school_id", schoolId)
            .put("channel", "text")
            .put("message", message)
            .put("created_at", now.toString())
            .put("expires_at", now.plusSeconds(TTL_DAYS * 86400).toString())
            .put("max_hops", DEFAULT_MAX_HOPS)
            .put("hops", JSONArray().put(originNode))
            .put("destination", DESTINATION)
            .put("lifetime_seconds", TTL_DAYS * 86400)
            .put("copies_remaining", copies)
            .put("priority", "normal")
        if (schoolCode != null) b.put("school_code", schoolCode)
        b.put("checksum", sha256Hex(canonical(b)))
        return b
    }

    private val mutableFields = setOf("checksum", "hops", "previous_node", "copies_remaining")

    /** JSON canonique : clés triées hors champs mutables, compact, UTF-8 brut. */
    fun canonical(bundle: JSONObject): String {
        val keys = mutableListOf<String>()
        val it = bundle.keys()
        while (it.hasNext()) {
            val k = it.next()
            if (k !in mutableFields) keys.add(k)
        }
        keys.sort()
        return keys.joinToString(",", "{", "}") { k ->
            JSONObject.quote(k) + ":" + valueOf(bundle.get(k))
        }
    }

    private fun valueOf(v: Any?): String = when (v) {
        null, JSONObject.NULL -> "null"
        is String -> JSONObject.quote(v)
        is Boolean, is Number -> v.toString()
        is JSONObject -> canonical(v)
        is JSONArray -> (0 until v.length()).joinToString(",", "[", "]") { valueOf(v.get(it)) }
        else -> JSONObject.quote(v.toString())
    }

    fun sha256Hex(raw: String): String =
        MessageDigest.getInstance("SHA-256")
            .digest(raw.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }

    data class Forward(val give: JSONObject, val keepCopies: Int)

    /**
     * Spray-and-Wait binaire : donne floor(n/2), garde ceil(n/2).
     * null = ne pas relayer (boucle, TTL, hops, ou dernière copie
     * réservée à la livraison directe au serveur).
     */
    fun forward(bundle: JSONObject, myNode: String): Forward? {
        val hops = bundle.optJSONArray("hops") ?: JSONArray()
        for (i in 0 until hops.length()) {
            if (hops.optString(i) == myNode) return null
        }
        val expires = runCatching { Instant.parse(bundle.getString("expires_at")) }.getOrNull()
            ?: return null
        if (!expires.isAfter(Instant.now())) return null
        if (hops.length() >= bundle.optInt("max_hops", DEFAULT_MAX_HOPS) + 1) return null
        val copies = bundle.optInt("copies_remaining", DEFAULT_COPIES)
        if (copies <= 1) return null
        val give = JSONObject(bundle.toString())
        val newHops = JSONArray()
        for (i in 0 until hops.length()) newHops.put(hops.get(i))
        newHops.put(myNode)
        give.put("hops", newHops)
        give.put("previous_node", hops.optString(hops.length() - 1))
        give.put("copies_remaining", copies / 2)
        return Forward(give, (copies + 1) / 2)
    }

    /** Vérifie le checksum quand il est présent (v1 : absent = accepté, cf. canal SMS). */
    fun verify(bundle: JSONObject): Boolean {
        if (bundle.isNull("checksum")) return true
        return bundle.optString("checksum") == sha256Hex(canonical(bundle))
    }

    fun requiredFieldsOk(bundle: JSONObject): Boolean =
        !bundle.isNull("bundle_id") && !bundle.isNull("origin_node_id") && !bundle.isNull("school_id")

    fun toQr(bundle: JSONObject): String =
        Base64.getUrlEncoder().withoutPadding()
            .encodeToString(bundle.toString().toByteArray(Charsets.UTF_8))

    fun fromQr(payload: String): JSONObject? = runCatching {
        JSONObject(String(Base64.getUrlDecoder().decode(payload.trim()), Charsets.UTF_8))
    }.getOrNull()
}

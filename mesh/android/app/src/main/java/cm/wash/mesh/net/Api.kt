package cm.wash.mesh.net

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Client HTTP minimal (HttpURLConnection, zéro dépendance) vers
 * le relai mesh (/v1/sync) et Laravel (/api/v1/mesh/...).
 * À appeler hors du thread UI (Coroutines IO / Worker).
 */
object Api {
    class ApiError(val code: Int, message: String) : Exception("HTTP $code: $message")

    data class SyncResult(val sent: Int, val received: List<JSONObject>)
    data class UploadResult(val accepted: Int, val duplicates: Int, val doneIds: List<String>)

    private fun post(url: String, body: JSONObject, meshKey: String = ""): JSONObject {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15000
            readTimeout = 30000
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Accept", "application/json")
            if (meshKey.isNotEmpty()) setRequestProperty("X-Mesh-Key", meshKey)
        }
        try {
            conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = runCatching { stream.bufferedReader().readText() }.getOrDefault("")
            val json = runCatching { JSONObject(text) }.getOrNull() ?: JSONObject()
            if (code !in 200..299) throw ApiError(code, json.optString("message", text.take(200)))
            return json
        } finally {
            conn.disconnect()
        }
    }

    /** Échange opportuniste avec le relai : je donne mon outbox, je prends ce qui me manque. */
    fun relaySync(
        relayUrl: String,
        nodeId: String,
        bundles: List<JSONObject>,
        knownIds: List<String>,
        meshKey: String = "",
    ): SyncResult {
        val arr = JSONArray()
        bundles.forEach { arr.put(it) }
        val ids = JSONArray()
        knownIds.forEach { ids.put(it) }
        val json = post(
            "$relayUrl/v1/sync",
            JSONObject().put("node_id", nodeId).put("bundles", arr).put("known_ids", ids),
            meshKey,
        )
        val received = mutableListOf<JSONObject>()
        val inArr = json.optJSONArray("bundles") ?: JSONArray()
        for (i in 0 until inArr.length()) received.add(inArr.getJSONObject(i))
        return SyncResult(json.optInt("stored", 0), received)
    }

    /** Upload final vers Laravel. Idempotent : doublons = déjà stockés. */
    fun laravelUpload(apiUrl: String, bundles: List<JSONObject>, meshKey: String = ""): UploadResult {
        val arr = JSONArray()
        bundles.forEach { b ->
            arr.put(
                JSONObject()
                    .put("bundle_id", b.getString("bundle_id"))
                    .put("origin_node_id", b.getString("origin_node_id"))
                    .put("school_id", b.getInt("school_id"))
                    .put("school_code", b.optString("school_code", null))
                    .put("message", b.optString("message", null))
                    .put("channel", b.optString("channel", "text"))
                    .put("hops", b.optJSONArray("hops") ?: JSONArray())
                    .put("max_hops", b.optInt("max_hops", 10))
                    .put("expires_at", b.optString("expires_at", null))
                    .put("checksum", b.optString("checksum", null))
                    .put("destination_eid", b.optString("destination", null))
                    .put("report_to_eid", b.optString("report_to", null))
                    .put("lifetime_seconds", if (b.isNull("lifetime_seconds")) null else b.optLong("lifetime_seconds"))
                    .put("previous_node_id", b.optString("previous_node", null))
                    .put("copies_remaining", b.optInt("copies_remaining", 8))
                    .put("custody_requested", b.optBoolean("custody_requested", false))
                    .put("priority", b.optString("priority", "normal"))
                    .put("signature", b.optString("signature", null)),
            )
        }
        val json = post("$apiUrl/v1/mesh/bundles", JSONObject().put("bundles", arr), meshKey)
        val summary = json.optJSONObject("summary") ?: JSONObject()
        val accepted = summary.optInt("accepted", 0)
        val duplicates = summary.optInt("duplicates", 0)
        val sentIds = bundles.map { it.getString("bundle_id") }
        val doneIds = mutableListOf<String>()
        val incidents = json.optJSONArray("incidents") ?: JSONArray()
        for (i in 0 until incidents.length()) {
            doneIds.add(incidents.getJSONObject(i).getString("bundle_id"))
        }
        // Lot entièrement comptabilisé (acceptés + doublons) = tout est au serveur.
        if (accepted + duplicates == bundles.size) return UploadResult(accepted, duplicates, sentIds)
        return UploadResult(accepted, duplicates, doneIds)
    }

    /** Remontée d'un SMS via la passerelle (mot-clé WASH parsé côté serveur). */
    fun smsPost(apiUrl: String, secret: String, from: String, message: String, sentAtIso: String?): JSONObject =
        post(
            "$apiUrl/v1/mesh/sms",
            JSONObject()
                .put("secret", secret)
                .put("from", from)
                .put("message", message)
                .put("sent_at", sentAtIso),
        )
}

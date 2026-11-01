/* ============================================================================
 * Cache TTS Sentinel — une synthèse par (texte, voix, langue), réécoutée sans
 * réseau. LRU borné (TTS_CACHE_CAPACITY entrées) avec révocation à l'éviction : les URL sont
 * la propriété du cache, l'appelant ne doit JAMAIS les révoquer.
 *
 * Seul le TTS est caché. Jamais le STT : les transcriptions alimentent le
 * triage, une mise en cache risquerait de faux incidents sur audio rassis.
 * ========================================================================== */

/** Nombre maximal d'audios gardés en mémoire. */
export const TTS_CACHE_CAPACITY = 20;

/** Langue par défaut de la clé de cache (miroir de wash.php `voice.default_language`). */
const TTS_DEFAULT_LANGUAGE = 'fr';
/** Voix par défaut de la clé de cache (étiquette locale, jamais envoyée). */
const TTS_DEFAULT_VOICE_KEY = 'default';

export interface TtsCacheOpts {
  voice?: string;
  language?: string;
}

export interface TtsAudioPayload {
  audio_base64: string;
  mime_type: string;
}

const cache = new Map<string, string>();

/** Clé stable pour (texte, voix, langue). */
export function ttsCacheKey(text: string, opts?: TtsCacheOpts): string {
  return `${opts?.language ?? TTS_DEFAULT_LANGUAGE}|${opts?.voice ?? TTS_DEFAULT_VOICE_KEY}|${text}`;
}

/** URL cachée si présente (rafraîchit le rang LRU), sinon undefined. */
export function getCachedTtsUrl(key: string): string | undefined {
  const found = cache.get(key);
  if (found !== undefined) {
    cache.delete(key);
    cache.set(key, found);
  }
  return found;
}

function storeTtsUrl(key: string, url: string): void {
  if (cache.has(key)) cache.delete(key);
  cache.set(key, url);
  while (cache.size > TTS_CACHE_CAPACITY) {
    const oldest = cache.keys().next();
    if (oldest.done === true) break;
    const evicted = cache.get(oldest.value);
    cache.delete(oldest.value);
    if (evicted !== undefined) URL.revokeObjectURL(evicted);
  }
}

function base64ToObjectUrl(audioBase64: string, mimeType: string): string {
  const bin = atob(audioBase64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes.buffer as ArrayBuffer], { type: mimeType }));
}

/**
 * URL lisible pour un texte : cache puis synthèse à la demande via fetchAudio.
 * Retourne null si la synthèse échoue. L'URL retournée appartient au cache :
 * ne pas la révoquer, elle survit aux allers-retours de lecture.
 */
export async function getSynthesizedUrl(
  text: string,
  opts: TtsCacheOpts | undefined,
  fetchAudio: () => Promise<TtsAudioPayload | null>,
): Promise<string | null> {
  const key = ttsCacheKey(text, opts);
  const hit = getCachedTtsUrl(key);
  if (hit !== undefined) return hit;
  let payload: TtsAudioPayload | null;
  try {
    payload = await fetchAudio();
  } catch {
    return null;
  }
  if (payload === null || payload.audio_base64 === '') return null;
  const url = base64ToObjectUrl(payload.audio_base64, payload.mime_type);
  storeTtsUrl(key, url);
  return url;
}

/** Vide le cache (tests, déconnexion) en révoquant toutes les URL. */
export function clearTtsCache(): void {
  for (const url of cache.values()) URL.revokeObjectURL(url);
  cache.clear();
}

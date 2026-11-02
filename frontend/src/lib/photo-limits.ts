/* ============================================================================
 * Limites photo du chat Sentinel — source unique (chaînon manquant :
 * voice-limits.ts ne couvre que l'audio).
 *
 * MIROIR BACKEND (ne pas modifier sans synchroniser) :
 * CHAT_PHOTO_MAX_BYTES = 10 Mo ↔ wash.php `photo.max_kb` (10240 Ko)
 *   ↔ WashReportController::PHOTO_MAX_KB (plafond unique réutilisé).
 * CHAT_PHOTO_MIMES ↔ wash.php `photo.mimes` (validation converse.image).
 * ========================================================================== */

/** Poids maximal d'une photo de chat acceptée (10 Mo, miroir Laravel). */
export const CHAT_PHOTO_MAX_BYTES = 10 * 1024 * 1024;

/** Types MIME photo acceptés par le chat (miroir de la validation Laravel). */
export const CHAT_PHOTO_MIMES = ['image/jpeg', 'image/png', 'image/webp'] as const;

export type ChatPhotoMime = (typeof CHAT_PHOTO_MIMES)[number];

/** Valeur de l'attribut `accept` de l'input fichier photo. */
export const CHAT_PHOTO_ACCEPT = CHAT_PHOTO_MIMES.join(',');

export function isChatPhotoMime(mime: string): mime is ChatPhotoMime {
  return (CHAT_PHOTO_MIMES as readonly string[]).includes(mime);
}

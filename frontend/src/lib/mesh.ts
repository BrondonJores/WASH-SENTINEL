// Pont PWA <-> protocole mesh : réexporte le SDK + helpers terrain (iOS, SMS, cache écoles).
import {
  MEDIA_MAX_BYTES,
  createBundle as sdkCreateBundle,
  MeshOutbox,
  nodeId,
  parseFromQR,
  serializeForQR,
  splitMedia,
  uploadToLaravel,
} from './mesh-sdk';
import type { MeshBundle } from './mesh-sdk';
import type { School } from './api';
import { registerMeshSync } from './mesh-sync';
import { API_URL } from './api';

export {
  MEDIA_MAX_BYTES,
  MeshOutbox,
  nodeId,
  parseFromQR,
  serializeForQR,
  splitMedia,
  uploadToLaravel,
};
export type { MeshBundle };
export const createBundle = sdkCreateBundle;

/** Base URL API partagée (voir API_URL dans lib/api — fail-fast en prod). */
export const apiBase = (): string => API_URL;

export const smsGateway = (): string =>
  (import.meta.env.VITE_SMS_GATEWAY_NUMBER as string | undefined) ?? '';

export const isIOS = (): boolean =>
  /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

/** Lien sms: pré-rempli (?body= Android, &body= iOS). */
export function smsHref(to: string, body: string): string {
  const sep = isIOS() ? '&' : '?';
  return `sms:${to}${sep}body=${encodeURIComponent(body)}`;
}

/**
 * CONTRAT GSM — miroirs de MeshSmsParser.php (ne pas modifier sans synchroniser) :
 * - SMS_DETAIL_MAX_CHARS = 100 ↔ DETAIL_MAX_LENGTH
 * - SMS_SINGLE_SEGMENT_MAX_CHARS = 160 ↔ 1 segment GSM 7-bit (cf. ACK_MAX_LENGTH)
 */
export const SMS_DETAIL_MAX_CHARS = 100;
export const SMS_SINGLE_SEGMENT_MAX_CHARS = 160;

/** Grammaire SMS commune : WASH <CODE> <TYPE> [détail], 1 segment. */
export function smsText(schoolCode: string, type: string, detail: string): string {
  const detailPart = detail.trim().slice(0, SMS_DETAIL_MAX_CHARS).toUpperCase();
  return `WASH ${schoolCode} ${type}${detailPart ? ` ${detailPart}` : ''}`.slice(0, SMS_SINGLE_SEGMENT_MAX_CHARS);
}

/** Cache local des écoles : la saisie reste possible offline dès la 2e visite. */
const SCHOOL_CACHE_KEY = 'wash_mesh_schools';
/** Nombre max d'écoles gardées dans le cache local (valeur front seule, aucun miroir backend). */
export const SCHOOL_CACHE_MAX = 300;

export function cacheSchools(schools: School[]): void {
  try {
    localStorage.setItem(SCHOOL_CACHE_KEY, JSON.stringify(schools.slice(0, SCHOOL_CACHE_MAX)));
  } catch {
    /* quota dépassé : on garde l'ancien cache */
  }
}

export function cachedSchools(): School[] {
  try {
    const raw = JSON.parse(localStorage.getItem(SCHOOL_CACHE_KEY) ?? '[]') as School[];
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

/**
 * Ajout outbox + demande de Background Sync best-effort (voir mesh-sync).
 * À utiliser pour chaque ajout : création locale comme réception QR.
 */
export function outboxAdd(outbox: MeshOutbox, bundle: MeshBundle): boolean {
  const added = outbox.add(bundle);
  if (added) void registerMeshSync();
  return added;
}

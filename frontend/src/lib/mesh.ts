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

export const apiBase = (): string =>
  (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost/api';

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

/** Grammaire SMS commune : WASH <CODE> <TYPE> [détail], 1 segment. */
export function smsText(schoolCode: string, type: string, detail: string): string {
  const detailPart = detail.trim().slice(0, 100).toUpperCase();
  return `WASH ${schoolCode} ${type}${detailPart ? ` ${detailPart}` : ''}`.slice(0, 160);
}

/** Cache local des écoles : la saisie reste possible offline dès la 2e visite. */
const SCHOOL_CACHE_KEY = 'wash_mesh_schools';

export function cacheSchools(schools: School[]): void {
  try {
    localStorage.setItem(SCHOOL_CACHE_KEY, JSON.stringify(schools.slice(0, 300)));
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

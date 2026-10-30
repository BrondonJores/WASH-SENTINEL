export const STATUS_FR: Record<string, string> = {
  reported: 'Signalé',
  triaged: 'Trié',
  assigned: 'Assigné',
  in_progress: 'En cours',
  resolved: 'Résolu',
  closed: 'Clôturé',
};

export const URGENCY_FR: Record<string, string> = {
  low: 'Basse',
  medium: 'Moyenne',
  high: 'Haute',
  critical: 'Critique',
};

export const CATEGORY_FR: Record<string, string> = {
  water_point: "Point d'eau",
  toilets_latrines: 'Toilettes / latrines',
  handwashing: 'Lavage des mains',
  sewage_drainage: 'Évacuation / drainage',
};

export const CHANNEL_FR: Record<string, string> = {
  voice: 'Vocal',
  text: 'Texte',
  photo: 'Photo',
  webrtc_call: 'Appel',
};

export type Tone = 'neutral' | 'accent' | 'success' | 'warn' | 'danger' | 'info';

export const urgencyTone = (u: string): Tone =>
  u === 'critical' ? 'danger' : u === 'high' ? 'warn' : u === 'medium' ? 'info' : 'neutral';

export const statusTone = (s: string): Tone =>
  s === 'resolved' || s === 'closed'
    ? 'success'
    : s === 'in_progress'
      ? 'info'
      : s === 'reported'
        ? 'warn'
        : 'neutral';

export const fmtDate = (iso: string | null): string =>
  iso
    ? new Date(iso).toLocaleString('fr-FR', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—';

export const fmtNum = (n: number | null | undefined): string =>
  new Intl.NumberFormat('fr-FR').format(n ?? 0);

export const INPUT_CLS =
  'w-full rounded-md border border-line bg-card px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none';

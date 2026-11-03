import type { IconName } from './components/icons';
import { pick } from './lib/i18n';

export interface NavItem {
  path: string;
  /** Libellé FR (défaut). */
  label: string;
  /** Libellé EN (repli sur `label` si absent). */
  labelEn?: string;
  icon: IconName;
  adminOnly?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { path: '/', label: 'Sentinel', labelEn: 'Sentinel', icon: 'chat' },
  { path: '/admin/incidents', label: 'Interventions', labelEn: 'Interventions', icon: 'alert' },
  { path: '/admin/ecoles', label: 'Écoles', labelEn: 'Schools', icon: 'school' },
  { path: '/admin/equipes', label: 'Équipes', labelEn: 'Teams', icon: 'user' },
  { path: '/admin/signalements', label: 'Signalements', labelEn: 'Reports', icon: 'inbox' },
  { path: '/admin/journal', label: 'Journal IA', labelEn: 'AI journal', icon: 'file', adminOnly: true },
  { path: '/admin/notifications', label: 'Notifications', labelEn: 'Notifications', icon: 'bell' },
  { path: '/admin/mesh', label: 'Maillage', labelEn: 'Mesh', icon: 'send' },
  { path: '/admin/reglages', label: 'Réglages IA', labelEn: 'AI settings', icon: 'sliders', adminOnly: true },
];

/** Libellé de navigation selon la langue UI. */
export const navLabel = (ui: string | undefined, item: NavItem): string =>
  pick(ui, item.label, item.labelEn ?? item.label);

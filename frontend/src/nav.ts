import type { IconName } from './components/icons';

export interface NavItem {
  path: string;
  label: string;
  icon: IconName;
  adminOnly?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { path: '/', label: 'Sentinel', icon: 'chat' },
  { path: '/admin/incidents', label: 'Interventions', icon: 'alert' },
  { path: '/admin/ecoles', label: 'Écoles', icon: 'school' },
  { path: '/admin/signalements', label: 'Signalements', icon: 'inbox' },
  { path: '/admin/journal', label: 'Journal IA', icon: 'file', adminOnly: true },
  { path: '/admin/notifications', label: 'Notifications', icon: 'bell' },
  { path: '/admin/reglages', label: 'Réglages IA', icon: 'sliders', adminOnly: true },
];

// Prompt d'installation PWA in-app.
//
// Android/desktop (Chromium) : `beforeinstallprompt` → bouton « Installer ».
// iPhone (Safari) : pas de prompt système → carte d'aide « Ajouter à l'écran
// d'accueil » avec les gestes iOS, en français.

import { useCallback, useEffect, useState } from 'react';

/** Pure (testable en node) : détection iPhone/iPad, y compris iPad desktop. */
export function isIOSDevice(userAgent: string, platform: string, maxTouchPoints: number): boolean {
  return (
    /iPad|iPhone|iPod/.test(userAgent) || (platform === 'MacIntel' && maxTouchPoints > 1)
  );
}

export function currentIsIOSDevice(): boolean {
  return isIOSDevice(navigator.userAgent, navigator.platform, navigator.maxTouchPoints);
}

/** L'app tourne-t-elle déjà installée (standalone) ? */
export function isStandaloneDisplay(): boolean {
  if (typeof window === 'undefined') return false;
  if (window.matchMedia?.('(display-mode: standalone)').matches) return true;
  return (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

export interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

export function isBeforeInstallPromptEvent(ev: Event): ev is BeforeInstallPromptEvent {
  return 'prompt' in ev && 'userChoice' in ev;
}

export interface InstallPrompt {
  /** Le navigateur propose l'installation (événement capturé). */
  canInstall: boolean;
  /** Affiche le prompt système. Retourne true si l'utilisateur accepte. */
  install: () => Promise<boolean>;
  /** Masque le bouton pour cette session (l'événement reste rejouable). */
  dismiss: () => void;
  dismissed: boolean;
}

export function useInstallPrompt(): InstallPrompt {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const onBeforeInstall = (ev: Event) => {
      if (!isBeforeInstallPromptEvent(ev)) return;
      ev.preventDefault();
      setDeferred(ev);
    };
    const onInstalled = () => {
      setDeferred(null);
      setDismissed(false);
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  const install = useCallback(async (): Promise<boolean> => {
    if (!deferred) return false;
    await deferred.prompt();
    const choice = await deferred.userChoice;
    setDeferred(null);
    return choice.outcome === 'accepted';
  }, [deferred]);

  const dismiss = useCallback(() => setDismissed(true), []);

  return { canInstall: deferred !== null && !dismissed, install, dismiss, dismissed };
}

const IOS_HELP_KEY = 'wash_mesh_ios_help_dismissed';

export function iosHelpDismissed(): boolean {
  try {
    return localStorage.getItem(IOS_HELP_KEY) === '1';
  } catch {
    return false;
  }
}

export function dismissIosHelp(): void {
  try {
    localStorage.setItem(IOS_HELP_KEY, '1');
  } catch {
    /* stockage indisponible : l'aide reviendra, sans gravité */
  }
}

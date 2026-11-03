import { api } from './api';

/** Traduction d'affichage des données terrain (titres, résumés saisis).
 *
 * Un seul POST par tick de rendu : les demandes simultanées des cartes
 * sont groupées (dédoublonnées, découpées par 20) puis ventilées.
 * Cache mémoire + repli sûr : l'original en cas d'échec (jamais de vide).
 */

const cache = new Map<string, string>();

interface Waiter {
  text: string;
  target: string;
  resolve: (value: string) => void;
}

let queue: Waiter[] = [];
let scheduled = false;

const keyOf = (text: string, target: string): string => `${target}\n${text}`;

function flush(): void {
  scheduled = false;
  const batch = queue;
  queue = [];
  const pending = batch.filter((w) => {
    const hit = cache.get(keyOf(w.text, w.target));
    if (hit !== undefined) {
      w.resolve(hit);
      return false;
    }
    return true;
  });
  if (pending.length === 0) return;
  const byTarget = new Map<string, Waiter[]>();
  for (const w of pending) {
    const list = byTarget.get(w.target) ?? [];
    list.push(w);
    byTarget.set(w.target, list);
  }
  for (const [target, waiters] of byTarget) {
    const uniq: string[] = [];
    const seen = new Set<string>();
    for (const w of waiters) {
      if (!seen.has(w.text)) {
        seen.add(w.text);
        uniq.push(w.text);
      }
    }
    const chunks: string[][] = [];
    for (let i = 0; i < uniq.length; i += 20) chunks.push(uniq.slice(i, i + 20));
    void Promise.all(
      chunks.map((texts) =>
        api
          .translateFieldTexts(texts, target)
          .then((res) => {
            texts.forEach((t, i) => {
              const tr = res.translations[i];
              cache.set(keyOf(t, target), typeof tr === 'string' && tr !== '' ? tr : t);
            });
          })
          .catch(() => {
            texts.forEach((t) => cache.set(keyOf(t, target), t));
          }),
      ),
    ).then(() => {
      for (const w of waiters) w.resolve(cache.get(keyOf(w.text, w.target)) ?? w.text);
    });
  }
}

/** Traduit un libellé terrain (groupé, caché, repli original). */
export function translateFieldText(text: string, target: string): Promise<string> {
  const hit = cache.get(keyOf(text, target));
  if (hit !== undefined) return Promise.resolve(hit);
  return new Promise<string>((resolve) => {
    queue.push({ text, target, resolve });
    if (!scheduled) {
      scheduled = true;
      setTimeout(flush, 0);
    }
  });
}

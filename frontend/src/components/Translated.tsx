import { useEffect, useState } from 'react';
import { translateFieldText } from '../lib/translate';

/** Libellé terrain traduit quand la réponse est EN (original sinon).
 *
 * Affiche l'original pendant le chargement (pas de flash), puis la
 * traduction avec l'original en infobulle (honnêteté du témoignage).
 * Noms d'écoles et références : ne jamais passer ici (noms propres).
 */
export function Translated({ text, lang }: { text: string; lang?: string }) {
  const [extra, setExtra] = useState<{ forText: string; shown: string } | null>(null);
  const shown = extra !== null && extra.forText === text && lang === 'en' ? extra.shown : text;
  useEffect(() => {
    if (lang !== 'en' || text.trim() === '' || text === '—') return;
    let live = true;
    translateFieldText(text, 'en').then((t) => {
      if (live) setExtra({ forText: text, shown: t });
    });
    return () => {
      live = false;
    };
  }, [text, lang]);
  if (lang !== 'en' || shown === text) return <>{text}</>;
  return <span title={text}>{shown}</span>;
}

import type { ReactNode } from 'react';
import { Badge, Button, Card } from './ui';
import { GuideEmpty } from './GuideEmpty';
import { Icon } from './icons';

// ---------- Helpers défensifs (contrat moteur) ----------

const asRecord = (v: unknown): Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : {};

const asArray = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

const fmtOpt = (v: unknown): string | undefined =>
  typeof v === 'string' && v !== '' ? v : undefined;

/** Ne garde que les URLs absolues http(s) ouvrables au navigateur. */
const httpUrl = (v: unknown): string | undefined =>
  typeof v === 'string' && (v.startsWith('http://') || v.startsWith('https://')) ? v : undefined;

/** Téléchargement simple : lien temporaire, repli navigateur si cross-origin. */
function downloadUrl(url: string, fileName: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ---------- Mini Markdown (sections du rapport, sans dépendance) ----------

/** Rend le gras **...** d'une ligne. */
function mdInline(text: string, keyPrefix: string): ReactNode {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  if (parts.length === 1) return text;
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <strong key={`${keyPrefix}-b${i}`}>{p}</strong>
        ) : (
          <span key={`${keyPrefix}-t${i}`}>{p}</span>
        ),
      )}
    </>
  );
}

/** Paragraphes, listes « - » et titres « # » ; le reste passe en texte. */
function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let n = 0;
  const flushList = (): void => {
    if (list.length === 0) return;
    const items = list;
    list = [];
    n += 1;
    blocks.push(
      <ul key={`ul-${n}`} className="mb-3 list-disc space-y-1 pl-5 text-sm leading-relaxed">
        {items.map((item, i) => (
          <li key={`li-${i}`}>{mdInline(item, `li-${n}-${i}`)}</li>
        ))}
      </ul>,
    );
  };
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    const bullet = /^(?:[-*]|\d+[.)])\s+(.+)$/.exec(line);
    if (bullet !== null) {
      list.push(bullet[1]);
      continue;
    }
    flushList();
    if (line === '') continue;
    n += 1;
    const heading = /^#{1,3}\s+(.+)$/.exec(line);
    if (heading !== null) {
      blocks.push(
        <h5 key={`h-${n}`} className="mb-1.5 mt-3 text-sm font-bold">
          {mdInline(heading[1], `h-${n}`)}
        </h5>,
      );
    } else {
      blocks.push(
        <p key={`p-${n}`} className="mb-2.5 text-sm leading-relaxed">
          {mdInline(line, `p-${n}`)}
        </p>,
      );
    }
  }
  flushList();
  if (blocks.length === 0) return null;
  return <>{blocks}</>;
}

// ---------- Carte affiche ----------

export function PosterCard({
  title,
  data,
  onAsk,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const imageUrl = httpUrl(data.image_url);
  const caption = fmtOpt(data.caption);
  const note = fmtOpt(data.note);
  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-x-3 gap-y-2 border-b border-stone-200/80 pb-3 dark:border-white/[0.07]">
        <h3 className="font-display text-[17px] font-bold leading-snug tracking-tight">{title}</h3>
        {caption !== undefined && (
          <span className="text-xs text-stone-500 dark:text-stone-400">{caption}</span>
        )}
      </div>
      {imageUrl === undefined ? (
        <GuideEmpty
          phrase="Affiche indisponible pour le moment."
          conseil={note ?? "L'image n'a pas pu être préparée : demandez une nouvelle affiche."}
          actions={[{ label: 'Demander une affiche', question: 'Génère une affiche pour ce dossier' }]}
          onAsk={onAsk}
        />
      ) : (
        <>
          <a
            href={imageUrl}
            target="_blank"
            rel="noreferrer"
            aria-label={`Ouvrir l'affiche ${caption ?? title} dans un nouvel onglet`}
            className="block overflow-hidden rounded-xl border border-line transition-[border-color] duration-150 ease-snap hover:border-accent"
          >
            <img
              src={imageUrl}
              alt={caption ?? title}
              loading="lazy"
              className="max-h-[420px] w-full object-contain bg-stone-100 dark:bg-stone-900"
            />
          </a>
          {caption !== undefined && (
            <p className="mt-2 text-center text-[13px] text-stone-500 dark:text-stone-400">{caption}</p>
          )}
          {note !== undefined && (
            <p className="mt-2 text-[13px] leading-relaxed text-stone-500 dark:text-stone-400">{note}</p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => downloadUrl(imageUrl, 'affiche.png')}>
              <Icon name="file" className="h-3.5 w-3.5" />
              Télécharger
            </Button>
            <Button size="sm" onClick={() => window.open(imageUrl, '_blank', 'noopener')}>
              Ouvrir dans un nouvel onglet
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}

// ---------- Rapport du dossier ----------

/** CSS d'impression minimale : seule la carte rapport s'imprime, sans boutons. */
const PRINT_CSS = `
@media print {
  body * { visibility: hidden; }
  .dossier-print, .dossier-print * { visibility: visible; }
  .dossier-print { position: absolute; inset: 0; width: 100%; border: none !important; box-shadow: none !important; }
  .no-print { display: none !important; }
}
`;

interface DossierFigure {
  url: string;
  caption?: string;
}

/** Figures : chaînes URL ou objets {url, caption} ; le reste est ignoré. */
const asFigures = (v: unknown): DossierFigure[] => {
  const out: DossierFigure[] = [];
  for (const entry of asArray<unknown>(v)) {
    if (typeof entry === 'string') {
      const url = httpUrl(entry);
      if (url !== undefined) out.push({ url });
      continue;
    }
    const r = asRecord(entry);
    const url = httpUrl(r.url);
    if (url !== undefined) {
      out.push({
        url,
        ...(typeof r.caption === 'string' && r.caption !== '' ? { caption: r.caption } : {}),
      });
    }
  }
  return out;
};

export function DossierView({
  title,
  data,
  onAsk,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const subject = fmtOpt(data.subject);
  const period = fmtOpt(data.period);
  const sections = asArray<unknown>(data.sections);
  const posterUrl = httpUrl(data.poster_url ?? data.posterUrl);
  const note = fmtOpt(data.note);
  return (
    <Card className="dossier-print p-4 sm:p-5">
      <style>{PRINT_CSS}</style>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-x-3 gap-y-2 border-b border-stone-200/80 pb-3 dark:border-white/[0.07]">
        <h3 className="font-display text-[17px] font-bold leading-snug tracking-tight">{title}</h3>
        <div className="flex flex-wrap items-center gap-1.5">
          {subject !== undefined && <Badge>{subject}</Badge>}
          {period !== undefined && <Badge>{period}</Badge>}
        </div>
      </div>
      <div className="no-print mb-4 flex flex-wrap gap-2">
        <Button size="sm" variant="primary" onClick={() => window.print()}>
          Imprimer le rapport
        </Button>
        {posterUrl !== undefined && (
          <Button size="sm" onClick={() => downloadUrl(posterUrl, 'affiche.png')}>
            <Icon name="file" className="h-3.5 w-3.5" />
            Télécharger l&apos;affiche
          </Button>
        )}
      </div>
      {note !== undefined && (
        <p className="mb-3 text-sm leading-relaxed text-stone-500 dark:text-stone-400">{note}</p>
      )}
      {sections.length === 0 ? (
        <GuideEmpty
          phrase="Rapport vide pour le moment."
          conseil="Le moteur n'a pas renvoyé de sections : précisez le sujet et la période, par exemple « Dossier Mvila, janvier à mars »."
          actions={[{ label: 'Préciser ma demande', question: 'Prépare un dossier décideur : quel sujet et quelle période ?' }]}
          onAsk={onAsk}
        />
      ) : (
        <div className="space-y-5">
          {sections.map((entry, i) => {
            const section = asRecord(entry);
            const heading = fmtOpt(section.heading);
            const body = fmtOpt(section.body_md ?? section.body);
            const figures = asFigures(section.figures);
            return (
              <section key={`section-${i}`}>
                {heading !== undefined && (
                  <h4 className="mb-2 font-display text-[15px] font-bold leading-snug tracking-tight">
                    {heading}
                  </h4>
                )}
                {body !== undefined && <Markdown text={body} />}
                {figures.length > 0 && (
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    {figures.map((fig, j) => (
                      <figure
                        key={`fig-${i}-${j}`}
                        className="overflow-hidden rounded-xl border border-line"
                      >
                        <img
                          src={fig.url}
                          alt={fig.caption ?? `Illustration ${j + 1} de ${heading ?? title}`}
                          loading="lazy"
                          className="max-h-56 w-full object-contain bg-stone-100 dark:bg-stone-900"
                        />
                        {fig.caption !== undefined && (
                          <figcaption className="px-2 py-1.5 text-center text-xs text-stone-500 dark:text-stone-400">
                            {fig.caption}
                          </figcaption>
                        )}
                      </figure>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}
    </Card>
  );
}

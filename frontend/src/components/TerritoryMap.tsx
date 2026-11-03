import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

export interface TerritoryPoint {
  key: string;
  name: string;
  district: string;
  lat: number;
  lng: number;
  openIncidents: number;
  affectedStudents: number;
  topUrgency: string | null;
}

/** Délai de grâce : sans aucune tuile chargée passé ce délai, on bascule hors-ligne. */
export const OFFLINE_GRACE_PERIOD_MS = 4000;
/** Nombre d'erreurs de tuiles suffisant pour basculer hors-ligne sans attendre la grâce. */
export const OFFLINE_TILE_ERROR_THRESHOLD = 3;

export interface OfflineSignals {
  tileErrors: number;
  loadedTiles: number;
  elapsedMs: number;
}

/**
 * Décision pure de bascule hors-ligne (testable sans Leaflet).
 * - Dès qu'au moins une tuile a chargé, on reste en ligne (non-régression).
 * - Sinon, on bascule si le seuil d'erreurs est atteint OU si la grâce est écoulée.
 */
export function shouldGoOffline({ tileErrors, loadedTiles, elapsedMs }: OfflineSignals): boolean {
  if (loadedTiles > 0) return false;
  if (tileErrors >= OFFLINE_TILE_ERROR_THRESHOLD) return true;
  if (elapsedMs >= OFFLINE_GRACE_PERIOD_MS) return true;
  return false;
}

const URGENCY_COLORS: Record<string, string> = {
  critical: '#e11d48',
  high: '#d97706',
  medium: '#0284c7',
  low: '#0d9488',
};

function urgencyColor(urgency: string | null): string {
  if (urgency === null) return '#0d9488';
  return URGENCY_COLORS[urgency] ?? '#0d9488';
}

function FitBounds({ points }: { points: TerritoryPoint[] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    const bounds = points.map((p): [number, number] => [p.lat, p.lng]);
    map.fitBounds(bounds, { padding: [24, 24], maxZoom: 12 });
  }, [map, points]);
  return null;
}

const LEGEND: { key: string; fr: string; en: string }[] = [
  { key: 'critical', fr: 'Critique', en: 'Critical' },
  { key: 'high', fr: 'Haute', en: 'High' },
  { key: 'medium', fr: 'Moyenne', en: 'Medium' },
  { key: 'low', fr: 'Basse / OK', en: 'Low / OK' },
];

export function TerritoryLegend({ lang }: { lang?: string }) {
  const en = lang === 'en';
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1">
      {LEGEND.map((l) => (
        <span key={l.key} className="inline-flex items-center gap-1.5 text-xs text-stone-600 dark:text-stone-400">
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ backgroundColor: urgencyColor(l.key) }}
          />
{en ? l.en : l.fr}
        </span>
      ))}
    </div>
  );
}

/** Quadrillage schématique affiché en fond quand les tuiles sont indisponibles. */
const OFFLINE_GRID_STYLE: CSSProperties = {
  backgroundImage:
    'linear-gradient(to right, rgb(0 0 0 / 0.08) 1px, transparent 1px), linear-gradient(to bottom, rgb(0 0 0 / 0.08) 1px, transparent 1px)',
  backgroundSize: '24px 24px',
};

export function TerritoryMap({ points, lang }: { points: TerritoryPoint[]; lang?: string }) {
  const en = lang === 'en';
  const [isOffline, setIsOffline] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const tileErrorsRef = useRef(0);
  const loadedTilesRef = useRef(0);
  const startTimeRef = useRef(0);

  // Grâce : si aucune tuile n'a chargé après OFFLINE_GRACE_PERIOD_MS, bascule hors-ligne.
  useEffect(() => {
    tileErrorsRef.current = 0;
    loadedTilesRef.current = 0;
    startTimeRef.current = Date.now();
    const timer = window.setTimeout(() => {
      if (
        shouldGoOffline({
          tileErrors: tileErrorsRef.current,
          loadedTiles: loadedTilesRef.current,
          elapsedMs: Date.now() - startTimeRef.current,
        })
      ) {
        setIsOffline(true);
      }
    }, OFFLINE_GRACE_PERIOD_MS);
    return () => window.clearTimeout(timer);
  }, [attempt]);

  const handleTileError = useCallback(() => {
    tileErrorsRef.current += 1;
    const startedAt = startTimeRef.current === 0 ? Date.now() : startTimeRef.current;
    if (
      shouldGoOffline({
        tileErrors: tileErrorsRef.current,
        loadedTiles: loadedTilesRef.current,
        elapsedMs: Date.now() - startedAt,
      })
    ) {
      setIsOffline(true);
    }
  }, []);

  const handleTileLoad = useCallback(() => {
    loadedTilesRef.current += 1;
  }, []);

  const handleRetry = useCallback(() => {
    tileErrorsRef.current = 0;
    loadedTilesRef.current = 0;
    startTimeRef.current = Date.now();
    setIsOffline(false);
    setAttempt((a) => a + 1);
  }, []);

  const center: [number, number] =
    points.length > 0
      ? [
          points.reduce((s, p) => s + p.lat, 0) / points.length,
          points.reduce((s, p) => s + p.lng, 0) / points.length,
        ]
      : [4.05, 9.7];
  return (
    <div className="relative z-0">
      <MapContainer
        key={attempt}
        center={center}
        zoom={6}
        scrollWheelZoom={false}
        className={
          isOffline
            ? 'h-80 w-full rounded-lg bg-stone-200 dark:bg-stone-800'
            : 'h-80 w-full rounded-lg'
        }
        style={isOffline ? OFFLINE_GRID_STYLE : undefined}
      >
        {!isOffline && (
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            eventHandlers={{ tileerror: handleTileError, tileload: handleTileLoad }}
          />
        )}
        {points.map((p) => {
          const color = urgencyColor(p.topUrgency);
          return (
            <CircleMarker
              key={p.key}
              center={[p.lat, p.lng]}
              radius={p.topUrgency === 'critical' ? 11 : 9}
              pathOptions={{ color, fillColor: color, fillOpacity: 0.55, weight: 2 }}
            >
              {isOffline && (
                <Tooltip permanent direction="top" offset={[0, -10]} opacity={1}>
                  {p.name}
                </Tooltip>
              )}
              <Popup>
                <strong>{p.name}</strong>
                <br />
{p.district} · {p.openIncidents} {en ? 'open incident(s)' : 'incident(s) ouvert(s)'} · {p.affectedStudents} {en ? 'pupils' : 'élèves'}
              </Popup>
            </CircleMarker>
          );
        })}
        <FitBounds points={points} />
      </MapContainer>
      {isOffline && (
        <div className="pointer-events-none absolute inset-x-2 bottom-6 z-[1000] flex flex-wrap items-center justify-center gap-2">
          <p
            role="status"
            className="pointer-events-auto rounded-full border border-amber-300 bg-amber-100 px-3 py-1 text-xs font-medium text-amber-900 shadow dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
          >
{en ? 'Offline mode — approximate positions' : 'Mode hors-ligne — positions approximatives'}
          </p>
          <button
            type="button"
            onClick={handleRetry}
            className="pointer-events-auto rounded-full border border-stone-300 bg-white px-3 py-1 text-xs font-medium text-stone-800 shadow transition-colors hover:bg-stone-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-500 motion-reduce:transition-none dark:border-stone-600 dark:bg-stone-900 dark:text-stone-100 dark:hover:bg-stone-800"
          >
{en ? 'Retry' : 'Réessayer'}
          </button>
        </div>
      )}
    </div>
  );
}

import { useEffect } from 'react';
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet';
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

const LEGEND = [
  { key: 'critical', label: 'Critique' },
  { key: 'high', label: 'Haute' },
  { key: 'medium', label: 'Moyenne' },
  { key: 'low', label: 'Basse / OK' },
];

export function TerritoryLegend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1">
      {LEGEND.map((l) => (
        <span key={l.key} className="inline-flex items-center gap-1.5 text-xs text-stone-600 dark:text-stone-400">
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ backgroundColor: urgencyColor(l.key) }}
          />
          {l.label}
        </span>
      ))}
    </div>
  );
}

export function TerritoryMap({ points }: { points: TerritoryPoint[] }) {
  const center: [number, number] =
    points.length > 0
      ? [
          points.reduce((s, p) => s + p.lat, 0) / points.length,
          points.reduce((s, p) => s + p.lng, 0) / points.length,
        ]
      : [4.05, 9.7];
  return (
    <div className="relative z-0">
      <MapContainer center={center} zoom={6} scrollWheelZoom={false} className="h-80 w-full rounded-lg">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {points.map((p) => {
          const color = urgencyColor(p.topUrgency);
          return (
            <CircleMarker
              key={p.key}
              center={[p.lat, p.lng]}
              radius={p.topUrgency === 'critical' ? 11 : 9}
              pathOptions={{ color, fillColor: color, fillOpacity: 0.55, weight: 2 }}
            >
              <Popup>
                <strong>{p.name}</strong>
                <br />
                {p.district} · {p.openIncidents} incident(s) ouvert(s) · {p.affectedStudents} élèves
              </Popup>
            </CircleMarker>
          );
        })}
        <FitBounds points={points} />
      </MapContainer>
    </div>
  );
}

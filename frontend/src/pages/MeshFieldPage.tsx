import { useCallback, useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';
import { Html5Qrcode } from 'html5-qrcode';
import { api, ApiError } from '../lib/api';
import type { School } from '../lib/api';
import { Badge, Button, Card } from '../components/ui';
import {
  MeshOutbox,
  apiBase,
  cachedSchools,
  cacheSchools,
  createBundle,
  isIOS,
  nodeId,
  parseFromQR,
  serializeForQR,
  smsGateway,
  smsHref,
  smsText,
  uploadToLaravel,
} from '../lib/mesh';
import type { MeshBundle } from '../lib/mesh';

const outbox = new MeshOutbox();
const SCANNER_ID = 'mesh-field-qr-reader';
const SMS_TYPES = [
  { value: 'P', label: 'P — Panne pompe/forage' },
  { value: 'L', label: 'L — Latrine' },
  { value: 'E', label: 'E — Eau / qualité' },
  { value: 'H', label: 'H — Hygiène' },
] as const;

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');

export default function MeshFieldPage() {
  const [schools, setSchools] = useState<School[]>(() => cachedSchools());
  const [schoolId, setSchoolId] = useState('');
  const [manualId, setManualId] = useState('');
  const [manualCode, setManualCode] = useState('');
  const [message, setMessage] = useState('');
  const [smsType, setSmsType] = useState<string>('P');
  const [items, setItems] = useState<MeshBundle[]>(() => outbox.all());
  const [online, setOnline] = useState(() => navigator.onLine);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [qrLabel, setQrLabel] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const scannerRef = useRef<Html5Qrcode | null>(null);

  const refresh = useCallback(() => setItems(outbox.all()), []);

  useEffect(() => {
    const onFlip = () => setOnline(navigator.onLine);
    window.addEventListener('online', onFlip);
    window.addEventListener('offline', onFlip);
    return () => {
      window.removeEventListener('online', onFlip);
      window.removeEventListener('offline', onFlip);
    };
  }, []);

  useEffect(() => {
    api
      .schools({})
      .then((res) => {
        setSchools(res.data);
        cacheSchools(res.data);
      })
      .catch(() => {
        setSchools(cachedSchools());
      });
  }, []);

  // Upload auto à la reconnexion.
  useEffect(() => {
    if (!online || outbox.size === 0) return;
    uploadToLaravel(outbox, apiBase())
      .then((r) => {
        if (r.accepted + r.duplicates > 0) {
          setNotice(`${r.accepted} signalement(s) envoyé(s), ${r.duplicates} déjà reçu(s).`);
          refresh();
        }
      })
      .catch(() => {
        /* on réessaiera à la prochaine reconnexion */
      });
  }, [online, refresh]);

  // Cycle de vie du scanner caméra.
  useEffect(() => {
    if (!scanning) return;
    const scanner = new Html5Qrcode(SCANNER_ID);
    scannerRef.current = scanner;
    scanner
      .start({ facingMode: 'environment' }, { fps: 10, qrbox: 250 }, (decoded) => {
        try {
          const bundle = parseFromQR(decoded);
          if (!bundle.bundle_id || !bundle.origin_node_id || !bundle.school_id) {
            setError('QR reçu : bundle incomplet.');
            return;
          }
          if (outbox.add(bundle)) {
            setNotice('Bundle reçu et stocké. Uploadez dès que possible.');
            refresh();
          } else {
            setNotice('Bundle déjà dans la file.');
          }
        } catch {
          setError('QR illisible : pas un bundle WASH.');
        } finally {
          setScanning(false);
        }
      }, undefined)
      .catch(() => {
        setError('Caméra inaccessible (HTTPS requis, autorisation à accorder).');
        setScanning(false);
      });
    return () => {
      scannerRef.current = null;
      scanner.stop().catch(() => undefined);
      scanner.clear();
    };
  }, [scanning, refresh]);

  const selectedSchool = schools.find((s) => String(s.id) === schoolId) ?? null;
  const effectiveId = selectedSchool ? selectedSchool.id : Number(manualId) || 0;
  const effectiveCode = selectedSchool?.code ?? manualCode.trim().toUpperCase();

  const saveOffline = async () => {
    setError(null);
    setNotice(null);
    if (!effectiveId || !message.trim()) {
      setError('Choisissez une école (ou son ID) et écrivez le signalement.');
      return;
    }
    setBusy(true);
    try {
      const bundle = await createBundle({
        schoolId: effectiveId,
        schoolCode: effectiveCode || undefined,
        message: message.trim(),
      });
      outbox.add(bundle);
      setMessage('');
      setQrUrl(null);
      refresh();
      setNotice('Signalement enregistré offline. Montrez son QR ou uploadez.');
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const showQr = async (bundle: MeshBundle) => {
    setError(null);
    try {
      const url = await QRCode.toDataURL(serializeForQR(bundle), {
        errorCorrectionLevel: 'M',
        width: 512,
        margin: 2,
      });
      setQrUrl(url);
      setQrLabel(`Bundle ${bundle.bundle_id.slice(0, 8)} — ${bundle.hops.length - 1} saut(s)`);
    } catch {
      setError('Bundle trop gros pour un QR.');
    }
  };

  const uploadAll = async () => {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const r = await uploadToLaravel(outbox, apiBase());
      refresh();
      setNotice(`${r.accepted} envoyé(s), ${r.duplicates} déjà reçu(s) par le serveur.`);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const removeItem = (id: string) => {
    outbox.remove([id]);
    refresh();
  };

  const gateway = smsGateway();
  const smsLink =
    gateway && effectiveCode ? smsHref(gateway, smsText(effectiveCode, smsType, message)) : null;

  return (
    <div className="mx-auto w-full max-w-2xl space-y-4 p-4 pb-16">
      <header className="flex flex-wrap items-center justify-between gap-2 pt-2">
        <div>
          <h1 className="text-xl font-bold">WASH Relai — signalement terrain</h1>
          <p className="mt-1 font-mono text-xs text-ink-soft">Nœud {nodeId()}</p>
        </div>
        <Badge tone={online ? 'success' : 'warn'}>{online ? 'En ligne' : 'Hors-ligne'}</Badge>
      </header>

      {isIOS() && (
        <Card className="p-3 text-xs text-ink-soft">
          Sur iPhone : le relai automatique en tâche de fond est impossible (limites Apple).
          Créez vos signalements ici, transmettez-les par QR à un téléphone Android relai,
          ou uploadez directement. Astuce : ajoutez cette page à l&apos;écran d&apos;accueil
          pour la retrouver sans réseau.
        </Card>
      )}

      {error && <p className="rounded-md bg-red-100 px-3 py-2 text-sm text-red-900 dark:bg-red-950 dark:text-red-200">{error}</p>}
      {notice && <p className="rounded-md bg-green-100 px-3 py-2 text-sm text-green-900 dark:bg-green-950 dark:text-green-200">{notice}</p>}

      <Card className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">Nouveau signalement (fonctionne hors-ligne)</h2>
        {schools.length > 0 ? (
          <select
            value={schoolId}
            onChange={(e) => setSchoolId(e.target.value)}
            className="w-full rounded-md border border-line bg-card px-2 py-2 text-sm"
          >
            <option value="">École…</option>
            {schools.map((s) => (
              <option key={s.id} value={s.id}>{s.name} — {s.district}</option>
            ))}
          </select>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            <input
              value={manualId}
              onChange={(e) => setManualId(e.target.value)}
              inputMode="numeric"
              placeholder="ID école"
              className="rounded-md border border-line bg-card px-2 py-2 text-sm"
            />
            <input
              value={manualCode}
              onChange={(e) => setManualCode(e.target.value)}
              placeholder="Code (ex. DOU-BON-001)"
              className="rounded-md border border-line bg-card px-2 py-2 text-sm"
            />
          </div>
        )}
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={3}
          placeholder="Décrivez la panne : pompe brisée, latrines pleines, eau trouble…"
          className="w-full rounded-md border border-line bg-card px-2 py-2 text-sm"
        />
        <Button variant="primary" disabled={busy} onClick={saveOffline} className="w-full">
          {busy ? 'Enregistrement…' : 'Enregistrer dans la file'}
        </Button>
      </Card>

      <Card className="space-y-3 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">File d&apos;envoi ({items.length})</h2>
          <Button size="sm" variant="primary" disabled={busy || items.length === 0} onClick={uploadAll}>
            {busy ? 'Envoi…' : 'Tout uploader'}
          </Button>
        </div>
        {items.length === 0 && <p className="text-xs text-ink-soft">File vide. Les signalements en attente de réseau apparaissent ici.</p>}
        <ul className="space-y-2">
          {items.map((b) => (
            <li key={b.bundle_id} className="flex items-center justify-between gap-2 rounded-md border border-line px-2 py-1.5 text-xs">
              <span className="min-w-0 flex-1 truncate">
                <span className="font-mono">{b.bundle_id.slice(0, 8)}</span>
                {' · '}{b.message?.slice(0, 60) ?? '(sans texte)'}
              </span>
              <Button size="sm" onClick={() => showQr(b)}>QR</Button>
              <Button size="sm" variant="ghost" onClick={() => removeItem(b.bundle_id)}>Retirer</Button>
            </li>
          ))}
        </ul>
        {qrUrl && (
          <div className="flex flex-col items-center gap-1 pt-2">
            <img src={qrUrl} alt="QR du bundle" className="h-56 w-56 rounded-md bg-white p-2" />
            <p className="font-mono text-[11px] text-ink-soft">{qrLabel}</p>
          </div>
        )}
      </Card>

      <Card className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">Recevoir (scanner le QR d&apos;un voisin)</h2>
        {!scanning ? (
          <Button onClick={() => setScanning(true)} className="w-full">Ouvrir le scanner</Button>
        ) : (
          <div className="space-y-2">
            <div id={SCANNER_ID} className="overflow-hidden rounded-md" />
            <Button variant="ghost" onClick={() => setScanning(false)} className="w-full">Fermer</Button>
          </div>
        )}
      </Card>

      {gateway && (
        <Card className="space-y-2 p-4">
          <h2 className="text-sm font-semibold">Secours SMS (sans internet du tout)</h2>
          <div className="flex gap-2">
            <select
              value={smsType}
              onChange={(e) => setSmsType(e.target.value)}
              className="flex-1 rounded-md border border-line bg-card px-2 py-2 text-sm"
            >
              {SMS_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          {smsLink && effectiveCode ? (
            <a href={smsLink} className="block text-center text-sm font-medium text-accent underline">
              Envoyer « {smsText(effectiveCode, smsType, message)} » par SMS
            </a>
          ) : (
            <p className="text-xs text-ink-soft">Sélectionnez une école avec un code pour activer l&apos;envoi SMS.</p>
          )}
        </Card>
      )}
    </div>
  );
}

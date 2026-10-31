import { useCallback, useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';
import { Html5Qrcode } from 'html5-qrcode';
import { api, ApiError } from '../lib/api';
import type { School } from '../lib/api';
import { Badge, Button, Card } from '../components/ui';
import {
  MEDIA_MAX_BYTES,
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
  splitMedia,
  uploadToLaravel,
} from '../lib/mesh';
import type { MeshBundle } from '../lib/mesh';
import { SEAL_ALG, fetchSealKey, sealMessage } from '../lib/mesh-crypto';
import type { SealKey } from '../lib/mesh-crypto';

const outbox = new MeshOutbox();
const SCANNER_ID = 'mesh-field-qr-reader';
const SMS_TYPES = [
  { value: 'P', label: 'P — Panne pompe/forage' },
  { value: 'L', label: 'L — Latrine' },
  { value: 'E', label: 'E — Eau / qualité' },
  { value: 'H', label: 'H — Hygiène' },
] as const;

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');

function blobToB64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.slice(result.indexOf(',') + 1));
    };
    reader.onerror = () => reject(new Error('Lecture fichier impossible.'));
    reader.readAsDataURL(blob);
  });
}

/** Photo → JPEG ≤1280px q0.7 (~100-200 Ko) pour le mesh. */
function compressPhoto(file: File): Promise<{ b64: string; mime: string }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, 1280 / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext('2d')?.drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        (blob) => {
          if (!blob) {
            reject(new Error('Compression photo impossible.'));
            return;
          }
          blobToB64(blob).then(
            (b64) => resolve({ b64, mime: 'image/jpeg' }),
            reject,
          );
        },
        'image/jpeg',
        0.7,
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Photo illisible.'));
    };
    img.src = url;
  });
}

function pickAudioMime(): string {
  if (typeof MediaRecorder === 'undefined') return '';
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
  for (const mime of candidates) {
    if (MediaRecorder.isTypeSupported(mime)) return mime.split(';')[0];
  }
  return '';
}

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
  const [sealOn, setSealOn] = useState(true);
  const [sealKey, setSealKey] = useState<SealKey | null>(null);
  const [photo, setPhoto] = useState<{ b64: string; mime: string } | null>(null);
  const [audio, setAudio] = useState<{ b64: string; mime: string } | null>(null);
  const [recording, setRecording] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
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

  useEffect(() => {
    if (!online) return;
    fetchSealKey(apiBase()).then(setSealKey);
  }, [online]);

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

  const onPhotoPicked = async (file: File | undefined) => {
    setError(null);
    if (!file) return;
    try {
      const compressed = await compressPhoto(file);
      if ((compressed.b64.length * 3) / 4 > MEDIA_MAX_BYTES) {
        setError('Photo trop lourde même compressée.');
        return;
      }
      setPhoto(compressed);
      setAudio(null);
    } catch (e) {
      setError(errMsg(e));
    }
  };

  const startRecording = () => {
    setError(null);
    const mime = pickAudioMime();
    if (!mime) {
      setError('Enregistrement vocal non supporté par ce navigateur.');
      return;
    }
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        const rec = new MediaRecorder(stream, { mimeType: mime });
        chunksRef.current = [];
        rec.ondataavailable = (ev: BlobEvent) => {
          if (ev.data.size > 0) chunksRef.current.push(ev.data);
        };
        rec.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          const blob = new Blob(chunksRef.current, { type: mime });
          blobToB64(blob)
            .then((b64) => {
              if ((b64.length * 3) / 4 > MEDIA_MAX_BYTES) {
                setError('Vocal trop long (30 s max).');
                return;
              }
              setAudio({ b64, mime });
              setPhoto(null);
            })
            .catch((e: unknown) => setError(errMsg(e)));
          setRecording(false);
        };
        recorderRef.current = rec;
        rec.start();
        setRecording(true);
        window.setTimeout(() => {
          if (recorderRef.current === rec && rec.state === 'recording') rec.stop();
        }, 30000);
      })
      .catch(() => setError('Micro inaccessible (autorisation + HTTPS requis).'));
  };

  const saveOffline = async () => {
    setError(null);
    setNotice(null);
    if (!effectiveId || !message.trim()) {
      setError('Choisissez une école (ou son ID) et écrivez le signalement.');
      return;
    }
    const media = photo
      ? { ...photo, channel: 'photo' as const }
      : audio
        ? { ...audio, channel: 'voice' as const }
        : null;
    setBusy(true);
    try {
      const key = sealOn ? sealKey : null;
      if (media) {
        const sealedMsg = key ? await sealMessage(message.trim(), key.public_key) : undefined;
        const split = await splitMedia({
          schoolId: effectiveId,
          schoolCode: effectiveCode || undefined,
          message: key ? undefined : message.trim(),
          sealed: sealedMsg,
          sealedAlg: key ? SEAL_ALG : undefined,
          channel: media.channel,
          mime: media.mime,
          dataB64: media.b64,
          seal: key
            ? (plain) => sealMessage(plain, key.public_key).then((sealed) => ({ sealed, alg: SEAL_ALG }))
            : undefined,
        });
        outbox.add(split.manifest);
        split.fragments.forEach((f) => outbox.add(f));
        setNotice(
          `Signalement + média enregistré offline (${split.fragments.length} fragments${key ? ', chiffrés' : ''}).`,
        );
      } else {
        const sealed = key ? await sealMessage(message.trim(), key.public_key) : undefined;
        const bundle = await createBundle({
          schoolId: effectiveId,
          schoolCode: effectiveCode || undefined,
          message: key ? undefined : message.trim(),
          sealed,
          sealedAlg: key ? SEAL_ALG : undefined,
        });
        outbox.add(bundle);
        setNotice(
          key
            ? 'Signalement chiffré enregistré offline. Montrez son QR ou uploadez.'
            : 'Signalement enregistré offline (non chiffré). Montrez son QR ou uploadez.',
        );
      }
      setMessage('');
      setPhoto(null);
      setAudio(null);
      setQrUrl(null);
      refresh();
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
    // Retirer un manifeste retire aussi ses fragments.
    const grouped = outbox.all().filter((b) => b.bundle_group === id).map((b) => b.bundle_id);
    outbox.remove([id, ...grouped]);
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
        <div className="flex flex-wrap items-center gap-2">
          <label className="cursor-pointer rounded-md border border-line px-2 py-1.5 text-sm">
            Photo
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                void onPhotoPicked(e.target.files?.[0]);
                e.target.value = '';
              }}
            />
          </label>
          {!recording ? (
            <Button size="sm" onClick={startRecording}>Vocal 30 s</Button>
          ) : (
            <Button size="sm" variant="primary" onClick={() => recorderRef.current?.stop()}>
              Stop ({'•'} en cours)
            </Button>
          )}
          {photo && <Badge tone="info">Photo prête</Badge>}
          {audio && <Badge tone="info">Vocal prêt</Badge>}
          {(photo || audio) && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setPhoto(null);
                setAudio(null);
              }}
            >
              Retirer
            </Button>
          )}
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-soft">
          <input
            type="checkbox"
            checked={sealOn && sealKey !== null}
            disabled={sealKey === null}
            onChange={(e) => setSealOn(e.target.checked)}
          />
          {sealKey
            ? 'Chiffrer vers le serveur (les relais ne liront pas le contenu)'
            : 'Chiffrement indisponible (clé serveur injoignable) — envoi en clair'}
        </label>
        <Button variant="primary" disabled={busy} onClick={saveOffline} className="w-full">
          {busy ? 'Enregistrement…' : 'Enregistrer dans la file'}
        </Button>
      </Card>

      <Card className="space-y-3 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">
            File d&apos;envoi ({items.filter((b) => !b.chunk).length}
            {items.some((b) => b.chunk) ? ` + ${items.filter((b) => b.chunk).length} fragments` : ''})
          </h2>
          <Button size="sm" variant="primary" disabled={busy || items.length === 0} onClick={uploadAll}>
            {busy ? 'Envoi…' : 'Tout uploader'}
          </Button>
        </div>
        {items.length === 0 && <p className="text-xs text-ink-soft">File vide. Les signalements en attente de réseau apparaissent ici.</p>}
        <ul className="space-y-2">
          {items.filter((b) => !b.chunk).map((b) => (
            <li key={b.bundle_id} className="flex items-center justify-between gap-2 rounded-md border border-line px-2 py-1.5 text-xs">
              <span className="min-w-0 flex-1 truncate">
                <span className="font-mono">{b.bundle_id.slice(0, 8)}</span>
                {' · '}{b.sealed ? '(chiffré)' : (b.message?.slice(0, 60) ?? '(sans texte)')}
                {b.fragment_total ? ` · média (${b.fragment_total} frag.)` : ''}
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

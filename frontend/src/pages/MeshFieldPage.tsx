import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
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
  outboxAdd,
  parseFromQR,
  serializeForQR,
  smsGateway,
  smsHref,
  smsText,
  splitMedia,
  uploadToLaravel,
} from '../lib/mesh';
import type { MeshBundle } from '../lib/mesh';
import { MESH_SYNC_MESSAGE, shouldFlushOutbox } from '../lib/mesh-sync';
import {
  MAX_SENT_HISTORY,
  bundleLabel,
  deriveOutboxView,
  loadOutboxMeta,
  outboxSummary,
  saveOutboxMeta,
} from '../lib/mesh-outbox-status';
import type { OutboxMeta, OutboxViewItem } from '../lib/mesh-outbox-status';
import {
  dismissIosHelp,
  iosHelpDismissed,
  isStandaloneDisplay,
  useInstallPrompt,
} from '../lib/install-prompt';
import { SEAL_ALG, fetchSealKey, sealMessage } from '../lib/mesh-crypto';
import type { SealKey } from '../lib/mesh-crypto';

const outbox = new MeshOutbox();
const SCANNER_ID = 'mesh-field-qr-reader';
const FILE_SCAN_ID = 'mesh-field-qr-file';
const SMS_TYPES = [
  { value: 'P', label: 'P — Panne pompe/forage' },
  { value: 'L', label: 'L — Latrine' },
  { value: 'E', label: 'E — Eau / qualité' },
  { value: 'H', label: 'H — Hygiène' },
] as const;

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');

/** Raison du premier échec de la file, sous la liste. */
function itemErrorHint(items: OutboxViewItem[]): ReactNode {
  const first = items.find((i) => i.status === 'failed' && i.error);
  if (!first?.error) return null;
  return <p className="text-xs text-red-800 dark:text-red-300">Dernier échec : {first.error}</p>;
}

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
  const [meta, setMeta] = useState<OutboxMeta>(() => loadOutboxMeta());
  const [sending, setSending] = useState(false);
  const [iosHelpVisible, setIosHelpVisible] = useState(
    () => isIOS() && !isStandaloneDisplay() && !iosHelpDismissed(),
  );
  const [standalone] = useState(() => isStandaloneDisplay());
  const install = useInstallPrompt();
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const scannerRef = useRef<Html5Qrcode | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const flushInFlight = useRef(false);
  const flushRef = useRef<() => Promise<void>>(async () => {});

  const refresh = useCallback(() => setItems(outbox.all()), []);

  // Envoie la file vers Laravel. `manual` = tap explicite (message détaillé).
  const flush = useCallback(
    async (manual = false) => {
      if (
        !shouldFlushOutbox({
          online: navigator.onLine,
          pendingCount: outbox.size,
          flushInFlight: flushInFlight.current,
        })
      ) {
        if (manual && !navigator.onLine && outbox.size > 0) {
          setError('Hors-ligne : la file reste stockée, elle partira au retour réseau.');
        }
        return;
      }
      flushInFlight.current = true;
      setSending(true);
      const before = outbox.all().filter((b) => !b.chunk);
      try {
        const r = await uploadToLaravel(outbox, apiBase());
        const afterIds = new Set(outbox.all().map((b) => b.bundle_id));
        const delivered = before.filter((b) => !afterIds.has(b.bundle_id));
        setMeta((prev) => {
          const failed = { ...prev.failed };
          for (const b of delivered) delete failed[b.bundle_id];
          const sent = [
            ...delivered.map((b) => ({
              id: b.bundle_id,
              label: bundleLabel(b),
              at: Date.now(),
            })),
            ...prev.sent,
          ].slice(0, MAX_SENT_HISTORY);
          const next = { failed, sent };
          saveOutboxMeta(next);
          return next;
        });
        refresh();
        if (manual || r.accepted + r.duplicates > 0) {
          setNotice(
            manual
              ? `${r.accepted} envoyé(s), ${r.duplicates} déjà reçu(s) par le serveur.`
              : `${r.accepted} signalement(s) envoyé(s), ${r.duplicates} déjà reçu(s).`,
          );
        }
      } catch (e) {
        const msg = errMsg(e);
        setMeta((prev) => {
          const failed = { ...prev.failed };
          for (const b of before) failed[b.bundle_id] = { at: Date.now(), error: msg };
          const next = { ...prev, failed };
          saveOutboxMeta(next);
          return next;
        });
        setError(`Envoi impossible (${msg}). La file est conservée — réessayez au retour réseau.`);
      } finally {
        flushInFlight.current = false;
        setSending(false);
      }
    },
    [refresh],
  );

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

  // Flush best-effort : message du SW (Background Sync) + fallbacks page
  // (retour online, onglet visible, minuteur 30 s) pour iOS/Safari.
  useEffect(() => {
    flushRef.current = flush;
  }, [flush]);

  useEffect(() => {
    const kick = () => {
      void flushRef.current();
    };
    const onVisible = () => {
      if (document.visibilityState === 'visible') kick();
    };
    const onSwMessage = (ev: MessageEvent) => {
      const data = ev.data as { type?: string } | null;
      if (data?.type === MESH_SYNC_MESSAGE) kick();
    };
    const sw = 'serviceWorker' in navigator ? navigator.serviceWorker : undefined;
    window.addEventListener('online', kick);
    document.addEventListener('visibilitychange', onVisible);
    sw?.addEventListener('message', onSwMessage);
    const timer = window.setInterval(kick, 30000);
    kick();
    return () => {
      window.removeEventListener('online', kick);
      document.removeEventListener('visibilitychange', onVisible);
      sw?.removeEventListener('message', onSwMessage);
      window.clearInterval(timer);
    };
  }, []);

  // Traite un texte QR (caméra ou fichier image) : même validation, même file.
  const ingestQrText = useCallback((decoded: string): boolean => {
    try {
      const bundle = parseFromQR(decoded);
      if (!bundle.bundle_id || !bundle.origin_node_id || !bundle.school_id) {
        setError('QR reçu : bundle incomplet.');
        return false;
      }
      if (outboxAdd(outbox, bundle)) {
        setNotice('Bundle reçu et stocké. Uploadez dès que possible.');
        refresh();
      } else {
        setNotice('Bundle déjà dans la file.');
      }
      return true;
    } catch {
      setError('QR illisible : pas un bundle WASH.');
      return false;
    }
  }, [refresh]);

  // Cycle de vie du scanner caméra.
  useEffect(() => {
    if (!scanning) return;
    const scanner = new Html5Qrcode(SCANNER_ID);
    scannerRef.current = scanner;
    scanner
      .start({ facingMode: 'environment' }, { fps: 10, qrbox: 250 }, (decoded) => {
        ingestQrText(decoded);
        setScanning(false);
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
  }, [scanning, refresh, ingestQrText]);

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
        outboxAdd(outbox, split.manifest);
        split.fragments.forEach((f) => outboxAdd(outbox, f));
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
        outboxAdd(outbox, bundle);
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

  const uploadAll = () => {
    setError(null);
    setNotice(null);
    void flush(true);
  };

  const removeItem = (id: string) => {
    // Retirer un manifeste retire aussi ses fragments.
    const grouped = outbox.all().filter((b) => b.bundle_group === id).map((b) => b.bundle_id);
    outbox.remove([id, ...grouped]);
    setMeta((prev) => {
      const failed = { ...prev.failed };
      delete failed[id];
      const next = { ...prev, failed };
      saveOutboxMeta(next);
      return next;
    });
    refresh();
  };

  const clearSent = () => {
    setMeta((prev) => {
      const next = { ...prev, sent: [] };
      saveOutboxMeta(next);
      return next;
    });
  };

  const showQrById = (id: string) => {
    const bundle = items.find((b) => b.bundle_id === id);
    if (bundle) void showQr(bundle);
  };

  const gateway = smsGateway();
  const smsLink =
    gateway && effectiveCode ? smsHref(gateway, smsText(effectiveCode, smsType, message)) : null;
  const outboxView = deriveOutboxView({
    bundles: items,
    sending,
    failed: meta.failed,
    sent: meta.sent,
  });

  return (
    <div className="mx-auto w-full max-w-2xl space-y-4 p-4 pb-16">
      <header className="flex flex-wrap items-center justify-between gap-2 pt-2">
        <div>
          <h1 className="text-xl font-bold">WASH Relai — signalement terrain</h1>
          <p className="mt-1 font-mono text-xs text-ink-soft">Nœud {nodeId()}</p>
        </div>
        <Badge tone={online ? 'success' : 'warn'}>{online ? 'En ligne' : 'Hors-ligne'}</Badge>
      </header>

      {install.canInstall && !standalone && (
        <Card className="flex flex-wrap items-center justify-between gap-2 p-3">
          <p className="text-xs text-ink-soft">
            Installez WASH Relai pour un accès direct, même hors-ligne.
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                void install.install();
              }}
              aria-label="Installer l'application WASH Relai"
            >
              Installer
            </Button>
            <Button size="sm" variant="ghost" onClick={install.dismiss} aria-label="Masquer le bouton d'installation">
              Plus tard
            </Button>
          </div>
        </Card>
      )}

      {iosHelpVisible && (
        <Card className="space-y-2 p-3 text-xs text-ink-soft">
          <p>
            Sur iPhone : le relai automatique en tâche de fond est impossible (limites Apple).
            Créez vos signalements ici, transmettez-les par QR à un téléphone Android relai,
            ou uploadez directement.
          </p>
          <div>
            <p className="font-semibold text-ink">Ajouter à l&apos;écran d&apos;accueil :</p>
            <ol className="list-decimal pl-5">
              <li>Touchez <span className="font-medium">Partager</span> (carré avec flèche vers le haut).</li>
              <li>Choisissez <span className="font-medium">« Sur l&apos;écran d&apos;accueil »</span>.</li>
              <li>Touchez <span className="font-medium">Ajouter</span> en haut à droite.</li>
            </ol>
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              dismissIosHelp();
              setIosHelpVisible(false);
            }}
            aria-label="Masquer l'aide d'installation iPhone"
          >
            Compris
          </Button>
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
          <h2 className="text-sm font-semibold">File d&apos;envoi</h2>
          <Button size="sm" variant="primary" disabled={sending || items.length === 0} onClick={uploadAll}>
            {sending ? 'Envoi…' : 'Tout uploader'}
          </Button>
        </div>
        <p role="status" aria-live="polite" className="text-xs text-ink-soft">
          {outboxSummary(outboxView.counts, outboxView.fragmentCount)}
        </p>
        {items.length === 0 && meta.sent.length === 0 && <p className="text-xs text-ink-soft">File vide. Les signalements en attente de réseau apparaissent ici.</p>}
        <ul className="space-y-2" aria-label="Signalements en attente d'envoi">
          {outboxView.items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line px-2 py-1.5 text-xs">
              <span className="min-w-0 flex-1 basis-full truncate sm:basis-auto">
                <span className="font-mono">{item.shortId}</span>
                {' · '}{item.label}
                {item.detail ? ` · ${item.detail}` : ''}
              </span>
              <Badge tone={item.status === 'failed' ? 'danger' : item.status === 'sending' ? 'info' : 'warn'}>
                {item.status === 'failed' ? 'Échec' : item.status === 'sending' ? 'Envoi…' : 'En attente'}
              </Badge>
              {item.status === 'failed' && (
                <Button
                  size="sm"
                  variant="primary"
                  disabled={sending}
                  onClick={uploadAll}
                  aria-label={`Réessayer l'envoi du signalement ${item.shortId}`}
                >
                  Réessayer
                </Button>
              )}
              <Button size="sm" onClick={() => showQrById(item.id)} aria-label={`Afficher le QR du signalement ${item.shortId}`}>QR</Button>
              <Button size="sm" variant="ghost" onClick={() => removeItem(item.id)} aria-label={`Retirer le signalement ${item.shortId} de la file`}>Retirer</Button>
            </li>
          ))}
        </ul>
        {itemErrorHint(outboxView.items)}
        {meta.sent.length > 0 && (
          <div className="space-y-2 pt-1">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold text-ink-soft">Envoyés récemment</h3>
              <Button size="sm" variant="ghost" onClick={clearSent} aria-label="Effacer l'historique des signalements envoyés">
                Effacer
              </Button>
            </div>
            <ul className="space-y-2" aria-label="Signalements envoyés">
              {meta.sent.map((s) => (
                <li key={`${s.id}-${s.at}`} className="flex items-center justify-between gap-2 rounded-md border border-line px-2 py-1.5 text-xs">
                  <span className="min-w-0 flex-1 truncate">
                    <span className="font-mono">{s.id.slice(0, 8)}</span>
                    {' · '}{s.label}
                  </span>
                  <Badge tone="success">Envoyé</Badge>
                </li>
              ))}
            </ul>
          </div>
        )}
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
        <div>
          <div id={FILE_SCAN_ID} className="hidden" aria-hidden="true" />
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              e.target.value = '';
              if (!file) return;
              setError(null);
              const reader = new Html5Qrcode(FILE_SCAN_ID);
              try {
                ingestQrText(await reader.scanFile(file, false));
              } catch {
                setError('Image illisible : aucun QR WASH détecté.');
              } finally {
                reader.clear();
              }
            }}
          />
          <Button variant="ghost" onClick={() => fileRef.current?.click()} className="w-full">
            … ou importer une photo de QR
          </Button>
        </div>
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

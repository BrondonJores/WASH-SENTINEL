import { useState } from 'react';
import type { FormEvent } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { Button, Card, LiveClock, StatusDot } from '../components/ui';
import { SentinelAvatar } from '../components/SentinelAvatar';

const inputCls =
  'w-full rounded-md border border-line bg-card px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none';
const labelCls = 'mb-1 block text-sm font-medium text-ink-soft';

export default function LoginPage() {
  const { user, login } = useAuth();
  const [email, setEmail] = useState('admin@wash.cm');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Échec de connexion.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-canvas px-4">
      <div aria-hidden="true" className="ambient" />
      <div className="relative z-10 w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <SentinelAvatar className="h-12 w-12 shrink-0" />
          <div>
            <h1 className="font-display text-xl font-bold tracking-tight">WASH Sentinel</h1>
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-faint">
              Console ops — accès restreint
            </p>
          </div>
        </div>
        <Card className="p-6">
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label htmlFor="email" className={labelCls}>
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="password" className={labelCls}>
                Mot de passe
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputCls}
              />
            </div>
            {error && <p className="text-sm font-medium text-danger">{error}</p>}
            <Button type="submit" variant="primary" disabled={busy} className="w-full">
              {busy ? 'Connexion…' : 'Se connecter'}
            </Button>
          </form>
        </Card>
        <div className="mt-4 flex items-center justify-between">
          <p className="font-mono text-[11px] text-ink-faint">
            démo : admin@wash.cm / tech@wash.cm / directeur@ecole.cm
          </p>
          <span className="flex items-center gap-1.5">
            <StatusDot tone="live" pulse />
            <LiveClock className="text-ink-faint" />
          </span>
        </div>
      </div>
    </div>
  );
}

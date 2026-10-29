import { useState } from 'react';
import type { FormEvent } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { Button, Card, LiveClock, StatusDot } from '../components/ui';
import { Icon } from '../components/icons';

const inputCls =
  'w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 focus:border-teal-700 focus:outline-none dark:border-stone-700 dark:bg-stone-900 dark:text-stone-100';
const labelCls = 'mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300';

export default function LoginPage() {
  const { user, login } = useAuth();
  const [email, setEmail] = useState('admin@wash.cm');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/admin" replace />;

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
    <div className="bg-grid flex min-h-screen items-center justify-center bg-stone-100 px-4 dark:bg-stone-950">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-teal-800 text-white dark:bg-teal-500 dark:text-stone-950">
            <Icon name="droplet" className="h-6 w-6" />
          </span>
          <div>
            <h1 className="text-xl font-bold tracking-tight">WASH Sentinel</h1>
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-stone-500 dark:text-stone-400">
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
            {error && <p className="text-sm font-medium text-red-700 dark:text-red-400">{error}</p>}
            <Button type="submit" variant="primary" disabled={busy} className="w-full">
              {busy ? 'Connexion…' : 'Se connecter'}
            </Button>
          </form>
        </Card>
        <div className="mt-4 flex items-center justify-between">
          <p className="font-mono text-[11px] text-stone-500 dark:text-stone-400">
            démo : admin@wash.cm / tech@wash.cm / directeur@ecole.cm
          </p>
          <span className="flex items-center gap-1.5">
            <StatusDot tone="live" pulse />
            <LiveClock className="text-stone-500 dark:text-stone-400" />
          </span>
        </div>
      </div>
    </div>
  );
}

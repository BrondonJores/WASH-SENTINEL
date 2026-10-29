import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { ThemeProvider } from './theme';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import ConsolePage from './pages/ConsolePage';
import PlaceholderPage from './pages/PlaceholderPage';
import SettingsPage from './pages/SettingsPage';

function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return user ? <>{children}</> : <Navigate to="/login" replace />;
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (!user?.roles.includes('wash_admin')) {
    return (
      <Layout>
        <p className="text-sm text-stone-600 dark:text-stone-400">Accès réservé aux administrateurs WASH.</p>
      </Layout>
    );
  }
  return <>{children}</>;
}

function authed(node: ReactNode) {
  return (
    <RequireAuth>
      <Layout>{node}</Layout>
    </RequireAuth>
  );
}

function adminOnly(node: ReactNode) {
  return (
    <RequireAuth>
      <RequireAdmin>
        <Layout>{node}</Layout>
      </RequireAdmin>
    </RequireAuth>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/admin" element={authed(<ConsolePage />)} />
            <Route
              path="/admin/incidents"
              element={authed(
                <PlaceholderPage
                  icon="alert"
                  title="Interventions"
                  description="Incidents triés par l'IA, vérifiés par l'humain : statuts, assignations, priorités."
                  step={3}
                />,
              )}
            />
            <Route
              path="/admin/ecoles"
              element={authed(
                <PlaceholderPage
                  icon="school"
                  title="Écoles"
                  description="Établissements, historiques de maintenance et verdicts réparer-vs-remplacer."
                  step={4}
                />,
              )}
            />
            <Route
              path="/admin/signalements"
              element={authed(
                <PlaceholderPage
                  icon="inbox"
                  title="Signalements"
                  description="File de vérification : doublons flaggés, rattachements, corrections."
                  step={5}
                />,
              )}
            />
            <Route
              path="/admin/journal"
              element={adminOnly(
                <PlaceholderPage
                  icon="file"
                  title="Journal IA"
                  description="Toutes les décisions de l'IA : confiance, modèle, overrides humains."
                  step={5}
                />,
              )}
            />
            <Route
              path="/admin/notifications"
              element={authed(
                <PlaceholderPage
                  icon="bell"
                  title="Notifications"
                  description="Alertes critiques, confirmations et activité récente."
                  step={5}
                />,
              )}
            />
            <Route path="/admin/reglages" element={adminOnly(<SettingsPage />)} />
            <Route path="/" element={<Navigate to="/admin" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}

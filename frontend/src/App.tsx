import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Suspense, lazy, useEffect } from 'react';
import type { ReactNode } from 'react';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { pick, useUILang } from './lib/i18n';
import { ThemeProvider } from './theme';
import { DialogueProvider } from './dialogues/DialogueContext';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import ConsolePage from './pages/ConsolePage';
import IncidentsPage from './pages/IncidentsPage';
import SchoolsPage from './pages/SchoolsPage';
import TeamsPage from './pages/TeamsPage';
import ReportsPage from './pages/ReportsPage';
import JournalPage from './pages/JournalPage';
import NotificationsPage from './pages/NotificationsPage';
import SettingsPage from './pages/SettingsPage';
import MeshPage from './pages/MeshPage';

const MeshFieldPage = lazy(() => import('./pages/MeshFieldPage'));
const PublicReportPage = lazy(() => import('./pages/PublicReportPage'));

function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return user ? <>{children}</> : <Navigate to="/login" replace />;
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const ui = useUILang();
  if (!user?.roles.includes('wash_admin')) {
    return (
      <Layout>
        <p className="text-sm text-stone-600 dark:text-stone-400">{pick(ui, 'Accès réservé aux administrateurs WASH.', 'Restricted to WASH administrators.')}</p>
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

function AuthedApp() {
  const { user } = useAuth();
  const ui = useUILang();
  useEffect(() => {
    document.documentElement.lang = ui;
    document.title = pick(ui, 'WASH Sentinel — Console IA', 'WASH Sentinel — AI Console');
  }, [ui]);
  return (
    <DialogueProvider key={user?.email ?? 'anon'}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/m"
              element={
                <Suspense fallback={<p className="p-4 text-sm text-ink-soft">{pick(ui, 'Chargement du relai terrain…', 'Loading the field relay…')}</p>}>
                  <MeshFieldPage />
                </Suspense>
              }
            />
            <Route
              path="/signaler"
              element={
                <Suspense fallback={<p className="p-4 text-sm text-ink-soft">{pick(ui, 'Chargement du formulaire…', 'Loading the form…')}</p>}>
                  <PublicReportPage />
                </Suspense>
              }
            />
            <Route path="/" element={authed(<ConsolePage />)} />
            <Route path="/admin/incidents" element={authed(<IncidentsPage />)} />
            <Route path="/admin/ecoles" element={authed(<SchoolsPage />)} />
            <Route path="/admin/equipes" element={authed(<TeamsPage />)} />
            <Route path="/admin/signalements" element={authed(<ReportsPage />)} />
            <Route path="/admin/journal" element={adminOnly(<JournalPage />)} />
            <Route path="/admin/notifications" element={authed(<NotificationsPage />)} />
            <Route path="/admin/mesh" element={authed(<MeshPage />)} />
            <Route path="/admin/reglages" element={adminOnly(<SettingsPage />)} />
            <Route path="/admin" element={<Navigate to="/" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
    </DialogueProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
          <AuthedApp />
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}

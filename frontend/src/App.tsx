import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { ThemeProvider } from './theme';
import { DialogueProvider } from './dialogues/DialogueContext';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import ConsolePage from './pages/ConsolePage';
import IncidentsPage from './pages/IncidentsPage';
import SchoolsPage from './pages/SchoolsPage';
import ReportsPage from './pages/ReportsPage';
import JournalPage from './pages/JournalPage';
import NotificationsPage from './pages/NotificationsPage';
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

function AuthedApp() {
  const { user } = useAuth();
  return (
    <DialogueProvider key={user?.email ?? 'anon'}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={authed(<ConsolePage />)} />
            <Route path="/admin/incidents" element={authed(<IncidentsPage />)} />
            <Route path="/admin/ecoles" element={authed(<SchoolsPage />)} />
            <Route path="/admin/signalements" element={authed(<ReportsPage />)} />
            <Route path="/admin/journal" element={adminOnly(<JournalPage />)} />
            <Route path="/admin/notifications" element={authed(<NotificationsPage />)} />
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

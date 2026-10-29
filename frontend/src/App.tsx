import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';
import { AuthProvider, useAuth } from './auth/AuthContext';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
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
        <p className="text-sm text-stone-600">Accès réservé aux administrateurs WASH.</p>
      </Layout>
    );
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/admin/reglages"
            element={
              <RequireAuth>
                <RequireAdmin>
                  <Layout>
                    <SettingsPage />
                  </Layout>
                </RequireAdmin>
              </RequireAuth>
            }
          />
          <Route path="/" element={<Navigate to="/admin/reglages" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

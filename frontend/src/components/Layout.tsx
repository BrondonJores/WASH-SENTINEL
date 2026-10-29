import { NavLink, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useAuth } from '../auth/AuthContext';

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const quit = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="min-h-screen bg-white text-stone-900">
      <header className="border-b border-stone-200">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <div>
            <p className="text-lg font-bold leading-tight">WASH Sentinel</p>
            <p className="text-sm text-stone-600">Administration</p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-stone-600">{user?.name}</span>
            <button
              onClick={quit}
              className="rounded-md border border-stone-300 px-3 py-1.5 text-sm font-medium text-stone-700 hover:bg-stone-100"
            >
              Déconnexion
            </button>
          </div>
        </div>
      </header>
      <nav className="border-b border-stone-200 bg-stone-50">
        <div className="mx-auto flex max-w-5xl gap-1 px-4">
          <NavLink
            to="/admin/reglages"
            className={({ isActive }) =>
              `px-3 py-2 text-sm font-medium ${isActive ? 'text-teal-800 underline underline-offset-4' : 'text-stone-600 hover:text-stone-900'}`
            }
          >
            Réglages IA
          </NavLink>
        </div>
      </nav>
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </div>
  );
}

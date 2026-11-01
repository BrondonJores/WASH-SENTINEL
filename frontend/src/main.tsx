import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Deep-link hash (binaire desktop : le webview démarre sur index.html#/m,
// un serveur de fichiers statiques ne connaît pas la route /m).
if (window.location.hash.startsWith('#/m')) {
  window.history.replaceState(null, '', '/m')
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

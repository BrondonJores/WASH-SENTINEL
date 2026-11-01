# WASH Sentinel — Frontend

React 19 + TypeScript + Tailwind v4: AI console (dashboard, incidents, schools, reports, journal,
notifications, mesh monitor, AI settings), public report form (`/signaler`), and the installable
offline field PWA (`/m` — outbox, QR show/scan/import, Background Sync, install prompt).

## Development

```bash
cp .env.example .env
npm install
npm run dev        # http://localhost:5173 (Vite)
```

The Laravel backend must run (Docker compose from the repo root, or `php artisan serve`)
with `VITE_API_URL` pointing at `/api`.

Demo accounts (`password`): `admin@wash.cm`, `tech@wash.cm`, `directeur@ecole.cm`.

## Checks & production

```bash
npx tsc -b        # types (CI gate)
npm run lint      # oxlint, 0 errors
npm run build     # dist/ (service worker precaches the shell + /m)
```

Notes: the TS mesh client is vendored at `src/lib/mesh-sdk.ts` and must stay identical to
`mesh/sdk/mesh-sdk.ts` (CI diff guard). PWA install: open `/m` once online, then Add to Home Screen.

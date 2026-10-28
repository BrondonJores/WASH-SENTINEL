# WASH Sentinel — Frontend

Interface d'administration (page Réglages IA) et widget agent.

## Développement

```bash
cp .env.example .env
npm install
npm run dev
```

Ouvrez [http://localhost:5173](http://localhost:5173) dans le navigateur.
Le backend Laravel doit tourner (ex: `php artisan serve --port=80` ou Docker)
avec `VITE_API_URL` pointant sur `/api`.

Compte démo : `test@example.com` / `password` (seeders Laravel).

## Production

```bash
npm run build
```

Les fichiers sont générés dans `dist/`.

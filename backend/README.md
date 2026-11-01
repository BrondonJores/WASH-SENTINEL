# WASH Sentinel — Backend (Laravel 12 API)

JSON-only API (`/api`, Sanctum + `spatie/laravel-permission` RBAC): schools, reports, incidents
lifecycle, AI copilot (chat, plans, epidemic scan, STT/vision profiles), WhatsApp webhook,
mesh ingest (bundles, SMS, USSD, signatures + TOFU), notifications, audit journal.

## Development (from repo root, recommended)

```bash
./start.sh   # compose + key + migrate --force + seed + Ollama
```

Standalone: `composer install && cp .env.example .env && php artisan key:generate`,
Postgres at `pgsql:5432` (`DB_*` in `.env`), then `php artisan migrate --force && php artisan db:seed --force`.

## Checks

```bash
php artisan test                                            # full suite (CI gate)
php artisan test --filter 'WashMeshTest|WashSmsTest|WashUssdTest|MeshSignatureTest|MeshNodeKeyTest|WashWhatsAppTest'
```

Seeded accounts (`password`): `admin@wash.cm` (wash_admin), `tech@wash.cm`
(maintenance_agent), `directeur@ecole.cm` (school_reporter) — plus 4 demo incidents.

Key artisan commands: `mesh:key-generate` (E2E seal keypair), `queue:work` (async WA/mesh
processing — runs as the `queue` compose service in dev).

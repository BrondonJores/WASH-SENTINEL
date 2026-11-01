<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Route;

/**
 * Preflight WhatsApp (Canal 2 vocal) : vérifie la config + la connectivité
 * Graph API avant le branchement live. Tout l'affichage est en français.
 *
 * Exit 0 si tout est vert (avertissements tolérés), 1 sinon avec la
 * liste des actions correctives.
 */
class WhatsappPreflightCommand extends Command
{
    protected $signature = 'wash:whatsapp:preflight';

    protected $description = 'Vérifie la configuration WhatsApp (Canal 2 vocal) avant le branchement live.';

    /** @var string[] */
    private array $errors = [];

    /** @var string[] */
    private array $warnings = [];

    public function handle(): int
    {
        $this->info('Preflight WhatsApp — Canal 2 (vocal de bout en bout)');
        $this->line('');

        $this->checkEnabled();
        $token = $this->checkToken();
        $phoneNumberId = $this->checkPhoneNumberId();
        $this->checkWabaId();
        $this->checkVerifyToken();
        $simulator = $this->resolveSimulator();
        $this->checkAppSecret($simulator);
        $this->checkSimulator($simulator);
        $this->checkConnectivity($token, $phoneNumberId, $simulator);
        $this->checkWebhookRoute();

        $this->line('');

        foreach ($this->warnings as $warning) {
            $this->warn('Avertissement : '.$warning);
        }

        if ($this->errors !== []) {
            $this->error('Preflight ÉCHOUÉ : '.count($this->errors).' point(s) à corriger.');
            $this->line('');
            $this->line('Actions à mener :');
            foreach ($this->errors as $i => $error) {
                $this->line('  '.($i + 1).'. '.$error);
            }

            return self::FAILURE;
        }

        $this->info('Preflight RÉUSSI : configuration WhatsApp prête pour le live.');

        return self::SUCCESS;
    }

    /**
     * Lecture config/whatsapp.php avec repli legacy services.whatsapp.*
     * (même règle que MetaWhatsAppService::cfg()).
     */
    private function cfg(string $key, mixed $default = ''): mixed
    {
        $legacyMap = [
            'base_url' => 'base_url',
            'phone_number_id' => 'phone_number_id',
            'token' => 'access_token',
            'verify_token' => 'verify_token',
            'app_secret' => 'app_secret',
            'simulator' => 'simulator',
        ];

        $value = config("whatsapp.{$key}");
        if ($value !== null && $value !== '') {
            return $value;
        }
        if (isset($legacyMap[$key])) {
            $legacy = config("services.whatsapp.{$legacyMap[$key]}");
            if ($legacy !== null && $legacy !== '') {
                return $legacy;
            }
        }

        return $default;
    }

    private function ok(string $label, string $detail = ''): void
    {
        $this->line('  [OK] '.$label.($detail !== '' ? ' — '.$detail : ''));
    }

    private function markError(string $label, string $action): void
    {
        $this->line('  [ERREUR] '.$label);
        $this->errors[] = $action;
    }

    private function skip(string $label, string $reason): void
    {
        $this->line('  [IGNORÉ] '.$label.' — '.$reason);
    }

    private function checkEnabled(): void
    {
        $enabled = (bool) config('whatsapp.enabled', true);
        if ($enabled) {
            $this->ok('WHATSAPP_ENABLED', 'canal activé');
        } else {
            $this->markError(
                'WHATSAPP_ENABLED : canal désactivé (webhook répondrait 503)',
                'Activer le canal : WHATSAPP_ENABLED=true dans le .env puis vider le cache de config.'
            );
        }
    }

    private function checkToken(): string
    {
        $token = (string) $this->cfg('token', '');
        if ($token !== '') {
            // Jamais la valeur : seule la longueur, pour prouver la présence.
            $this->ok('WHATSAPP_TOKEN', 'présent ('.strlen($token).' caractères, valeur masquée)');
        } else {
            $this->markError(
                'WHATSAPP_TOKEN : absent',
                'Renseigner WHATSAPP_TOKEN (Dashboard Meta → WhatsApp → API Setup).'
            );
        }

        return $token;
    }

    private function checkPhoneNumberId(): string
    {
        $id = (string) $this->cfg('phone_number_id', '');
        if ($id !== '') {
            $this->ok('WHATSAPP_PHONE_NUMBER_ID', $id);
        } else {
            $this->markError(
                'WHATSAPP_PHONE_NUMBER_ID : absent',
                'Renseigner WHATSAPP_PHONE_NUMBER_ID (numéro expéditeur Meta, API Setup).'
            );
        }

        return $id;
    }

    private function checkWabaId(): void
    {
        $wabaId = (string) config('whatsapp.waba_id', '');
        if ($wabaId !== '') {
            $this->ok('WHATSAPP_WABA_ID', $wabaId);
        } else {
            $this->markError(
                'WHATSAPP_WABA_ID : absent',
                'Renseigner WHATSAPP_WABA_ID (compte WhatsApp Business, API Setup).'
            );
        }
    }

    private function checkVerifyToken(): void
    {
        $verifyToken = (string) $this->cfg('verify_token', '');
        if ($verifyToken === '') {
            $this->markError(
                'WHATSAPP_VERIFY_TOKEN : absent',
                'Inventer WHATSAPP_VERIFY_TOKEN (≥ 16 caractères) et le recopier dans le Dashboard (Configuration du webhook).'
            );
        } elseif (strlen($verifyToken) < 16) {
            $this->markError(
                'WHATSAPP_VERIFY_TOKEN : trop court ('.strlen($verifyToken).' caractères, 16 minimum)',
                'Allonger WHATSAPP_VERIFY_TOKEN à ≥ 16 caractères et le recopier dans le Dashboard.'
            );
        } else {
            $this->ok('WHATSAPP_VERIFY_TOKEN', strlen($verifyToken).' caractères (valeur masquée)');
        }
    }

    private function resolveSimulator(): bool
    {
        return (bool) $this->cfg('simulator', false);
    }

    private function checkAppSecret(bool $simulator): void
    {
        $secret = (string) $this->cfg('app_secret', '');
        if ($secret !== '') {
            $this->ok('WHATSAPP_APP_SECRET', 'présent (signature HMAC vérifiable)');
            return;
        }

        if ($simulator) {
            $this->line('  [ATTENTION] WHATSAPP_APP_SECRET : absent (toléré en mode simulateur)');
            $this->warnings[] = 'WHATSAPP_APP_SECRET absent : penser à le renseigner avant le live (sinon webhook 403).';
        } else {
            $this->markError(
                'WHATSAPP_APP_SECRET : absent (webhook refuserait les appels Meta en live)',
                'Renseigner WHATSAPP_APP_SECRET (Dashboard Meta → Paramètres de l\'application).'
            );
        }
    }

    private function checkSimulator(bool $simulator): void
    {
        if (! $simulator) {
            $this->ok('WHATSAPP_SIMULATOR', 'false — appels Graph API réels');

            return;
        }

        if (app()->environment('production')) {
            $this->markError(
                'WHATSAPP_SIMULATOR : true en production (aucun appel Meta réel)',
                'Passer WHATSAPP_SIMULATOR=false en production.'
            );
        } else {
            $this->line('  [ATTENTION] WHATSAPP_SIMULATOR : true — aucun appel Meta réel (dev local uniquement)');
            $this->warnings[] = 'Mode simulateur actif : passer WHATSAPP_SIMULATOR=false pour le live.';
        }
    }

    private function checkConnectivity(string $token, string $phoneNumberId, bool $simulator): void
    {
        if ($simulator) {
            $this->skip('Connectivité Graph API', 'mode simulateur : aucun appel Meta');

            return;
        }
        if ($token === '' || $phoneNumberId === '') {
            $this->skip('Connectivité Graph API', 'token ou phone_number_id manquant (voir erreurs ci-dessus)');

            return;
        }

        $base = rtrim((string) $this->cfg('base_url', 'https://graph.facebook.com/v21.0'), '/');
        $url = $base.'/'.$phoneNumberId;

        try {
            $response = Http::timeout(10)
                ->withToken($token)
                ->get($url, ['fields' => 'display_phone_number']);
        } catch (ConnectionException $e) {
            $this->markError(
                'Connectivité Graph API : délai dépassé ou réseau injoignable ('.$e->getMessage().')',
                'Vérifier la connectivité sortante vers graph.facebook.com (pare-feu, proxy) puis relancer le preflight.'
            );

            return;
        } catch (\Throwable $e) {
            $this->markError(
                'Connectivité Graph API : erreur inattendue ('.$e->getMessage().')',
                'Vérifier WHATSAPP_BASE_URL puis relancer le preflight.'
            );

            return;
        }

        if ($response->successful()) {
            $display = (string) ($response->json('display_phone_number') ?? '');
            $detail = $display !== '' ? 'numéro '.$display : 'réponse Meta OK';
            $this->ok('Connectivité Graph API', $detail);

            return;
        }

        $status = $response->status();
        if ($status === 401) {
            $this->markError(
                'Connectivité Graph API : 401 — token invalide ou expiré',
                'Régénérer WHATSAPP_TOKEN (Dashboard Meta → API Setup, ou token permanent via System User) puis relancer le preflight.'
            );
        } elseif ($status === 403) {
            $this->markError(
                'Connectivité Graph API : 403 — token sans permission ou numéro inaccessible',
                'Vérifier les permissions du token (whatsapp_business_messaging) et WHATSAPP_PHONE_NUMBER_ID puis relancer le preflight.'
            );
        } else {
            $this->markError(
                'Connectivité Graph API : HTTP '.$status,
                'Vérifier WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID et WHATSAPP_BASE_URL puis relancer le preflight.'
            );
        }
    }

    private function checkWebhookRoute(): void
    {
        $hasGet = false;
        $hasPost = false;

        foreach (Route::getRoutes() as $route) {
            if ($route->uri() !== 'api/v1/whatsapp/webhook') {
                continue;
            }
            $methods = $route->methods();
            if (in_array('GET', $methods, true)) {
                $hasGet = true;
            }
            if (in_array('POST', $methods, true)) {
                $hasPost = true;
            }
        }

        if ($hasGet && $hasPost) {
            $this->ok('Route webhook', 'GET + POST /api/v1/whatsapp/webhook enregistrées');
        } else {
            $missing = [];
            if (! $hasGet) {
                $missing[] = 'GET (challenge verify)';
            }
            if (! $hasPost) {
                $missing[] = 'POST (réception messages)';
            }
            $this->markError(
                'Route webhook : manquante ('.implode(', ', $missing).')',
                'Restaurer la route /api/v1/whatsapp/webhook dans routes/api.php.'
            );
        }
    }
}

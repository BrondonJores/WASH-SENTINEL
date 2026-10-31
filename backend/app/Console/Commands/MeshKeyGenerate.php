<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;

class MeshKeyGenerate extends Command
{
    protected $signature = 'mesh:key-generate';

    protected $description = 'Génère la paire de clés E2E du serveur mesh (libsodium sealed box).';

    public function handle(): int
    {
        $keypair = sodium_crypto_box_keypair();
        $secret = base64_encode(sodium_crypto_box_secretkey($keypair));
        $public = base64_encode(sodium_crypto_box_publickey($keypair));

        $this->info('Paire de clés mesh générée.');
        $this->line('  MESH_SEAL_SECRET='.$secret);
        $this->line('  Clé publique (publiée sur GET /api/v1/mesh/key) : '.$public);
        $this->warn('Ajoutez MESH_SEAL_SECRET au .env du backend et redémarrez. Ne commitez jamais la clé privée.');

        return self::SUCCESS;
    }
}

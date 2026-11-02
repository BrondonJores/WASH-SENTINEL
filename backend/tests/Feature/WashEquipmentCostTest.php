<?php

namespace Tests\Feature;

use App\Http\Controllers\Api\WashEquipmentCostController;
use App\Models\EquipmentCost;
use Database\Seeders\WashEquipmentCostSeeder;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Request;
use Illuminate\Validation\ValidationException;
use Symfony\Component\HttpKernel\Exception\HttpException;
use Tests\TestCase;

// Référentiel prix : le routeur (routes/api.php) appartient à un autre
// agent, donc ces tests appellent le contrôleur directement.
class WashEquipmentCostTest extends TestCase
{
    use RefreshDatabase;

    private function makeGet(array $query = []): Request
    {
        return Request::create('/faux', 'GET', $query);
    }

    private function makePost(array $data): Request
    {
        return Request::create('/faux', 'POST', $data);
    }

    private function makePatch(array $data): Request
    {
        return Request::create('/faux', 'PATCH', $data);
    }

    public function test_seeder_charge_six_prix_sources(): void
    {
        $this->seed(WashEquipmentCostSeeder::class);

        $this->assertSame(6, EquipmentCost::count());

        $forage = EquipmentCost::where('equipment_key', 'forage_equipe_pmh')->firstOrFail();
        $this->assertSame(8000000, $forage->min_xaf);
        $this->assertSame(8500000, $forage->max_xaf);
        $this->assertSame('water_point', $forage->category);
        $this->assertNotEmpty($forage->source_name);
        $this->assertNotEmpty($forage->source_url);

        // Idempotent : un 2e passage ne duplique rien.
        $this->seed(WashEquipmentCostSeeder::class);
        $this->assertSame(6, EquipmentCost::count());

        // Toutes les catégories sont valides, toutes les lignes sont sourcées.
        foreach (EquipmentCost::all() as $row) {
            $this->assertContains($row->category, EquipmentCost::CATEGORIES);
            $this->assertGreaterThanOrEqual(0, $row->min_xaf);
            $this->assertGreaterThanOrEqual($row->min_xaf, $row->max_xaf);
            $this->assertNotEmpty($row->source_name);
        }
    }

    public function test_index_liste_et_filtre_par_categorie(): void
    {
        $this->seed(WashEquipmentCostSeeder::class);
        $controller = new WashEquipmentCostController();

        $all = $controller->index($this->makeGet())->getData(true);
        $this->assertCount(6, $all);

        $water = $controller->index($this->makeGet(['category' => 'water_point']))->getData(true);
        $this->assertCount(4, $water);
        foreach ($water as $row) {
            $this->assertSame('water_point', $row['category']);
        }
    }

    public function test_store_cree_un_prix(): void
    {
        $controller = new WashEquipmentCostController();

        $response = $controller->store($this->makePost([
            'equipment_key' => 'test_pompe',
            'label' => 'Pompe de test',
            'category' => 'water_point',
            'min_xaf' => 10000,
            'max_xaf' => 20000,
            'source_name' => 'Boutique de test',
            'source_url' => 'https://example.com/pompe',
            'observed_at' => '2026-11-02',
            'notes' => 'Ligne de test.',
        ]));

        $this->assertSame(201, $response->getStatusCode());
        $data = $response->getData(true);
        $this->assertSame('test_pompe', $data['equipment_cost']['equipment_key']);
        $this->assertDatabaseHas('equipment_costs', ['equipment_key' => 'test_pompe']);
    }

    public function test_store_rejette_categorie_inconnue(): void
    {
        $this->expectException(ValidationException::class);

        (new WashEquipmentCostController())->store($this->makePost([
            'equipment_key' => 'test_bad',
            'label' => 'Mauvaise catégorie',
            'category' => 'toitures',
            'min_xaf' => 10000,
            'max_xaf' => 20000,
            'source_name' => 'Boutique de test',
        ]));
    }

    public function test_store_rejette_max_inferieur_au_min(): void
    {
        $this->expectException(ValidationException::class);

        (new WashEquipmentCostController())->store($this->makePost([
            'equipment_key' => 'test_range',
            'label' => 'Fourchette inversée',
            'category' => 'water_point',
            'min_xaf' => 20000,
            'max_xaf' => 10000,
            'source_name' => 'Boutique de test',
        ]));
    }

    public function test_show_et_update(): void
    {
        $this->seed(WashEquipmentCostSeeder::class);
        $controller = new WashEquipmentCostController();
        $row = EquipmentCost::where('equipment_key', 'station_lavemains')->firstOrFail();

        $shown = $controller->show($row)->getData(true);
        $this->assertSame('station_lavemains', $shown['equipment_key']);

        $updated = $controller->update($this->makePatch(['max_xaf' => 25000]), $row)->getData(true);
        $this->assertSame(25000, $updated['equipment_cost']['max_xaf']);
        $this->assertSame(1200, $updated['equipment_cost']['min_xaf']);
    }

    public function test_update_partiel_rejette_fourchette_incoherente(): void
    {
        $this->seed(WashEquipmentCostSeeder::class);
        $row = EquipmentCost::where('equipment_key', 'station_lavemains')->firstOrFail();

        // min actuel 1 200 : un max à 500 rend la fourchette incohérente.
        $this->expectException(HttpException::class);

        (new WashEquipmentCostController())->update($this->makePatch(['max_xaf' => 500]), $row);
    }
}

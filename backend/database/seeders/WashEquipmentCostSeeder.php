<?php

namespace Database\Seeders;

use App\Models\EquipmentCost;
use Illuminate\Database\Seeder;

// Référentiel prix issu d'une recherche web réelle (observations du
// 2026-11-02, montants étrangers convertis au taux indicatif ~600 XAF/USD,
// parité 1 XOF ≈ 1 XAF). AUCUNE source inventée : chaque ligne cite ses
// observations en notes. Idempotent (updateOrCreate sur equipment_key).
class WashEquipmentCostSeeder extends Seeder
{
    public function run(): void
    {
        foreach ($this->costs() as $data) {
            EquipmentCost::updateOrCreate(['equipment_key' => $data['equipment_key']], $data);
        }
    }

    protected function costs(): array
    {
        return [
            [
                'equipment_key' => 'pompe_immergee_750w',
                'label' => 'Pompe immergée 750 W – 1,1 kW (forage)',
                'category' => 'water_point',
                'min_xaf' => 63000,
                'max_xaf' => 134500,
                'source_name' => 'NKCL Market / Glotelho Cameroun',
                'source_url' => 'https://nkclmarket.com/product/subcategory/315/pompe?page=2',
                'observed_at' => '2026-11-02',
                'notes' => 'Min : Glotelho Cameroun, pompe immergée INGCO SWP7501 750 W 1 HP, 63 000 FCFA en promo (régulier 75 000). Max : NKCL Market Cameroun, pompe immergée INGCO DWP7501 750 W 1 HP 4", 122 300 XAF (régulier 134 500). Complément : Afribobo, pompe immergée pour puits 18 m, 120 000 FCFA.',
            ],
            [
                'equipment_key' => 'pompe_surface_jet',
                'label' => 'Pompe de surface / jet 550 W – 1,1 kW',
                'category' => 'water_point',
                'min_xaf' => 46500,
                'max_xaf' => 115000,
                'source_name' => 'NKCL Market / Glotelho Cameroun',
                'source_url' => 'https://nkclmarket.com/product/subcategory/315/pompe?page=2',
                'observed_at' => '2026-11-02',
                'notes' => 'Min : NKCL Market Cameroun, pompe périphérique EMTOP 750 W, 46 500 XAF (jet de surface INGCO JP07508 750 W : 48 500 XAF). Max : NKCL Market, surpresseur INGCO JPT110068 1 100 W 1,5 CV, 115 000 XAF (régulier 189 000). Recoupement : Glotelho Cameroun, centrifuge INGCO 550 W 49 400 FCFA / 1 500 W 56 500 FCFA.',
            ],
            [
                'equipment_key' => 'forage_equipe_pmh',
                'label' => 'Forage complet équipé de pompe à motricité humaine',
                'category' => 'water_point',
                'min_xaf' => 8000000,
                'max_xaf' => 8500000,
                'source_name' => "ARMP Cameroun (appels d'offres communaux)",
                'source_url' => 'https://pridesoft.armp.cm/_lib/file/doc/0903/2024/01/16/C_DJOHONG/AD_16_01_24_AO_01_C-DJOHONG.pdf',
                'observed_at' => '2026-11-02',
                'notes' => "Coût prévisionnel par lot (forage + PMH) : 8 000 000 FCFA (Beka 2020, Ndop 2019, Djohong 2024 : 24 M pour 3 lots) à 8 500 000 FCFA (Santa-Mezam 2020, Odza/Yaoundé IV 2018 via Katika237, Wina 2025 : 25,5 M pour 3 forages). Variante forage pastoral : 10 000 000 FCFA (Mayo-Baleo 2021).",
            ],
            [
                'equipment_key' => 'cuve_stockage_1000l',
                'label' => "Cuve de stockage d'eau 1 000 L (mini château d'eau)",
                'category' => 'water_point',
                'min_xaf' => 50000,
                'max_xaf' => 160000,
                'source_name' => 'Camerbiz (Douala) / Jiji (Dakar, parité FCFA)',
                'source_url' => 'https://www.camerbiz.com/en/itm/c94a10356/cubitenaire-de-1000-litre-a-bon-prix',
                'observed_at' => '2026-11-02',
                'notes' => 'Min : Camerbiz Douala (marché Nkololoun), cubitenaire 1 000 L, 50 000 FCFA (annonce du 2021-02-05). Max : Jiji Dakar, cuve / réservoir 1 000 L importé, 90 000 – 160 000 F CFA (XOF, parité 1 XOF ≈ 1 XAF, à valider localement).',
            ],
            [
                'equipment_key' => 'bloc_latrines_vip',
                'label' => 'Bloc latrines VIP scolaire (4 – 6 cabines)',
                'category' => 'toilets_latrines',
                'min_xaf' => 3500000,
                'max_xaf' => 4290000,
                'source_name' => 'MINEPAT (Journal des Projets) / TGUP (Buea)',
                'source_url' => 'https://www.cvuc-uccc.com/national/images/JDP.18_Adamaoua.pdf',
                'observed_at' => '2026-11-02',
                'notes' => "Min : MINEPAT via CVUC, Journaux des Projets 2017-2018, construction de blocs latrines en écoles primaires : 3 500 000 FCFA (EP Doyang 2, EP Kourengue…). Max : TGUP, bloc 6 cabines à l'école primaire de Ndongo (Buea) : 7 146 USD ≈ 4 290 000 XAF (taux indicatif ~600). Complément : CDVTA, projet latrines VIP + formation dans 10 écoles, 16 650 USD par école.",
            ],
            [
                'equipment_key' => 'station_lavemains',
                'label' => 'Station de lavage des mains (seau à robinet / tippy-tap)',
                'category' => 'handwashing',
                'min_xaf' => 1200,
                'max_xaf' => 22800,
                'source_name' => 'PLOS Water via ScienMag (Zambie) / Akvopedia',
                'source_url' => 'https://scienmag.com/households-in-zambia-reveal-how-much-they-would-pay-for-handwashing-stations/',
                'observed_at' => '2026-11-02',
                'notes' => "Min : tippy-tap, matériaux achetés 2 – 4 USD ≈ 1 200 – 2 400 XAF (Akvopedia, dispositif promu par UNICEF/WaterAid). Max : station préfabriquée 38 USD ≈ 22 800 XAF ; seau à robinet sur support métallique 10 USD ≈ 6 000 XAF (étude PLOS Water à Lusaka, via ScienMag 2026-10-09). Taux indicatif ~600 XAF/USD. Sources internationales — à valider localement.",
            ],
        ];
    }
}

<?php

namespace Tests;

use Illuminate\Foundation\Testing\TestCase as BaseTestCase;

abstract class TestCase extends BaseTestCase
{
    /**
     * Force l'isolation SQLite des tests. Les conteneurs injectent de vraies
     * variables DB_* lues en priorité par Laravel via $_SERVER, que phpunit.xml
     * ne peut pas écraser : sans ceci, RefreshDatabase nettoie la base de dev.
     */
    public function createApplication()
    {
        $_SERVER['DB_CONNECTION'] = 'sqlite';
        $_SERVER['DB_DATABASE'] = ':memory:';

        return parent::createApplication();
    }
}

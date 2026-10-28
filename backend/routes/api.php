<?php

use App\Http\Controllers\Api\WashAgentController;
use App\Http\Controllers\Api\WashIncidentController;
use App\Http\Controllers\Api\WashReportController;
use App\Http\Controllers\Api\WashSchoolController;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;

Route::get('/user', function (Request $request) {
    return $request->user();
})->middleware('auth:sanctum');

Route::prefix('v1/wash')->group(function () {
    Route::get('/schools', [WashSchoolController::class, 'index']);
    Route::get('/schools/{school}', [WashSchoolController::class, 'show']);

    Route::get('/reports', [WashReportController::class, 'index']);
    Route::post('/reports', [WashReportController::class, 'store']);
    Route::get('/reports/{report}', [WashReportController::class, 'show']);

    Route::get('/incidents', [WashIncidentController::class, 'index']);
    Route::get('/incidents/{incident}', [WashIncidentController::class, 'show']);

    Route::post('/agent/chat', [WashAgentController::class, 'copilotChat']);
    Route::post('/agent/dispatch-plan', [WashAgentController::class, 'dispatchPlan']);
    Route::post('/agent/epidemic-scan', [WashAgentController::class, 'epidemicScan']);
    Route::post('/agent/synthesize', [WashAgentController::class, 'synthesize']);
    Route::get('/agent/schools/{school}/replace-vs-repair', [WashAgentController::class, 'replaceVsRepair']);

    Route::middleware('auth:sanctum')->group(function () {
        Route::post('/schools', [WashSchoolController::class, 'store']);
        Route::patch('/incidents/{incident}/status', [WashIncidentController::class, 'updateStatus']);
        Route::post('/incidents/{incident}/assign', [WashIncidentController::class, 'assign']);
        Route::post('/incidents/{incident}/override-priority', [WashIncidentController::class, 'overridePriority']);
        Route::post('/incidents/{incident}/maintenance-logs', [WashIncidentController::class, 'storeMaintenanceLog']);
    });
});

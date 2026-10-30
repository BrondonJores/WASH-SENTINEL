<?php

use App\Http\Controllers\Api\Admin\WashAiAnalysisController;
use App\Http\Controllers\Api\Admin\WashModelProfileController;
use App\Http\Controllers\Api\Admin\WashSttProfileController;
use App\Http\Controllers\Api\AuthController;
use App\Http\Controllers\Api\WashAgentController;
use App\Http\Controllers\Api\WashIncidentController;
use App\Http\Controllers\Api\WashProjectController;
use App\Http\Controllers\Api\WashConversationController;
use App\Http\Controllers\Api\WashNotificationController;
use App\Http\Controllers\Api\WashWhatsAppController;
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
    Route::post('/reports', [WashReportController::class, 'store'])->middleware('throttle:60,1');
    Route::get('/reports/{report}', [WashReportController::class, 'show']);

    Route::get('/overview', [WashIncidentController::class, 'overview']);
    Route::get('/incidents', [WashIncidentController::class, 'index']);
    Route::get('/incidents/{incident}', [WashIncidentController::class, 'show']);

    Route::post('/agent/chat', [WashAgentController::class, 'copilotChat']);
    Route::post('/agent/converse', [WashAgentController::class, 'converse'])->middleware('throttle:30,1');
    Route::post('/agent/dispatch-plan', [WashAgentController::class, 'dispatchPlan']);
    Route::post('/agent/epidemic-scan', [WashAgentController::class, 'epidemicScan']);
    Route::post('/agent/synthesize', [WashAgentController::class, 'synthesize']);
    Route::get('/agent/schools/{school}/replace-vs-repair', [WashAgentController::class, 'replaceVsRepair']);

    Route::middleware('auth:sanctum')->group(function () {
        Route::post('/schools', [WashSchoolController::class, 'store'])->middleware('permission:manage schools');
        Route::patch('/incidents/{incident}/status', [WashIncidentController::class, 'updateStatus'])->middleware('permission:update incident status');
        Route::post('/incidents/{incident}/assign', [WashIncidentController::class, 'assign'])->middleware('permission:assign incidents');
        Route::post('/incidents/{incident}/override-priority', [WashIncidentController::class, 'overridePriority'])->middleware('permission:override ai priority');
        Route::post('/incidents/{incident}/maintenance-logs', [WashIncidentController::class, 'storeMaintenanceLog'])->middleware('permission:update incident status');
        Route::get('/assignable-users', [WashIncidentController::class, 'assignableUsers'])->middleware('permission:assign incidents');
        Route::get('/library', [WashConversationController::class, 'library']);
        Route::apiResource('/projects', WashProjectController::class)->only(['index', 'store', 'update', 'destroy']);
        Route::post('/conversations', [WashConversationController::class, 'store']);
        Route::patch('/conversations/{conversation}', [WashConversationController::class, 'update']);
        Route::delete('/conversations/{conversation}', [WashConversationController::class, 'destroy']);
        Route::put('/conversations/{conversation}/messages', [WashConversationController::class, 'replaceMessages']);
    });
});

Route::prefix('v1/admin')->middleware(['auth:sanctum', 'permission:manage ai settings'])->group(function () {
    Route::get('/ai-analyses', [WashAiAnalysisController::class, 'index']);
    Route::get('/provider-types', [WashModelProfileController::class, 'providerTypes']);
    Route::apiResource('/model-profiles', WashModelProfileController::class)->parameters(['model-profiles' => 'modelProfile']);
    Route::post('/model-profiles/{modelProfile}/activate', [WashModelProfileController::class, 'activate']);
    Route::post('/model-profiles/{modelProfile}/test', [WashModelProfileController::class, 'test']);
    Route::get('/stt-types', [WashSttProfileController::class, 'sttTypes']);
    Route::apiResource('/stt-profiles', WashSttProfileController::class)->parameters(['stt-profiles' => 'sttProfile']);
    Route::post('/stt-profiles/{sttProfile}/activate', [WashSttProfileController::class, 'activate']);
    Route::post('/stt-profiles/{sttProfile}/test', [WashSttProfileController::class, 'test']);
});

Route::prefix('v1/notifications')->middleware('auth:sanctum')->group(function () {
    Route::get('/', [WashNotificationController::class, 'index']);
    Route::post('/read-all', [WashNotificationController::class, 'readAll']);
    Route::post('/{notification}/read', [WashNotificationController::class, 'read']);
});

Route::prefix('v1/whatsapp')->group(function () {
    Route::get('/webhook', [WashWhatsAppController::class, 'verify']);
    Route::post('/webhook', [WashWhatsAppController::class, 'receive'])->middleware('throttle:60,1');
});

Route::prefix('v1/auth')->group(function () {
    Route::post('/token', [AuthController::class, 'token'])->middleware('throttle:10,1');
    Route::delete('/token', [AuthController::class, 'destroy'])->middleware('auth:sanctum');
});

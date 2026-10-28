# WASH Sentinel 🛡️🚰

Plateforme IA pour le signalement, la priorisation et le suivi des pannes d'infrastructures WASH (Eau, Hygiène, Assainissement) dans les établissements scolaires.

## Architecture

Le projet est structuré en deux dossiers distincts :
- **`backend/`** :
  - **`ai-engine/`** : Microservice IA en FastAPI (Meta Llama 3.2 via Ollama, Embeddings vectoriels pour détection de doublons, Whisper.cpp pour la transcription vocale).
  - API REST Laravel 12 (PostgreSQL, Authentification, RBAC Spatie, Gestion des écoles, incidents et rapports).
- **`frontend/`** : Application Web React / Tailwind pour les signalements et le tableau de bord de maintenance.

## Démarrage rapide du moteur IA

```bash
cd backend/ai-engine
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Documentation interactive disponible sur `http://localhost:8000/docs`.
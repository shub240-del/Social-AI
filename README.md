# AI Social Media Content Platform Monorepo

> **Production Platform Repository — Version 17.0 (Dockerless Architecture & NVIDIA API Edition)**  
> Built according to approved Master System Specifications and Implementation Roadmap.

## Monorepo Layout

```
├── apps/               # Next.js Frontend Application
├── packages/           # Shared Python & TypeScript libraries
│   ├── ai_core/        # Provider Adapters, Router, Memory Client
│   ├── ai_agents/      # Multi-Agent Pipeline & Prompt Templates
│   └── shared_core/    # Exception Handling, NVIDIA AI Service Layer, Security & Logging
├── services/           # Backend Microservices
│   ├── api_gateway/    # FastAPI Core REST API Gateway
│   ├── identity_service/# Auth0, RBAC, Users & Workspaces
│   ├── workflow_engine/# Async Workers & Event Handlers
│   ├── publishing_service/# Social Media API Dispatchers
│   ├── analytics_service/# Performance Collectors
│   └── billing_service/# Usage Metering & Quotas
└── migrations/         # Alembic Database DDL Revisions
```

## Quick Start (Dockerless Local Environment)

### 1. Python Environment Setup
```powershell
# Create & activate Python virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install Python dependencies
pip install poetry
poetry install
```

### 2. Configure Environment Variables
Set database and NVIDIA API credentials in `.env`:
```ini
POSTGRES_HOST=localhost # or your Supabase host: xxxx.supabase.co
POSTGRES_PORT=5432
POSTGRES_DB=socialai
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_postgres_password

NVIDIA_API_KEY=nvapi-your-key-here
NVIDIA_API_BASE_URL=https://integrate.api.nvidia.com/v1
DEFAULT_LLM_MODEL=meta/llama-3.1-70b-instruct
```

### 3. Run Database Migrations
```powershell
# Execute Alembic DDL migrations against PostgreSQL / Supabase
python -m alembic upgrade head
```

### 4. Launch FastAPI Backend Server
```powershell
python -m uvicorn services.identity_service.main:app --host 127.0.0.1 --port 8000 --reload
```
- **API Base:** `http://127.0.0.1:8000`
- **Interactive Swagger Docs:** `http://127.0.0.1:8000/docs`
- **Health Check:** `http://127.0.0.1:8000/healthz`

### 5. Run Test Suite
```powershell
python -m pytest -v --cov=packages --cov=services
```

---

## Code Quality & CI Pipeline

- **Code Formatting & Linting:** `ruff check .`, `ruff format --check .`, `npx pyright`, and `mypy packages/ services/`.
- **CI Pipeline (`.github/workflows/ci.yml`):** Automated GitHub Actions verification running linting, static type checking, and Pytest unit test suite natively on every push without requiring Docker.

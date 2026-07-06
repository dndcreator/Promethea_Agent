# Real User Setup

This is the "send to users and sleep well" setup guide.
Goal: a new user can clone, configure, run, and chat in one pass.

## 0. What users need

- Python 3.10+
- a model API key
- optional: Neo4j (only if they keep memory backend as `neo4j`)

## 1. Clone and install

```bash
git clone https://github.com/dndcreator/Promethea_Agent.git
cd Promethea_Agent
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -r requirements.txt
```

macOS / Linux:

```bash
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 2. Create `.env` from template

Windows:

```powershell
copy env.example .env
```

macOS / Linux:

```bash
cp env.example .env
```

Then edit `.env`.

## 3. Fill only the actually required fields first

Minimum required set:

```bash
API__API_KEY=replace_with_your_key
API__BASE_URL=https://openrouter.ai/api/v1
API__MODEL=openai/gpt-4.1-mini
```

Important: these three must belong to the same provider account/environment.
If your key is DeepSeek but base URL is OpenRouter, it will fail (yes, even if the key is valid).

## 4. Memory backend choice (do this once)

### Option A: quick local run (recommended for first-time users)

```bash
MEMORY__ENABLED=true
MEMORY__STORE_BACKEND=sqlite_graph
```

No extra service needed.

### Option B: full Neo4j memory

```bash
MEMORY__ENABLED=true
MEMORY__STORE_BACKEND=neo4j
MEMORY__NEO4J__ENABLED=true
MEMORY__NEO4J__URI=bolt://127.0.0.1:7687
MEMORY__NEO4J__USERNAME=neo4j
MEMORY__NEO4J__PASSWORD=your_password
MEMORY__NEO4J__DATABASE=neo4j
```

If Neo4j is not reachable, service may still boot but memory features will degrade.

## 5. Start service

```bash
python start_gateway_service.py
```

Open:
- UI: `http://127.0.0.1:5173`
- health: `http://127.0.0.1:8000/health`

## 6. First-run verification checklist

1. `/health` returns 200.
2. `/api/status` returns tools and runtime status.
3. Send one message from UI and receive model response.
4. Send second message and verify memory behavior matches your backend expectation.

If all four pass, user-side setup is done.

## 7. Common issues (human version)

### 401 Missing Authentication header

Cause: `API__API_KEY` / `API__BASE_URL` / `API__MODEL` mismatch.
Fix: set all three in `.env` as one coherent provider set.

### UI keeps loading forever

Open browser console first. If there is JS syntax error, frontend build is broken locally.
If backend logs are clean and `/api/status` is 200, this is usually frontend-side issue.

### Playwright browser missing

If logs show `playwright install` hint:

```bash
playwright install
```

This affects browser controller only, not core chat pipeline.

### User config parse error (corrupt JSON)

Runtime now auto-heals corrupted user config by backing it up and recreating a valid one.
If you still see repeated errors, check file permissions of `config/users/`.

## 8. What to tell users before filing a bug

Ask for these three items:

1. startup log snippet (first 100 lines)
2. their `.env` key names (not values)
3. output of:

```bash
GET /health
GET /api/status
GET /api/health/memory
GET /api/ops/readiness
```

This cuts "it does not work" triage time by a lot.

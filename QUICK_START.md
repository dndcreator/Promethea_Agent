# Quick Start

This guide is for first-time local users who want to start Promethea with the Web UI.

Promethea's full experience uses Neo4j for graph memory. This guide keeps Neo4j on the main path and explains the setup in beginner-friendly steps.

## 0. Prerequisites

Install:

1. Python 3.10+
2. Node.js / npm
3. Neo4j Desktop or a Neo4j service

Run commands from the project root.

## 1. Start Neo4j

Promethea stores its full memory graph in Neo4j. Start Neo4j before creating your first Promethea account.

The easiest beginner path is Neo4j Desktop:

1. Download and install Neo4j Desktop from the Neo4j website.
2. Open Neo4j Desktop.
3. Create a local DBMS, or open an existing local DBMS.
4. Set a password you can remember. The default username is usually `neo4j`.
5. Start the DBMS and wait until Neo4j Desktop shows it as running.
6. Keep the default Bolt URI unless you changed it: `bolt://127.0.0.1:7687`.
7. Keep the default database name unless you changed it: `neo4j`.

### Neo4j checklist

Before starting Promethea, confirm:

- Neo4j Desktop shows the DBMS as running.
- You can open Neo4j Browser at `http://localhost:7474`.
- You can sign in to Neo4j Browser with username `neo4j` and the DBMS password you set.
- The Bolt URI is `bolt://127.0.0.1:7687`, unless you changed Neo4j ports manually.
- The same password is copied into `MEMORY__NEO4J__PASSWORD`.

You will need these values in `.env`:

```env
MEMORY__NEO4J__URI=bolt://127.0.0.1:7687
MEMORY__NEO4J__USERNAME=neo4j
MEMORY__NEO4J__PASSWORD=your_neo4j_password
MEMORY__NEO4J__DATABASE=neo4j
```

Common Neo4j first-run mistakes:

- Using the wrong password in `.env`. It must match the local DBMS password, not your Neo4j account password.
- Starting Neo4j Browser but not starting the DBMS.
- Changing the Bolt port in Neo4j, then leaving `.env` at `bolt://127.0.0.1:7687`.
- Leaving `MEMORY__NEO4J__PASSWORD` empty.

## 2. Install Python Dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

For development mode:

```powershell
pip install -e .
```

## 3. Configure `.env`

Create `.env` in the project root. You can copy `env.example`.

Minimum usable configuration:

```env
API__API_KEY=your_api_key
API__BASE_URL=https://your-provider.example/v1
API__MODEL=your_model_name
```

Use the base URL and model name from your own provider. See
[docs/configuration.md](docs/configuration.md) for OpenRouter, OpenAI-compatible,
local-model, and Azure examples.

Add the Neo4j memory settings:

```env
MEMORY__ENABLED=true
MEMORY__STORE_BACKEND=neo4j
MEMORY__NEO4J__ENABLED=true
MEMORY__NEO4J__URI=bolt://127.0.0.1:7687
MEMORY__NEO4J__USERNAME=neo4j
MEMORY__NEO4J__PASSWORD=your_neo4j_password
MEMORY__NEO4J__DATABASE=neo4j
```

If Neo4j is selected but unreachable, Promethea will still start, but account registration is intentionally blocked with a clear message instead of silently falling back to another backend. This protects the full graph-memory experience from accidentally running in a reduced mode.

## 4. Start Backend and Web UI

```powershell
python start_gateway_service.py
```

The startup script will:

- start the backend on `http://127.0.0.1:8000`
- start the Vite Web UI on `http://127.0.0.1:5173`
- install UI dependencies automatically if `UI/node_modules` is missing
- open the browser automatically when possible

Open:

- Web UI: `http://127.0.0.1:5173`
- API status: `http://127.0.0.1:8000/api/status`

If you want to skip the Web UI:

```powershell
$env:PROMETHEA_SKIP_UI="1"
python start_gateway_service.py
```

## 5. Create an Account

1. Open the Web UI.
2. Register a user.
3. Log in.
4. Send a test message.

If registration says Neo4j is unavailable, either:

- confirm Neo4j is running;
- confirm the Bolt URI is `bolt://127.0.0.1:7687` unless you changed it;
- confirm `MEMORY__NEO4J__USERNAME`, `MEMORY__NEO4J__PASSWORD`, and `MEMORY__NEO4J__DATABASE` match your Neo4j DBMS.

## 6. Optional CLI Setup

The CLI is the reference client for the runtime API.

```powershell
pip install -e .
promethea --help
```

Common commands:

```powershell
promethea auth register <username> <password>
promethea auth login <username> <password>
promethea auth whoami
promethea status base
promethea chat send "hello"
promethea ask "hello"
promethea workflow list
promethea memory graph
promethea ops capabilities
promethea ops protocol
promethea ops framework-check
promethea ops surfaces
```

## 7. Verify Memory

Memory verification is optional.

1. Chat for several turns with stable facts, preferences, goals, or constraints.
2. Ask follow-up questions that should require recall.
3. Inspect memory through the UI or API.

Memory health:

```powershell
curl http://127.0.0.1:8000/api/health/memory
```

## 8. Verify User Isolation

1. Create user A and write a visible fact.
2. Log out.
3. Create or log in as user B.
4. User B should not see user A's sessions, memory, files, or logs.

Runtime user data is stored under `config/users/` and is ignored by git.

## Troubleshooting

### `API key is not configured`

Check `API__API_KEY` in `.env`.

### The UI opens but chat fails

Check:

- `API__API_KEY`
- `API__BASE_URL`
- `API__MODEL`

The Web UI can start without a working model provider, but chat needs a valid OpenAI-compatible API endpoint.

### `npm was not found`

Install Node.js, reopen PowerShell, and run again:

```powershell
python start_gateway_service.py
```

### `Memory system not enabled`

Check:

- `MEMORY__ENABLED`
- `MEMORY__STORE_BACKEND`
- `MEMORY__NEO4J__ENABLED`
- Neo4j URI, username, password, and database name

### Neo4j connection failed

Check:

1. Neo4j is running.
2. Bolt URI is correct, usually `bolt://127.0.0.1:7687`.
3. Username, password, and database are correct.

### I only want a temporary no-Neo4j fallback

Neo4j is the recommended full path. If you only need a temporary degraded local run, you can set `MEMORY__STORE_BACKEND=sqlite_graph` and `MEMORY__NEO4J__ENABLED=false`, then restart Promethea. Switch back to `neo4j` for the intended graph-memory experience.

## More Docs

- [RELEASE_NOTES.md](RELEASE_NOTES.md)
- [docs/ui-overview.md](docs/ui-overview.md)
- [docs/configuration.md](docs/configuration.md)
- [docs/testing-strategy.md](docs/testing-strategy.md)

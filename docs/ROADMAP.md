# Eye of Ender — Build Roadmap

> Ask questions about your data in plain English. Get back the answer, the table, a chart, and the SQL that produced it.
> A self-hosted take on Databricks Genie.

This file is our map. We build Eye of Ender in **14 steps** (Step 0 → Step 13). Every step has a **Goal**, a **Build** list, and a **Done when** checklist. We finish and test one step before starting the next.

Current status: see the [Progress tracker](#progress-tracker) at the bottom.

---

## 1. What we are building

A user opens a **Space** (a curated workspace around a set of data) and asks something like:

> *"Top 5 products by revenue last quarter in Gujarat?"*

Eye of Ender then:

1. understands the question, including follow-ups like *"now only March"*,
2. finds the right tables, columns, and business rules (RAG),
3. writes SQL for the right engine,
4. checks the SQL is safe, runs it, and repairs it by itself if it fails,
5. answers in plain words, with the result table, a chart, and the SQL it used.

### Genie features we match

| Databricks Genie | Eye of Ender |
|---|---|
| Genie spaces with curated tables | **Spaces**: data sources + instructions grouped per topic |
| Natural language → SQL → results | Same, plus a self-repair loop |
| Follow-up questions | Conversation memory + question rewriting |
| Automatic visualizations | A chart picked for every answer (bar, line, area, pie, scatter, KPI, table) |
| Instructions, example SQL, trusted assets | **Knowledge**: instructions, example SQL, glossary, documents; **Trusted** badge |
| Column descriptions, synonyms, entity matching | Auto-profiling + editable descriptions/synonyms + value index |
| Thumbs up / down | Feedback; editors promote good answers to example SQL |
| Benchmarks | Benchmark sets with an accuracy score per space |

### Data we can analyse

| Source | Example | How we read it | Where the SQL runs |
|---|---|---|---|
| **Uploaded files** | `sales.csv`, `.xlsx`, `.parquet`, `.json` | Validated, converted to Parquet, profiled | DuckDB |
| **Delta tables (by path)** | `C:/data/orders_delta`, `s3://bucket/orders` | DuckDB `delta` extension (`delta_scan`), tested on this machine | DuckDB |
| **Delta tables (Unity Catalog)** | `main.sales.orders` | Databricks SQL Warehouse via `databricks-sql-connector` | Databricks |
| **UC Volumes** | `/Volumes/main/raw/landing/leads.csv` | Browse with `databricks-sdk` Files API. Small tabular files → DuckDB. Large ones → `read_files()` on the warehouse. Documents → RAG | DuckDB or Databricks |
| **Documents** (uploaded or from a volume) | `metric_definitions.pdf` | Chunked and embedded into pgvector | RAG (no SQL) |

- Unity Catalog and UC Volumes need a Databricks workspace (host, token, SQL warehouse). Everything else works without Databricks.
- One question runs on one engine. Joining a Databricks table with a local file in one query is a later idea (section 8).

---

## 2. How it works

```
Browser ── React + Vite + Motion   (Spaces · Chat · Results · Charts · Settings)
   │
   │  REST + live events (Server-Sent Events)
   ▼
FastAPI backend
   ├── Genie engine:  rewrite → route → retrieve → write SQL → guard → run → repair → explain
   │      │
   │      ├── LLM gateway:  OpenRouter keys 1→2→3→4  ──(all failing)──▶  Groq keys 1→2→3→4
   │      │
   │      ├── RAG:  chunk · embed · hybrid search (vector + keyword) · rerank
   │      │           └── PostgreSQL 18 + pgvector
   │      │
   │      └── Query engines
   │             ├── DuckDB      → uploaded files, Delta tables by path, small UC Volume files
   │             └── Databricks  → Unity Catalog Delta tables, large UC Volume files
   │
   └── Auth · Spaces · Data sources · Knowledge · Chat · Benchmarks · Admin
```

Two databases, two different jobs:

- **PostgreSQL** is the app's own memory: users, spaces, chats, knowledge, embeddings (pgvector), full-text index. Generated SQL **never** runs against it.
- **DuckDB / Databricks** is where the user's data lives and where generated SQL runs.

---

## 3. Tech stack

### Backend

| Part | Choice | Why |
|---|---|---|
| Language | Python 3.12 in `.venv` | Installed and stable |
| API | FastAPI + Uvicorn | Async, typed, auto docs at `/docs` |
| Settings | pydantic-settings | `.env` is typed and checked at startup |
| App database | PostgreSQL 18.4 + pgvector 0.8.6 + pg_trgm | Already installed here. Vectors, full-text, and fuzzy match in one DB |
| ORM / migrations | SQLAlchemy 2 (async, asyncpg) + Alembic | Standard, reliable |
| Query engine | DuckDB 2.0 + `delta` extension | Fast analytics over files and Delta. Tested here |
| Delta | `deltalake` (delta-rs) | Delta metadata, versions, test tables |
| Databricks | `databricks-sql-connector` + `databricks-sdk` | UC tables via SQL Warehouse, Volumes via Files API |
| SQL safety | `sqlglot` | Parse, validate, add `LIMIT`, translate dialects |
| LLM client | `openai` SDK pointed at OpenRouter and Groq | Both are OpenAI-compatible, so one code path |
| Embeddings + rerank | `fastembed` (ONNX, CPU) | Runs locally: free, no PyTorch, uses no API quota |
| Documents | `pypdf`, `python-docx` | Text from PDF / DOCX |
| Streaming | SSE (`sse-starlette`) | Live "thinking steps" in the UI |
| Auth | JWT (`pyjwt`) + Argon2 (`pwdlib`) | Secure passwords and sessions |
| Quality | `pytest`, `pytest-asyncio`, `respx`, `ruff` | Tests, HTTP mocks, lint + format |

### Frontend

| Part | Choice |
|---|---|
| Build | Vite + React + TypeScript (latest stable at Step 10) |
| Styling | Tailwind CSS + CSS variables (design tokens for light / dark) |
| Animation | **Motion**: `npm install motion`, import from `motion/react` |
| Design system | **UI UX Pro Max** skill for Claude Code |
| Server data | TanStack Query |
| Result tables | TanStack Table + TanStack Virtual (large results stay smooth) |
| Charts | Recharts |
| SQL viewer | CodeMirror 6 |
| UI primitives | Radix UI (unstyled and accessible, so the look is ours) |
| Icons | lucide-react |
| Routing | React Router |

> **Note on `npx motion`:** the `motion` package on npm (v14.6.0, by motiondivision) does not include a command-line tool, so `npx motion` has nothing to run. `npm install motion` is all we need.

---

## 4. Key design decisions

### 4.1 LLM gateway: 4 OpenRouter keys, then 4 Groq keys

Every LLM call follows this order:

```
OpenRouter key 1 → 2 → 3 → 4      (round-robin start, skips keys that are resting)
        │  every key resting or failing
        ▼
Groq key 1 → 2 → 3 → 4
        │  every key failing
        ▼
Clear message to the user: "AI service is busy, try again in N seconds"
```

What happens on each result:

| Result | What we do with that key | Then |
|---|---|---|
| Success | Nothing | Return the answer |
| `429` rate limit | Rest the key (use `Retry-After`, else 60 s, doubling on repeat) | Try the next key immediately |
| `401` / `403` invalid key | Disable the key until restart, log a warning (key masked) | Next key |
| `402` no credits (OpenRouter) | Rest the key for 1 hour | Next key |
| `404` "No endpoints found matching your data policy" (OpenRouter) | That account blocks free endpoints in its privacy settings. Disable the key until restart and log how to fix it | Next key |
| `5xx`, timeout, network error | Count the failure, short backoff | Next key |
| `400` bad request (e.g. prompt too long) | The key is fine | Don't rotate keys, because every key would fail. Shrink the prompt or try the next model |

More rules:

- **Round-robin:** each new request starts at the next key, so the load spreads over all 4 keys instead of burning key 1 first.
- **Two model tiers per provider:** **smart** (writing and repairing SQL) and **fast** (rewriting questions, routing, summaries, titles).
- The `openai` SDK's own retries are switched off (`max_retries=0`), so the key pool is the only retry logic.
- **Streaming:** we can switch key or provider only **before the first token**. Once text is streaming, a failure ends that answer with a clear error.
- **At startup**, every configured model ID is checked against the provider's `/models` list. Wrong IDs are reported clearly.
- Keys are never logged. They appear masked, like `sk-or-…a1b2`. Every call is recorded (provider, key number, model, tokens, time, status) in an `llm_calls` table. An admin page shows the health of each key.

Keys live in `.env` as `OPENROUTER_API_KEY_1` … `_4` and `GROQ_API_KEY_1` … `_4`. To add a 5th key later, add `_5`; no code change is needed.

Models: **free tiers only**. Chosen on 2026-10-26 from OpenRouter's live list of 17 free models and Groq's free plan:

| Provider | Smart (tried in order) | Fast (tried in order) |
|---|---|---|
| OpenRouter | `thinkingmachines/inkling:free`, then `nvidia/nemotron-3-ultra-550b-a55b:free` | `thinkingmachines/inkling-small:free`, then `nvidia/nemotron-3.5-lightning:free` |
| Groq | `openai/gpt-oss-120b` | `openai/gpt-oss-20b` |

Why these:

- **Inkling** (975B total / 41B active) is the strongest free model on OpenRouter. It scores 41 on the Artificial Analysis Intelligence Index, about 3 points above **Nemotron 3 Ultra** (550B / 55B active), which is its backup.
- **Inkling Small** (276B / 12B active, index 26, about 190 tokens/s) handles the quick jobs. **Nemotron 3.5 Lightning** (30B / 3B active, very fast) is its backup.
- **Groq:** `gpt-oss-120b` and `gpt-oss-20b` are the production models on Groq's free plan. Groq's Qwen model is "preview" (it can be retired at short notice) and Llama 3.3 70B was retired in August 2026, so we use neither.
- Free model lists change often. The startup check catches a removed model, and changing a model is a one-line edit in `.env`.

Free-tier facts that shape the code:

- **Limits are per account, not per key.** OpenRouter allows about 20 requests/minute and 50 requests/day per account (1,000/day once the account has bought $10 of credits at any time). Groq's limits are per organization and per model: about 30 requests/minute, 1,000 requests/day, and 8,000 tokens/minute. **So the 4 keys only add capacity if they come from 4 different accounts.**
- **One question costs about 3 LLM calls** (rewrite, SQL, explain), more if the SQL needs repair. 50 requests/day is roughly 15 questions per OpenRouter account per day.
- **Small prompts.** Groq's 8,000 tokens/minute means RAG sends only the most relevant schema cards, never the whole schema. Target: at most 6,000 prompt tokens.
- **Structured output through tool calling.** The free OpenRouter models above support tool calling but not `response_format`, so the gateway gets JSON back through a tool call, which works on every chosen model, and validates it with Pydantic.
- **Reasoning models.** All four OpenRouter models "think" before answering. The fast tier asks for low reasoning effort to stay quick.
- **Privacy.** Free endpoints may log prompts or use them for training. Prompts contain table and column names, sample values, and result rows, so don't use free models with confidential data. If an OpenRouter account has free endpoints switched off in its privacy settings, requests fail with "No endpoints found matching your data policy". Turn them on at openrouter.ai/settings/privacy.

### 4.2 RAG and chunking

No single chunking method is best for every kind of content. So we **chunk by content type**:

| Content | How we chunk it | Why |
|---|---|---|
| Table schema | 1 **table card** per table (name, description, columns, row count, keys) + 1 **column card** per column (`table.column`, type, description, synonyms, sample values) | The column is the unit we need to find. Cutting by characters would split schemas in half |
| Example SQL | 1 chunk per question → SQL pair. We embed the **question** | We search for "a similar question asked before" |
| Instructions, glossary | 1 chunk per rule / term | Short and self-contained |
| Column values | Not embedded. Distinct values of text columns (1 to 1,024 distinct, each up to 127 characters, the same limits as Genie's entity matching) go into a `pg_trgm` fuzzy index | Matches the typo "Gujrat" to `'Gujarat'`. It cannot turn "Gujarat" into the code `'GJ'`: that is what column descriptions, synonyms and the common values shown to the AI are for |
| Documents (PDF, DOCX, PPTX, XLSX, HTML, MD, TXT) | **The document pipeline below** | |

**The document pipeline.** These settings are fixed by the project owner; Step 6 must follow them. The "How we do it" column is how each one is implemented:

| Stage | Setting | How we do it |
|---|---|---|
| **Parsing** | Convert to Markdown, keep headings and tables | Every format becomes Markdown first. The converter (MarkItDown or Docling) is chosen in Step 6 by testing both on real PDFs; Docling is stronger on tables and complex layouts, MarkItDown is lighter. Tables stay Markdown tables. |
| **Splitting** | By section first, then recursive | Split on headings. A section that fits stays whole. A section that is too long is split recursively: paragraphs → lines → sentences → words. A code block is never split; a long table is split by rows, repeating the header row in every piece. |
| **Chunk size** | About 512 tokens (try 256–1024) | Measured with the **embedding model's own tokenizer**. Important: `bge-small-en-v1.5` reads at most **512 tokens** and silently cuts off the rest, so the context header plus the chunk text must fit inside 512 (about 450 tokens of text). Sizes above that need a long-input embedder, such as `jinaai/jina-embeddings-v2-small-en` (local, 8,192 tokens). Step 12 benchmarks 256 / 512 / 1024 and keeps the winner. |
| **Overlap** | 0–50 tokens | 40 tokens by default, and only between pieces of the same section. Separate sections never overlap, because the heading already marks the boundary. |
| **Context** | Title + section path, or an LLM-written summary | Every chunk is embedded with a header like `Sales Policy 2025 › Discounts › Regional rules`, so "this applies from Q2" stays findable. An LLM-written 1–2 sentence summary per chunk is available behind a setting, off by default, because on free tiers it would use up the daily LLM quota while documents are being processed. |
| **Index** | Hybrid: vector + BM25, with metadata | Vectors in pgvector (HNSW, cosine) plus **true BM25** keyword ranking (`bm25s`; Postgres' built-in text ranking isn't real BM25). Metadata on every chunk: space, source, document, content type, section path, page, and updated time. Filters (e.g. "only this space") apply before ranking. |
| **Retrieval** | Top 20–50, rerank to top 5–10 | Take the top 40 from vector search and the top 40 from BM25 → merge with Reciprocal Rank Fusion → rerank the best 30 with a local cross-encoder → keep the 5–10 that score above a threshold. Neighbouring pieces of the same section are joined back together before going to the LLM. |

```
question ─┬─▶ vector search (pgvector, top 40) ─┐
          └─▶ BM25 search   (bm25s,   top 40) ─┴─▶ Reciprocal Rank Fusion
              ─▶ rerank best 30 (local cross-encoder) ─▶ keep 5–10 ─▶ LLM
```

The same hybrid retrieval serves every content type (schema cards, example SQL, instructions, documents).

- **Why hybrid:** vectors find meaning ("revenue" ≈ "sales amount"). Keywords find exact names (`cust_id`, `SKU-1043`) that vectors often miss.
- **Embeddings:** `BAAI/bge-small-en-v1.5` (384 dimensions, 67 MB) via fastembed, running locally on the CPU: no API calls, no quota, and the data never leaves the machine. On this machine it was compared with 3 other small local models on 15 sample questions (indicative only). It was the most accurate at finding the right column (12/15 first choice, 13/15 in the top 3) at about 12 ms per question. Switching models later requires re-indexing.
- **Why not "semantic chunking"** (splitting where embedding similarity drops)? It costs an embedding per sentence at ingestion, and published comparisons have not shown it consistently beating good recursive chunking. We can add it later behind a flag and measure it with the Step 12 benchmarks.

### 4.3 From question to answer (the Genie engine)

```
1. Rewrite    "and in March?"  →  "Total revenue by product in March 2025, Gujarat"       (fast model)
2. Route      data question │ document question │ needs clarification │ out of scope
3. Retrieve   tables + columns, example SQL, instructions, glossary, matching values      (RAG)
4. Write SQL  in the right dialect (DuckDB or Databricks SQL), with a short plan          (smart model)
5. Guard      parse with sqlglot; it must pass every safety rule in 4.4
6. Run        with a timeout and a row limit
7. Repair     on error, send the error back to the model; at most 3 tries
8. Explain    plain-language answer, chart choice, 3 follow-up suggestions                (fast model)
9. Save       message, SQL, result preview, chart, timings, model and key number used
```

- Each stage sends a live event to the UI ("Finding tables…", "Writing SQL…", "Running…"), so the user sees progress, not just a spinner.
- If a **trusted** example SQL was used (as written, or with parameters filled in), the answer gets a **Trusted** badge, like Genie.
- If the question is ambiguous (e.g. "show sales" with three sales tables and no rule for which), it asks one short clarifying question instead of guessing.

### 4.4 Safety rules for generated SQL

- Exactly **one** statement, and it must be `SELECT` or `WITH … SELECT`. Blocked: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `DROP`, `CREATE`, `ALTER`, `ATTACH`, `COPY`, `PRAGMA`, `SET`, `INSTALL`, `LOAD`, `CALL`.
- Only tables registered in the current space. No file-reading functions (`read_csv`, `read_parquet`, `delta_scan`, `read_files`, …) inside generated SQL.
- `LIMIT` is added if missing. The UI shows up to 1,000 rows; downloads are capped at 10,000.
- A timeout on every query (default 60 s).
- **DuckDB:** a fresh in-memory connection per question that only sees that space's views, with file access locked down (exact DuckDB settings verified in Step 4).
- **Databricks:** use a token whose user or service principal has `SELECT`-only grants.
- **Uploads:** size limit, extension and content checks, stored under random file names.

### 4.5 Frontend design rules (so it doesn't look vibe-coded)

1. **Design system first.** In Step 10 we use UI UX Pro Max to choose one palette, one font pairing, a spacing scale, and a radius scale, and save them in `frontend/DESIGN.md`. Every screen uses only those tokens.
2. **Tokens, not hard-coded colors.** `--bg`, `--surface`, `--border`, `--text`, `--text-muted`, `--accent`, `--danger`, … each with a light and a dark value. Theme options: System / Light / Dark, saved per user and applied before first paint (no white flash).
3. **Restraint.** One accent color. No purple-to-blue gradients, no glow on everything, no emoji as icons, no random shadows. Consistent 4 px spacing grid.
4. **Motion with a purpose.** 150–300 ms, ease-out, animate only `transform` and `opacity`. Used for messages arriving, step progress, panels opening, and switching between chart and table. Off for users with `prefers-reduced-motion`.
5. **Every screen has 4 states:** loading (skeleton), empty (says what to do next), error (says how to fix it), and filled.
6. **Keyboard and accessibility:** visible focus rings, Enter to send and Shift+Enter for a new line, Esc to close, Ctrl/⌘+K for quick search, WCAG AA contrast in both themes.
7. **Few screens, done well:** Sign in · Spaces · Chat · Space settings (Data, Knowledge, Benchmarks) · Settings. Nothing more in v1.

Brand: "Eye of Ender" stays subtle, with a dark "End" palette and one teal-green accent. The final palette is chosen in Step 10.

---

## 5. Folder structure

```
Enderman/                     project root
├── .venv/                    Python virtual environment (not in git)
├── .claude/                  Claude Code skills (UI UX Pro Max)
├── backend/
│   ├── app/
│   │   ├── main.py           app factory, routers, middleware
│   │   ├── core/             config, logging, security, errors
│   │   ├── db/               session, base, models/
│   │   ├── api/v1/           auth, spaces, sources, knowledge, chat, benchmarks, admin, health
│   │   ├── schemas/          Pydantic request / response models
│   │   ├── llm/              key_pool, providers, gateway, prompts/
│   │   ├── connectors/       files, delta_path, unity_catalog, uc_volumes
│   │   ├── engine/           duckdb_engine, databricks_engine, sql_guard
│   │   ├── rag/              chunking/, embeddings, store, retriever, reranker, ingest
│   │   ├── genie/            pipeline, rewrite, router, schema_linker, sql_writer, repair, explain, charts
│   │   └── services/         business logic used by the routes
│   ├── alembic/              database migrations
│   ├── tests/
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/                 React app (built alongside the backend)
│   ├── DESIGN.md             design system: tokens, type, motion, components
│   └── src/
│       ├── components/       app shell + base components (ui/)
│       ├── features/         one folder per area: status/, playground/, later spaces/, chat/ …
│       ├── lib/              API client, SSE reader, theme, formatting
│       └── styles/           Tailwind + design tokens
├── data/                     uploads, Parquet files, caches (not in git)
├── docs/
│   └── ROADMAP.md            this file
├── .env                      your secrets (not in git)
├── .env.example              template for .env
└── README.md
```

---

## 6. The steps

### Step 0 — Project setup

**Goal:** the machine and the project are ready.

**Build**
- [x] Python virtual environment `.venv` (Python 3.12.10)
- [x] Checked: PostgreSQL 18.4 runs on `localhost:5432` with pgvector 0.8.6 and pg_trgm available
- [x] Checked: DuckDB 2.0 reads Delta tables on this machine
- [x] `.gitignore`, `.env.example`, `.env`, `README.md`, this roadmap, `git init`
- [ ] **You:** add the 4 OpenRouter keys and the 4 Groq keys to `.env`
- [ ] **You:** set up the database with one command (below)
- [ ] **You:** install the UI UX Pro Max skill (commands below)
- [ ] Recommended: move the project out of OneDrive (note below)

**Where the database is: one line in `.env`.**

```
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE
```

For example `postgresql://postgres:your-password@localhost:5432/eyeofender`. `postgres://` works too. If the password contains special characters, URL-encode them (`@` → `%40`, `:` → `%3A`, `/` → `%2F`, `#` → `%23`, `%` → `%25`). The app, Alembic, the setup script, and the tests all read this one line. Tests always switch to a separate database on the same server, `eye_of_ender_test`, and refuse to run against anything else. The old separate `POSTGRES_*` lines still work when `DATABASE_URL` is empty.

**Set up the database (recommended way).** In PowerShell or the VS Code terminal, from the `backend` folder with `.venv` active:

```powershell
python scripts/setup_database.py
```

It asks once for the `postgres` password, the one you chose when installing PostgreSQL (pgAdmin asks for the same one). That password is never shown or saved. If `DATABASE_URL` already logs in as `postgres`, it uses that password instead of asking. Then it:

1. creates the app's own login `eoe_app` with a new random password, or resets it if it exists,
2. creates the app database (the name in `DATABASE_URL`, default `eye_of_ender`) and `eye_of_ender_test`, both owned by `eoe_app`,
3. installs pgvector and pg_trgm in both, and hands any existing tables over to `eoe_app`,
4. writes `DATABASE_URL` (now with `eoe_app`) into `.env`, changing nothing else,
5. creates the tables (`alembic upgrade head`) and runs the health checks.

It is safe to run again; each run gives `eoe_app` a fresh password and saves it. Afterwards, restart the backend, because it reads `.env` only when it starts.

<details>
<summary>Manual way (psql), if you prefer</summary>

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost
```

```sql
CREATE ROLE eoe_app LOGIN PASSWORD 'choose-a-strong-password';
CREATE DATABASE eye_of_ender OWNER eoe_app;
CREATE DATABASE eye_of_ender_test OWNER eoe_app;
\c eye_of_ender
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
\c eye_of_ender_test
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
\q
```

The extensions must be created by `postgres`, because pgvector is not a "trusted" extension. Then put `DATABASE_URL=postgresql://eoe_app:the-same-password@localhost:5432/eye_of_ender` into `.env`, and run `alembic upgrade head`.
</details>

**Install UI UX Pro Max.** Inside the Claude Code chat:

```
/plugin marketplace add nextlevelbuilder/ui-ux-pro-max-skill
/plugin install ui-ux-pro-max@ui-ux-pro-max-skill
```

Or, in a terminal in the project folder: `npx uipro-cli init --ai claude`. Restart Claude Code afterwards.

**OneDrive note.** This project is inside OneDrive. `.venv` and `node_modules` hold tens of thousands of files, and OneDrive tries to sync all of them. That slows everything down and can lock files during installs. Best fix: move the project to a folder like `C:\dev\eye-of-ender`, then recreate the venv with `python -m venv .venv` (a venv cannot be moved).

**Done when:** `.env` has the keys, and the setup script ends with "All set" (all four health checks ok).

---

### Step 1 — Backend foundation

**Goal:** a running FastAPI app with config, logging, a database connection, and migrations.

**Build**
- [x] `backend/requirements.txt` + `requirements-dev.txt` (pinned versions), installed into `.venv`
- [x] `core/config.py`: typed settings. If something required is missing, the app refuses to start and says exactly what
- [x] Logging with a request ID on every line (readable in development, JSON in production); one JSON error format for every error
- [x] Async SQLAlchemy engine and session, Alembic, first migration (`0001`: pgvector + pg_trgm)
- [x] `GET /api/v1/health` → app, PostgreSQL, pgvector, and pg_trgm status (503 if anything is down)
- [x] CORS for the frontend dev server; pytest with a separate test database

**Test database:** `eye_of_ender_test` is created by the Step 0 setup script, along with the main database.

**When the database is not ready**, the app says so instead of failing silently:
- `GET /api/v1/health` has four checks: PostgreSQL, pgvector, pg_trgm, and **tables** (are migrations up to date?).
- Any request that needs the database answers `503` with the code `database_unavailable` (can't connect: wrong login, server stopped, database missing) or `database_not_ready` (tables missing or out of date), plus the exact fix. Production hides the details.
- The web app shows a "Can't connect to the database" page with the reason and the fix steps, and recovers by itself (it checks every 5 seconds) once the backend is restarted with a working login.

**Run it** (from the `backend` folder, with `.venv` active):

```powershell
alembic upgrade head              # apply migrations to eye_of_ender
uvicorn app.main:app --reload     # http://127.0.0.1:8000/docs
pytest                            # all tests (uses eye_of_ender_test)
pytest -m "not db"                # only tests that don't need PostgreSQL
ruff check . ; ruff format --check .
```

**Done when:** `uvicorn app.main:app --reload` runs, `/docs` opens, `/api/v1/health` reports the database OK, `pytest` passes, and `ruff check` is clean.

---

### Step 2 — LLM gateway (OpenRouter ×4 → Groq ×4)

**Goal:** one `llm.complete(...)` / `llm.stream(...)` interface. The rest of the code never cares which key or provider answered.

**Build**
- [x] A key pool per provider: round-robin plus the rest/disable rules from 4.1 (`app/llm/key_pool.py`)
- [x] Provider clients (OpenAI SDK, base URL per provider, SDK retries off, timeouts)
- [x] Smart and fast tiers; structured output through a `submit` tool call (forced only where the model supports `tool_choice`), JSON-in-text accepted as a fallback, validated with Pydantic, one retry; low reasoning effort for the fast tier
- [x] A prompt-size check per provider (Groq's free plan allows 8,000 tokens/minute)
- [x] Streaming with failover before the first chunk
- [x] Model check in the background at startup; `llm_calls` table (migration `0002`); `GET /api/v1/admin/llm/status` (keys masked)
- [x] `POST /api/v1/admin/llm/playground`: streams a test answer as Server-Sent Events
- [x] Tests against a fake provider: a `429` moves to the next key, all OpenRouter keys down → Groq, invalid and data-policy keys are disabled, a `400` doesn't rotate keys, structured output, streaming, model check
- [x] **Frontend** (built with this step): System status page and Playground page

Since Step 3, the admin routes require a signed-in admin.

**Test it yourself:** start the backend and the frontend (README), open http://localhost:5173.
- **System status** shows every key (masked) as Ready / Resting / Disabled, and whether each model is still offered.
- **Playground** sends a prompt and shows which provider, model, and key answered. Run it a few times: the key number changes, because keys take turns.

**Done when:** the tests pass, and real answers come back through the Playground from OpenRouter and from Groq (put only Groq keys in `.env` once to see the fallback).

---

### Step 3 — Users and auth

**Goal:** secure sign-in and roles.

**Build**
- [x] **No public sign-up.** The first visit creates the admin account (`/setup`); after that, only admins add people (`/api/v1/users`)
- [x] Roles: **admin** (everything), **editor** (sets up spaces, from Step 4), **viewer** (asks questions)
- [x] Passwords: Argon2id, at least 10 characters, not the email address. Hashing runs off the event loop
- [x] Sessions: access token (signed JWT, 15 min) kept only in browser memory + refresh token in an httpOnly, SameSite=Strict cookie (7 days) that is replaced on every use and stored only as a hash
- [x] Theft detection: if a replaced refresh token is used again later, the whole session is revoked. A reuse within 30 seconds is treated as two tabs racing, not theft
- [x] Instant lock-out: changing a password or turning a user off ends their sessions immediately (token version)
- [x] Sign-in protection: 5 failed tries per email or 30 per IP in 15 minutes, then a pause. Unknown emails take the same time as wrong passwords, and get the same message
- [x] Admin tools (System status, Playground) now require an admin, so they work in production too
- [x] **Frontend:** Setup, Sign in, Account (profile + change password), Users (add, change role, set password, turn off/on), role-based menu, quiet token refresh, "No access" page
- [x] Tests: 22 backend sign-in/security tests + 4 frontend token-refresh tests + an end-to-end browser run of the whole flow (9 checks)

**Try it:** open http://localhost:5173. The first time, it asks you to create the admin account.

**Done when:** tests cover login, refresh rotation, wrong password, and role checks.

---

### Step 4 — Spaces and data sources

**Goal:** create a space and attach data to it.

**Build**
- [x] Spaces CRUD + members (editor / viewer per space). Admins see every space and act as editors; people who aren't members get "not found", so a space's existence isn't revealed. A space always keeps at least one editor
- [x] **Uploaded files:** CSV / TSV / Excel / Parquet / JSON / JSON Lines → size and type check → converted to Parquet (zstd) in `data/spaces/<space>/` under a random file name → a table in the space. The table name comes from the file name (or is typed in) and must be a safe SQL name
- [x] **Delta by path (local):** register a Delta folder inside `DATA_DIR` or `LOCAL_DATA_ROOTS` → `delta_scan` view, showing the Delta version. Deleting a space never touches a Delta folder
- [x] DuckDB engine: a fresh in-memory connection per query that sees only the space's views; then file access is limited to exactly those files/folders, external access is turned off, and the settings are locked. Time limit (`QUERY_TIMEOUT_SECONDS`) and row limit (`QUERY_MAX_ROWS`)
- [x] SQL guard (sqlglot): exactly one read-only query, only the space's tables, no file-reading or system functions. Tested on its own, and the DuckDB lock-down is tested as if the guard were bypassed
- [x] Engine API: `POST /api/v1/spaces/{id}/query` (editors; viewers will ask through the AI from Step 7), table preview (first 50 rows), `GET /spaces/limits`
- [x] `scripts/make_sample_data.py`: sample `sales.csv`, `customers.jsonl` and a two-version local Delta table in `data/samples`
- [x] **Frontend:** Spaces list (home page for everyone) and a space page: **Data** (drag-and-drop upload with progress, add Delta folder, tables with columns and preview, remove), **SQL** (editor, Ctrl+Enter, clickable table/column list, results grid), **Members**, **Settings** (rename, delete)
- [x] Tests: 8 API tests for spaces (access rules, uploads, names, size limit, Delta, SQL), 39 engine + guard tests, migration up/down, frontend unit tests
- [ ] **Unity Catalog:** Databricks host + token + warehouse → browse catalogs, schemas, tables → add tables. *Waiting for a Databricks workspace to build and test against*
- [ ] **UC Volumes:** browse `/Volumes/...` → add a file as a table (small: into DuckDB; large: `read_files()` on the warehouse) or as a document (goes to RAG in Step 6). *Waiting for a Databricks workspace*
- [ ] Cloud Delta paths (`s3://`, `abfss://`) and the shared connector interface (`test()`, `list_tables()`, `get_schema()`, `sample()`): built together with the Databricks connector, when there is a second kind of source to share it

**Try it:** run `python scripts/make_sample_data.py` in `backend`, then open http://localhost:5173 → Spaces → New space. Upload `data/samples/sales.csv`, add the Delta folder `data/samples/orders_delta` (the script prints the full path), and run `SELECT region, sum(amount) FROM sales GROUP BY 1` on the SQL tab.

**Done when:** one space holds an uploaded CSV and a local Delta table (plus a UC table and a volume file, if a Databricks workspace is available), and a hand-written SQL query runs through the engine API.

---

### Step 5 — Metadata and profiling

**Goal:** the system "knows" the data, the way a Genie Agent's knowledge store does: descriptions, synonyms, real values and joins, kept per space and never written back to the data.

**Build**
- [x] **Profiling** (DuckDB, on the same locked-down connection as queries): per column the null count and %, distinct count, min/max and the 5 most common values. Runs automatically when a table is added, and again on **Re-profile**. A Delta table whose version moved on is marked **Data changed**. Descriptions, synonyms and switches an editor set survive re-profiling
- [x] **Descriptions and synonyms:** one description per table and per column, plus synonyms (business words for a column, up to 20). Editable by editors, readable by everyone in the space
- [x] **AI-drafted descriptions:** **Draft with AI** on a table proposes descriptions and synonyms for blank fields. It is on-click (free-tier quota), nothing is saved until an editor saves, and a column whose values are not shared never has them sent to the model
- [x] **Hide from AI:** a hidden column is left out of what the AI sees. The data and permissions do not change (as in Genie)
- [x] **Prompt matching, two levels (as in Genie):** *show sample values to AI* (format assistance) and *searchable values* (entity matching: text columns with 1 to 1,024 distinct values of at most 127 characters, at most 120 columns per space, needs the first switch). Values go into a `pg_trgm` index; `GET /spaces/{id}/values?q=` finds them despite typos. **Try a value** on the Metadata tab shows what would match
- [x] **Joins:** detected from column names, types and value overlap (at least one side must be a unique key), saved as *needs review*, then confirmed, edited (relationship: many to one, one to many, one to one) or deleted. Editors can add joins by hand
- [x] **Frontend:** a **Metadata** tab on the space page (tables and columns, joins, value tester)
- [x] Tests: 10 profiling and join-detection tests on real Parquet, 11 API tests (access rules, edits kept across re-profiling, searchable values, joins, Delta staleness, AI draft cleaning and privacy), migration up/down, frontend unit tests
- [ ] **Not in this step:** join conditions written as SQL expressions and self-joins (to be added when Step 7 needs them); SQL expressions (measures, filters, fields) come with the glossary in Step 6; mining thumbs-up answers for suggestions comes with feedback in Step 12

**Try it:** upload `data/samples/sales.csv` and `customers.jsonl`, open the **Metadata** tab: statistics are already there. Click **Draft with AI** (needs API keys), edit, **Save**, then **Find joins** and **Try a value**.

**Done when:** every table in the test space has descriptions, stats, and searchable values, and edited descriptions are saved.

---

### Step 6 — RAG knowledge layer

**Goal:** find the right context for any question.

**Build**
- [x] The document pipeline exactly as set in 4.2: Markdown parsing, section-first recursive splitting, 450-token text chunks (header included, never above the embedder's 512), 40-token overlap inside a section only, title + section-path headers, hybrid vector + BM25 index with metadata, top 40 + 40, Reciprocal Rank Fusion, rerank the best 30, keep 5 to 10, neighbouring pieces of a section joined back together
- [x] Chunkers for schema cards (one per table, one per visible column), example SQL (the question is embedded, the SQL travels in the metadata), instructions and glossary terms. Hidden columns get no card; a column whose values are not shared has no values in its card
- [x] **Knowledge items** (needed so there is something to index): `GET/POST/PATCH/DELETE /spaces/{id}/knowledge` for instructions, glossary terms and example SQL. Example SQL is checked by the SQL guard against the space's tables; editors can mark it **Trusted**
- [x] **Documents:** `POST /spaces/{id}/documents` (PDF, Word, PowerPoint, Excel, HTML, Markdown, text). A file that can't be read is kept as *failed* with the reason
- [x] Local fastembed embeddings (`EMBEDDING_MODEL`) and a local cross-encoder reranker (`RERANK_MODEL`), cached in `data/models` (a short path on purpose)
- [x] `chunks` table: text, header, metadata, `vector(384)` + HNSW index (cosine). One BM25 index per space, rebuilt when the space's `index_version` moves on
- [x] **Automatic re-indexing:** profiling, editing a description or synonym, hiding a column, joins, adding or removing a table, and every knowledge item change update the index. Unchanged chunks keep their vectors (content hash), so only new or changed text is embedded. `POST /spaces/{id}/index/rebuild` re-reads everything after a model or chunk-size change
- [x] **Parser bake-off** (`scripts/parser_bakeoff.py`): see below. MarkItDown is the default
- [x] Debug endpoint `GET /api/v1/spaces/{id}/search?q=` (editors): every candidate with its vector rank, BM25 rank, fused rank, rerank score and final rank, plus timings
- [x] **Frontend:** a **Knowledge** tab (instructions, glossary, example SQL, documents) and a **Search tester** in Settings (what the AI would be shown, the ranking at each stage, index counts, Rebuild)
- [x] Tests: 17 chunking tests on the real tokenizer (sizes, overlap, tables, code, odd inputs), 8 retrieval unit tests, 10 end-to-end knowledge tests, migration up/down

**Parser bake-off** (two generated PDFs with headings and tables; MarkItDown 0.1.9 and Docling, same machine, CPU)

| | Headings kept as `#` | Table rows kept intact | Time (one page) | Install |
|---|---|---|---|---|
| MarkItDown | 0% | 100% | 7 s first run, including start-up | light (no PyTorch); also reads Word, PowerPoint, Excel, HTML |
| Docling | 100% | 100% | 10 s warm, 41 s first run | 1.5 GB (PyTorch); in this sample it put the last section first |

*Decision:* MarkItDown stays the default: fast, light, one tool for every format, tables intact. Its cost is that **PDFs lose their heading structure**, so a PDF is split by size alone and its chunk headers carry only the document title. For PDFs where the section path matters, set `DOCUMENT_PARSER=docling` (`pip install docling`); Word, PowerPoint and HTML keep their headings with MarkItDown. Re-run `python scripts/parser_bakeoff.py <parser>` on your own PDFs before deciding. Page numbers are not recorded (neither converter's Markdown carries them).

**Retrieval report:** [docs/RETRIEVAL_REPORT.md](RETRIEVAL_REPORT.md). 22 questions on a small sales space: the right passage was in the final list for 22 of 22 (100%, target 90%).

**Limits worth knowing**
- A code block that cannot fit in 512 tokens even alone is cut on line boundaries (each piece keeps its fences), because the 512 limit wins over "never split".
- The test space is small and synthetic, so 100% is an upper bound. Step 12 adds a bigger benchmark and the 256 / 512 / 1024 chunk-size comparison.
- The embedding model is tied to the `vector(384)` column. Changing `EMBEDDING_MODEL` to a model of a different size needs a new migration, then Rebuild.
- The first search downloads about 150 MB of models into `data/models`. Without network access and without those files, indexing is skipped (the error is logged, saving metadata still works) and search fails with an error.

**Try it:** open a space, then **Knowledge** to add a few instructions, a glossary term, an example question with SQL, and a document. Then **Settings → Search tester** and ask a question.

**Done when:** for a test set of about 20 questions, the correct table or passage is in the final 5-10 at least 90% of the time, shown in a small retrieval report, and no chunk is ever cut off by the embedder's 512-token limit (checked by a test).

---

### Step 7 — Genie engine (question → SQL → result)

**Goal:** the core brain.

**Build**
- [x] The pipeline of 4.3 in `app/chat/`: rewrite a follow-up so it stands alone (fast model, only when the thread has history) → retrieve (Step 6) → write SQL, or answer from documents, ask one clarifying question, or decline (smart model) → SQL guard → run with the time and row limits → repair on error (at most 3 tries in all). 2 to 3 model calls per question, to stay inside the free-tier limits
- [x] Context for the prompt, built per question: the tables the retrieval points at (plus tables joined to them) with their visible columns, descriptions, synonyms and common values; all instructions; matching glossary terms; up to 3 example queries; values from the data that match words in the question (Florida → `FL`); document passages. Hidden columns are never shown
- [x] Conversation memory: the last 6 finished turns of **the same thread** (question, standalone question, SQL, outcome). Nothing from other threads
- [x] **Trusted** badge: set when the SQL that ran equals (ignoring case and spacing) a trusted example that retrieval found
- [x] Stop: `POST .../messages/{id}/cancel` interrupts a running DuckDB query; closing the connection also stops the turn
- [x] Tests with a scripted stand-in for the AI: query repair, 3 tries then a clear failure, the guard blocking `DROP`, unknown tables and file reads before anything runs, clarify / decline / answer-from-documents, empty results, trusted marking, AI failures, follow-ups, isolation between threads, access, stop

**Not yet measured:** the "80% of a 30-question set returns correct results" goal needs a real AI and keys. It is checked in Step 12 with the benchmark runner.

---

### Step 8 — Answers and charts

**Goal:** answers you can read at a glance.

**Build**
- [x] A short summary written from the result by the fast model, with a **grounding check**: every number in it must be found in the rows, the totals, the row count or the question. A summary with an unfound number is replaced by one built straight from the result, so an answer never states an invented figure
- [x] Chart picker by rules (`app/chat/charts.py`): time + numbers → line (one line per small category), category + number → bar (grouped for two categories), few shares → pie, one row → KPI tiles, two numbers → scatter. No chart when a table is clearer (no numbers, an id column, more than 30 categories, too few points). The spec only names columns that exist, and is marked `partial` when only a preview of the rows is stored
- [x] Chart editing: `PUT .../messages/{id}/chart` validates the type, X, Y, series and title against the result's columns
- [x] Up to 3 follow-up questions and a thread title from the same single call. Titles never overwrite a name a person chose

---

### Step 9 — Chat API and streaming

**Goal:** the frontend can drive everything.

**Build**
- [x] Threads: `GET/POST /spaces/{id}/conversations` (list with search, create), `GET/PATCH/DELETE .../{cid}`. A thread is private to its owner: even an admin or a fellow member gets "not found"
- [x] `POST .../{cid}/messages` streams events `start`, `status`, `sql`, `rows`, `answer`, `chart`, `suggestions`, `title`, `error`, `done` (`done` carries the saved message). Access problems are normal HTTP errors, not stream events. Only one answer runs at a time per thread. Editing an earlier question (`replace_message_id`) replaces it and everything after it
- [x] `GET .../messages/{id}/csv`: the full result as CSV (the query runs again, up to the row limit), with spreadsheet formula injection neutralised
- [x] Every turn is saved as it goes (SQL, rows preview, answer, chart, suggestions, timings per stage, models used, attempts, errors), which is also what the monitoring page (Step 12) reads
- [x] Feedback: thumbs up / down with an optional comment on every answer (`PUT/DELETE .../messages/{id}/feedback`). It is a signal for the people who maintain the space and is never given to the AI or turned into knowledge automatically
- [x] **General chat and per-chat documents:** every person has a personal space (no tables, never listed, `POST /chat/general`). Files added in a chat (`POST .../conversations/{id}/documents`, up to 10) are indexed for that conversation only, are removed with it, and are never visible to other chats or to the space. Viewers can add files to their own chats
- [x] **@mentions:** a question can point at documents (`mentions` on the message); the answer then uses only those documents (other knowledge still applies)
- [x] **Thought process and streamed answer:** `thought` events (what was found, the plan, retries, the row count) arrive as they happen and are saved with the answer; the answer text then streams as `answer.delta` pieces. The text is streamed after its numbers have been checked, so an unchecked figure is never on screen
- [x] Starting points: `GET /spaces/{id}/suggestions` (the space's example questions) and `GET /spaces/{id}/discover?q=` (search tables, columns, terms, documents and example questions; viewers allowed)

**Done when:** a test client receives the full event stream for a question and a follow-up, and stop cancels a running query. *Both are covered by tests in `tests/test_chat.py`.*

---

### Step 10 — Frontend foundation

**Goal:** a polished shell before any feature screen. *Moved up: built together with Step 2, so every backend step can be tested in the browser.*

**Build**
- [x] Vite + React + TypeScript project, Motion (`npm install motion`), Tailwind CSS, TanStack Query, React Router
- [x] Design system in `frontend/DESIGN.md`, tokens in `src/styles/index.css`, every text color checked for WCAG AA in both themes
- [x] System / Light / Dark theme, no flash on load
- [x] App shell: sidebar, mobile menu, routing, page transitions, API client with readable errors, streaming (SSE) reader with tests
- [x] Base components: Button, Card, StatusLabel, Badge, Notice, EmptyState, Skeleton, SegmentedControl
- [ ] Added when their step needs them: auth guard and token refresh (Step 3), Input, Dialog, Menu, Tabs, Tooltip, toasts
- [ ] Review the design with UI UX Pro Max once it is installed

**Done when:** the shell looks finished in both themes, works with the keyboard alone, and scores 95+ on the Lighthouse accessibility audit.

---

### Step 11 — Frontend features

**Goal:** the full product. Each screen below is built in the same step as the backend it uses (sign-in with Step 3, Data with Step 4, Chat with Steps 7–9, and so on). This step is the final pass that joins them up.

**Build**
- Sign in, Spaces list
- **Chat:** live steps, answer card with Answer / Table / Chart / SQL views, Trusted badge, feedback, follow-up chips, history sidebar
- **Space → Data:** file upload with progress, add a Delta path, Unity Catalog browser, UC Volume browser
- **Space → Knowledge:** instructions, example SQL, glossary, documents
- **Settings:** theme, account; for admins, LLM key health

**Done when:** a new user can sign in, create a space, upload a file, ask 3 follow-up questions, see charts, and give feedback with no dead ends, and every screen has its loading, empty, error, and filled states.

---

### Step 12 — Quality loop (benchmarks and feedback)

**Goal:** measure and improve accuracy, like Genie benchmarks.

**Build**
- [x] **Monitoring** (administrators): `/admin/monitoring` summary (questions, failure rate, average and slowest-5% speed, thumbs, answers needing review, per-day series) and a filterable list (period, space, status, feedback, review state, text). An answer's detail shows the question, the SQL, the error, timings and models, but never the rows a query returned
- [x] **Review workflow:** thumbs-down and failed answers form a queue. An administrator marks each resolved, dismissed or open again, with a note
- [x] **Verified corrections:** an administrator writes the right SQL; it is checked by the guard and run, and only then saved as an example (optionally Trusted) for that space, which also resolves the review. Feedback is never trusted as SQL or business logic
- [ ] Benchmark sets per space (question + expected SQL or expected result). A run gives an accuracy % and a per-question diff
- [ ] Review of thumbs-down answers by space editors (today only administrators see the queue)

**Done when:** the benchmark page shows a score and its history, and adding an example measurably fixes a failing question.

---

### Step 13 — Hardening and deploy

**Goal:** safe to run for real users.

**Build:** rate limits, security headers, upload limits, audit log. Caching (schemas, embeddings, repeated queries). Load test of the chat endpoint. Error monitoring hooks. Dockerfiles + `docker-compose.yml` (backend, frontend via nginx, Postgres with pgvector). Backup notes. Final README.

**Done when:** the full test suite is green, the security checklist is complete, and `docker compose up` runs the whole app.

---

## 7. How we work

- **One step at a time.** Each step ends with: tests pass → short demo → tracker below updated → git commit.
- **Frontend grows with the backend.** Every backend step also ships the screen that uses it, so each step can be tried in the browser.
- **Secrets only in `.env`**, which is never committed. `.env.example` is updated whenever a setting is added, and each step adds its own settings (RAG settings arrive in Step 6, and so on).
- **Every setting** has a safe default and a comment.
- **Python:** type hints everywhere, `ruff` for lint and format. **Frontend:** strict TypeScript, ESLint + Prettier.

## 8. Later ideas (not in v1)

- Cross-engine joins (e.g. copy small Unity Catalog tables into DuckDB)
- More connectors: PostgreSQL, MySQL, Snowflake
- Scheduled questions and email digests
- Dashboards built from saved answers
- Semantic chunking and LLM-written chunk context, measured with benchmarks
- SSO (Google, Microsoft, Databricks OAuth)

---

## Progress tracker

| Step | Name | Status |
|---|---|---|
| 0 | Project setup | Database done. API keys and the UI UX Pro Max skill install are your actions |
| 1 | Backend foundation | Done and tested |
| 2 | LLM gateway | Code and tests done. Live check waits for your API keys |
| 3 | Users and auth | Done and tested (backend, frontend, browser run) |
| 4 | Spaces and data sources | Done and tested for uploads and local Delta. Unity Catalog + UC Volumes wait for a Databricks workspace |
| 5 | Metadata and profiling | Done and tested (backend, frontend build). Draft with AI waits for your API keys for a live check |
| 6 | RAG knowledge layer | Done and tested (22/22 on the retrieval set; the 512-token limit is checked by tests). MarkItDown is the default parser |
| 7 | Genie engine | Backend done and tested with a scripted AI. A live check waits for your API keys |
| 8 | Answers and charts | Backend done and tested (grounding check, chart rules). Charts are drawn in the chat UI (Step 11) |
| 9 | Chat API and streaming | Done and tested, except feedback (with monitoring) |
| 10 | Frontend foundation | Mostly done (built with Step 2). Rest arrives with later steps |
| 11 | Frontend features | Status, Playground, Users, Spaces, **Chat** (history, answer card with table / chart / SQL, chart editor, CSV, edit-and-rerun, suggested questions, Search mode, thumbs), **About**, **Business definitions**, **Monitoring** done. Unity Catalog and UC Volume browsers wait for a Databricks workspace |
| 12 | Quality loop | Feedback, monitoring and the review workflow are done. Benchmark sets and the accuracy score are not started |
| 13 | Hardening and deploy | Not started |

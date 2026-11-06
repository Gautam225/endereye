# Eye of Ender: the complete guide in simple words

This guide explains the whole system from the start: what it is, who uses it, what it does, how a question travels through it, and every Python library we installed and why. You do not need to be a programmer to read it. Words in **bold** are explained again in the glossary at the end.

---

## 1. What is Eye of Ender?

Think of a company that keeps its important numbers in databases and spreadsheets: employees, salaries, sales, orders. Today, when a manager wants an answer ("Which department pays the most?"), they must ask a data analyst, who writes a database query (SQL), waits for it to run, makes a chart and sends it back. That takes hours or days.

**Eye of Ender lets anyone ask that question in plain English and get the answer in seconds.** The person types a question. The system:

1. understands it,
2. writes the SQL query itself,
3. checks the query is safe,
4. runs it on the data,
5. shows the **answer in words, a table, a chart, and the SQL** it used.

It is a **self-hosted** product: it runs on the company's own computers or servers, so the company's data does not have to be uploaded to someone else's cloud. It is inspired by Databricks Genie, but it is lighter and you own it.

The one thing that is sent outside is the **question and the names of tables and columns** (so an AI model can write the query). **The rows of data are not sent** unless an administrator turns that on for a connection.

---

## 2. Who will use it (enterprise level)

### The three kinds of people

| Role | Who they usually are | What they can do |
| --- | --- | --- |
| **Administrator** | IT, data-platform owner, security lead | Everything. Adds users and sets their roles, connects external databases, decides who sees which columns and rows (access rules), adds people to spaces, watches system health and answer quality. |
| **Editor** | Data analyst, team lead, domain expert (HR analyst, finance analyst) | Creates **spaces**, uploads files, picks database tables, teaches the system the company's words and rules (the **knowledge**), runs SQL by hand, saves trusted example queries, builds test sets (benchmarks). |
| **Viewer** | Manager, executive, sales rep, anyone who just needs answers | Asks questions in the chat, reads answers, charts and tables, downloads results, shares and pins chats. Cannot change data or settings. |

Only an administrator can add people to a space or change anyone's role. This is checked on the server, not just hidden in the screen.

### Typical enterprise situations

- **HR:** "How many current employees per department, and what is the average salary?" asked by HR managers who never learn SQL.
- **Sales operations:** "Revenue by region last quarter, compared with the quarter before."
- **Finance:** "Total salary spend by department", with Excel export for the monthly report.
- **Leadership:** a **Deep** question such as "Prepare a workforce analysis" that is split into several analyses and printed as a PDF report.
- **IT/security:** one admin connects a read-only company database, hides the salary column from most people, and watches the audit trail.

### Why a company would choose this

- **Data stays inside.** Self-hosted. Result rows are not sent to the AI service by default.
- **Safe by design.** The system can only read. It cannot change or delete data (see section 6).
- **Different people see different data.** Access rules hide columns or rows per role or person.
- **Trust.** Every answer shows the SQL. Editors can mark queries as **Trusted** so answers that use them are labelled *Verified query*.
- **Measurable quality.** Benchmarks score the assistant against questions with known right answers.

---

## 3. The big picture

```
 Person in a web browser
        |
        v
 +----------------------+        +-------------------------------+
 |  Frontend (React)    | -----> |  Backend (Python, FastAPI)    |
 |  chat, charts, admin |  HTTP  |  login, spaces, chat pipeline |
 +----------------------+        +---------------+---------------+
                                                 |
        +----------------+-----------------------+-------------------+
        v                v                       v                   v
 PostgreSQL (app DB)   DuckDB                 External PostgreSQL   AI services
 users, spaces,        runs SQL on uploaded   (the company's own    OpenRouter, Groq
 chats, knowledge,     files (CSV, Excel,     database, read-only)  (write SQL, explain)
 search vectors        Parquet, JSON, Delta)
                                                                     Local models on this
                                                                     computer (search)
```

- **Frontend:** the website people see (React).
- **Backend:** the brain, written in Python. It checks logins, runs the question pipeline and talks to everything else.
- **PostgreSQL (the app database):** the system's own memory: accounts, spaces, chat history, knowledge, and the search index. (This is *not* the company data.)
- **DuckDB:** a fast engine that runs SQL on **uploaded files** inside the backend.
- **External PostgreSQL:** the company's real database, connected read-only.
- **AI services:** large language models, used to write the SQL and, when allowed, to explain the result.
- **Local models:** small models on the same machine that power the search over schemas, rules and documents (no outside calls).

---

## 4. What the system does, feature by feature

### 4.1 Spaces: one room per topic
A **space** is a workspace for one subject (for example "HR" or "Sales"). It holds the tables, the knowledge, the members and the chats. Members are *viewers* or *editors* of that space. There is also a **general chat** that has no data: it just answers general questions and can read documents you attach.

### 4.2 Bringing in data
- **Upload files:** CSV, TSV, Excel, Parquet, JSON. They are converted to Parquet and queried with DuckDB.
- **Local Delta tables:** attach a Delta folder by path.
- **External PostgreSQL database:** an administrator creates a **connection**. The password is **encrypted** and never shown again. The system tests the connection and checks that the login is truly **read-only**. It can even create a safe read-only login for you. Then you pick up to 50 tables to put in a space.

### 4.3 Teaching the system your business (the "knowledge")
The AI does not know your company's words. Editors teach it:
- **Descriptions and synonyms** for tables and columns ("emp_no is also called employee number").
- **Business definitions** written as SQL ("current employee = to_date is 9999-01-01"), tested before saving, and *default filters* added to every question that needs them.
- **Glossary terms**, **instructions** ("always show salaries rounded"), **"when to ask" rules** for ambiguous questions.
- **Example queries** (question + SQL). If marked **Trusted**, answers using them show a *Verified query* badge.
- **Documents** (PDF, Word, PowerPoint, Excel, HTML): their text is searched and used to answer.
- **Joins** between tables, detected automatically and confirmed by an editor.

### 4.4 Asking questions
The question box has three answer styles (the small menu beside the send button):
- **Quick:** a faster model, fewer checks. For simple look-ups.
- **Standard:** one checked query, with the answer explained.
- **Deep:** a big request (like a full workforce analysis) is split into up to five separate analyses. Each is written, checked, repaired and shown on its own with its own table, chart and SQL. A failing part does not sink the others. The answer lists **assumptions** and **what the data could not answer**, so nothing is made up.

The box also decides on its own whether you are **searching** ("find the salary table") or **asking** ("average salary by department"). You can attach files and point at a document with `@name`.

If the system truly needs more information it asks a **clarifying question** with clickable options plus a free-text box.

### 4.5 What an answer contains
- A **plain-language summary** (every number comes from the real result; for private connections it is written by the system itself).
- A **table** (sortable, formatted).
- **Charts** chosen automatically by rules, not by guesswork: one chart per kind of figure, never mixing salary with head-count on one axis; horizontal ranked bars for many categories; a different colour per chart; totals tiles ("overall average", "total") worked out by the database, not by adding rows.
- The **SQL** (collapsed; editors can edit and re-run it).
- The **sources** used, **thumbs up/down** feedback, and suggested follow-up questions.

### 4.6 Taking answers away
- **CSV** (all rows), **Excel** (rows plus a sheet with the question, answer, overall figures and SQL), **PDF** (the browser's print dialog, laid out cleanly), **PNG** of any chart.
- **Pin** important chats, **rename** them, **share** a chat read-only with the space, and **branch** a chat into your own copy.

### 4.7 Quality and monitoring
- **Monitoring (administrators):** volume of questions, failures, speed, feedback, a review queue for bad answers.
- **Benchmarks (editors):** a set of questions with known correct SQL. Run them to get a score and spot regressions.
- **System status** page for administrators: database checks, AI keys (masked), models used.

### 4.8 Look and feel
Light, dark or system mode and three colour templates (Default, Claude-style, ChatGPT-style). The chat history can be folded or resized.

---

## 5. How one question travels through the system

Example: *"Compare all departments by average salary."*

1. **Login check.** The backend confirms who you are and that you belong to the space.
2. **Understand.** If this is a follow-up ("and in March?"), a fast model rewrites it into a full question.
3. **Retrieve.** The system searches its local index for the right pieces: relevant tables and columns, glossary terms, business definitions, example queries, instructions, documents. It uses keyword search (BM25), meaning search (embeddings in pgvector) and a reranker to keep the best ones. It also matches words in your question to real values in the data ("Florida" to "FL").
4. **Remember your permissions.** Columns hidden from you are never described to the AI.
5. **Write the SQL.** A "smart" AI model gets a short prompt: the tables, rules, examples and your question. It answers with a structured plan (the SQL, assumptions, which figures it will show).
6. **Guard.** The **SQL guard** checks the query: one read-only SELECT, only this space's tables, only allowed functions, no hidden columns, a row limit. For databases it rewrites table names to the real ones.
7. **Run.** The query runs with a **time limit** and **row limit**, in a read-only transaction. You can press Stop and it really stops.
8. **Repair.** If it fails, the error is sent back to the AI to fix, up to 3 tries. The system also redoes a query once if:
   - a figure you asked for is missing from the result,
   - a filtered query returned nothing (it is shown the real date ranges of the data),
   - you asked for a "combined" chart but got separate ones.
9. **Overall figures.** For results that compare several measures, the system asks the database for the grand total/average with the same query minus the grouping. (Adding up rows would be wrong for averages.)
10. **Explain.** If the connection allows, a fast model writes a short summary, and the system **checks every number in it against the result**; an invented number causes the text to be replaced by a safe one built from the data. If rows must not leave, the summary is written locally.
11. **Chart.** Rules choose the chart type and layout from the real columns.
12. **Save and stream.** Each step is saved as it happens and streamed to the screen (you see the "thought process" live). A refresh never loses work.

---

## 6. Security and safety in simple terms

| Protection | What it means |
| --- | --- |
| **Read-only everywhere** | The SQL guard allows one SELECT. The external database login is checked to be read-only. The query runs in a read-only transaction. Three separate walls. |
| **Passwords are encrypted** | External database passwords are locked with AES-GCM using a key kept only in the server's environment file, never in the database. The key can be rotated. |
| **Safe network use** | Connection addresses are checked so the app cannot be tricked into reaching internal or forbidden machines (SSRF protection). |
| **Login security** | Passwords are hashed with Argon2. Sessions use short-lived tokens plus refresh tokens. Changing your password signs out other devices. |
| **Roles** | Administrator, Editor, Viewer, checked on the server for every request. |
| **Access rules** | An administrator can hide a column, show it as empty, or show only some rows (for example only region = 'West') for viewers, for members, for everyone, or for one person. Applied where data is read, so they hold in the assistant, SQL tab, previews, exports and Deep mode. |
| **No made-up numbers** | Numbers in written answers are checked against the result. |
| **Privacy of results** | Result rows are not sent to the AI service unless an administrator turns it on per connection. |
| **Audit trail** | Connection actions are logged. Secrets are removed from logs. |
| **Limits** | Rate limits on sign-in and heavy actions, upload size limits, query time and row limits. |

Honest limits: the company's database is still reached with **one saved login** per connection (no separate database identity per person). Access rules are enforced by the app's own checks, so they do not protect against someone who has direct access to the database or files.

---

## 7. The Python libraries and why we use them

The backend uses **Python 3.12**. Versions are pinned exactly so the same code works the same everywhere. File: `backend/requirements.txt`.

### 7.1 Web server and settings
| Library | What it is | Why we use it |
| --- | --- | --- |
| **fastapi** | A modern framework for building web APIs. | It receives the browser's requests (login, ask a question, download a file), checks inputs automatically, and can stream answers live (Server-Sent Events). |
| **uvicorn** | The program that actually runs the FastAPI app and listens for connections. | A fast server that handles many users at once. |
| **pydantic** | Describes the exact shape of data and checks it. | Every request and response has a strict shape, and the AI's replies are forced into a shape too, so bad data is rejected early. |
| **pydantic-settings** | Reads configuration (from `.env` and the environment) into checked settings. | Limits, keys and options are validated at start-up, so mistakes show immediately. |
| **python-dotenv** | Reads the `.env` file. | Keeps secrets (API keys, the encryption key) out of the code. |
| **python-multipart** | Understands file uploads in web requests. | Needed for uploading CSV, Excel and documents. |
| **email-validator** | Checks email addresses properly. | Used for user accounts. |

### 7.2 The application database (PostgreSQL)
| Library | What it is | Why we use it |
| --- | --- | --- |
| **sqlalchemy** | Lets Python talk to databases using Python objects instead of hand-written SQL. | Stores users, spaces, chats and knowledge safely (it prevents SQL injection by design). We use its async mode. |
| **asyncpg** | A very fast PostgreSQL driver. | SQLAlchemy uses it, and we also use it directly to read the company's external PostgreSQL. |
| **alembic** | Database "version control": migrations. | Each change to the app's tables is a numbered migration (now up to 0021), so every installation upgrades the same way. |
| **pgvector** | Adds a "vector" column type to PostgreSQL. | Stores embeddings (the numbers that represent meaning) so we can search by meaning. |

The app database also uses two PostgreSQL extensions: **pgvector** (meaning search) and **pg_trgm** (typo-tolerant text matching, used to match words in a question to real values in the data). The health check reports if either is missing.

### 7.3 Running SQL and keeping it safe
| Library | What it is | Why we use it |
| --- | --- | --- |
| **duckdb** | A fast analytical database that runs inside the program. | Runs the SQL on uploaded files without a separate server. Locked down: it can only read the space's own files. |
| **sqlglot** | A SQL parser and rewriter. | The heart of safety. It reads a query as a tree so we can check every table, column and function, rewrite table names, add row filters, read which columns are averages or counts, and build the "overall figures" query. |

### 7.4 The AI (language models)
| Library | What it is | Why we use it |
| --- | --- | --- |
| **openai** | The standard Python client for the OpenAI-style API. | OpenRouter and Groq speak the same API, so one client works with both. Our own gateway adds key rotation and fallback. |
| **httpx2** | An HTTP client library. | Used by the AI client; we catch its network errors, and tests use it to call the API. |

### 7.5 Search over knowledge (RAG)
| Library | What it is | Why we use it |
| --- | --- | --- |
| **fastembed** | Runs small AI models locally on the CPU (ONNX). | Makes embeddings and reranks results on this machine, with no outside calls and no extra cost. |
| **bm25s** | Fast keyword ranking (BM25). | Finds exact words and names, which meaning search can miss. Combined with vector search. |
| **markitdown** (with pdf, docx, pptx, xlsx parts) | Converts documents to clean text. | Lets people attach PDF, Word, PowerPoint, Excel and HTML files and ask about them. |

### 7.6 Sign-in and secrets
| Library | What it is | Why we use it |
| --- | --- | --- |
| **pyjwt** | Creates and checks login tokens (JWT). | Proves who is calling the API without asking for the password every time. |
| **pwdlib** (with argon2) | Password hashing. | Stores passwords as Argon2 hashes, the modern safe choice, so even we cannot read them. |
| **cryptography** | A strong encryption library. | Encrypts external database passwords with AES-GCM (the vault). *Note: it was being installed only indirectly; it is now listed explicitly.* |

### 7.6b Files for people
| Library | What it is | Why we use it |
| --- | --- | --- |
| **openpyxl** | Reads and writes Excel files. | Builds the Excel download with the results on one sheet and the answer and SQL on another. |

### 7.7 Tools for developers and tests (`requirements-dev.txt`)
| Library | Why |
| --- | --- |
| **pytest** | Runs the automatic tests (about 900 of them). |
| **ruff** | Checks code style and common mistakes, and formats the code. |
| **deltalake**, **pyarrow** | Create sample Delta tables for tests and demos. |
| **reportlab**, **python-docx** | Create sample PDF and Word files for tests. |

### 7.8 Libraries that come along automatically
Some libraries are installed because the ones above need them (for example **starlette**, which FastAPI is built on, **anyio** for async work, **tokenizers** for the local models, **pdfminer** for reading PDFs). We list only the ones we choose ourselves.

### 7.9 Standard Python tools we also use
`asyncio` (many things at once), `threading` (run DuckDB without blocking), `dataclasses`, `re` (patterns), `hashlib`/`secrets` (hashing and random keys), `ipaddress`/`socket`/`ssl` (safe connections), `csv`, `io`, `pathlib`.

---

## 8. The website's libraries (frontend, in short)

| Library | Why |
| --- | --- |
| **React** + **react-router** | Builds the screens and the page navigation. |
| **Vite** | Builds and serves the website quickly during development. |
| **TypeScript** | Catches mistakes before they run. |
| **Tailwind CSS** | Styling with a consistent design system (colours, spacing). |
| **TanStack Query** | Loads data from the backend, caches it, and refreshes it. |
| **Recharts** | Draws the charts. |
| **react-markdown** + **remark-gfm** | Shows the answer text with lists, bold and tables. |
| **Motion** | Gentle animations that explain changes. |
| **lucide-react** | The icons. |
| **Vitest**, **ESLint**, **Prettier** | Tests, code checks and formatting. |

---

## 9. Where things live (folder map)

```
Enderman/
  backend/
    app/
      api/v1/      The web endpoints (login, spaces, chat, connections, access rules...)
      chat/        The question pipeline: prompts, SQL repair loop, charts, summaries, Deep mode
      core/        Settings, security, encryption vault, logging, rate limits
      db/          Database models and sessions
      engine/      SQL guards and engines (DuckDB, PostgreSQL), profiling, provisioning
      llm/         The AI gateway: providers, key rotation, error handling
      rag/         Search: embeddings, keyword search, document parsing
      schemas/     The shapes of requests and responses
      services/    The business logic behind the endpoints
    alembic/       Database migrations (numbered)
    tests/         About 900 automatic tests
    requirements.txt, requirements-dev.txt
  frontend/
    src/features/  chat, spaces, connections, monitoring, users, account...
    src/components/ Buttons, cards, drop-downs, shared pieces
    DESIGN.md      The design rules (colours, spacing, charts)
  docs/            ROADMAP.md (the plan), this guide
  README.md        Setup and feature notes
```

---

## 10. Words explained

- **SQL:** the language used to ask databases questions.
- **LLM (large language model):** the AI that writes the SQL and explains results.
- **RAG:** "retrieve, then answer". Instead of hoping the AI knows your business, the system first looks up the right tables, rules and documents and gives them to the AI.
- **Embedding:** a list of numbers that captures the *meaning* of a piece of text, so similar meanings can be found.
- **BM25:** a classic keyword-matching score. Good for exact words.
- **Reranker:** a small model that re-orders search hits so the best come first.
- **SQL guard:** the code that inspects every query and refuses anything unsafe.
- **Read-only:** can look at data but not change it.
- **DuckDB:** an analytics database that runs inside the app.
- **Delta / Parquet:** file formats for big data tables.
- **Migration:** a numbered, repeatable change to the app's database structure.
- **JWT:** a signed token that proves who you are for a short time.
- **Argon2:** a slow, safe way to store passwords.
- **SSRF:** a trick where an app is made to call internal machines; we block it.
- **Space:** a workspace for one topic with its data, knowledge, members and chats.
- **Trusted / Verified query:** an example query an editor checked; answers using it are labelled.
- **Access rule:** a restriction on what a person can read (hide a column, empty a column, filter rows).
- **Benchmark:** a list of questions with known right SQL used to score the assistant.
- **Grounding:** checking that every number in the written answer exists in the result.

---

## 11. Running and checking it

From the project folder (see README for the first-time setup):

```powershell
# backend (from backend/)
python scripts/setup_database.py      # first time: creates the databases
python -m alembic upgrade head        # apply database upgrades
python -m uvicorn app.main:app --reload

# frontend (from frontend/)
npm install
npm run dev                           # http://localhost:5173

# checks
python -m pytest -q                   # backend tests (about 12 minutes, run one at a time)
npm run typecheck && npm run lint && npm test
```

---

## 12. What it does not do (yet), honestly

- Only **PostgreSQL** is supported as an external database (plus uploaded files and local Delta folders).
- No per-person database identity: one saved read-only login per connection, with the app's access rules on top.
- Charts and written results follow fixed rules; unusual shapes may fall back to a table.
- Deep mode builds each analysis's text from its rows; it does not give an AI-written overall narrative.
- Scheduled reports, e-mailed charts and write-back to other tools are not built.
- The top of `README.md` still mentions Databricks SQL and Unity Catalog from the original plan; those are not part of the current build.

# Eye of Ender: what it can do, what it cannot, what to build next, and how it differs from Databricks Genie

This is a planning and presentation document. It is based on the system as it is built today (see `SYSTEM_GUIDE.md` for how each part works) and on the Databricks Genie notes kept in `important_docs_about_project/`. Statements about Genie come from those notes; Genie is a fast-moving product, so check Databricks' current documentation before quoting a Genie feature outside this team.

---

## 1. In one paragraph

Eye of Ender lets people ask questions about company data in plain words and get back an answer, a table, a chart and the SQL behind it. It is a **self-hosted** product: the company runs it, chooses the AI provider, and keeps the data where it already is. Its safety does not depend on trusting the AI. The AI only *writes* a query; the database's read-only login and the app's SQL guard decide what may actually run.

---

## 2. What the system can do today (built and working)

### 2.1 Asking questions
- Plain-language questions, with follow-ups that remember the conversation.
- Three answer styles: **Quick** (fastest, short), **Standard** (balanced), **Deep** (splits a big request into up to five separate analyses and shows each step).
- Automatic choice between *asking the data* and *searching the knowledge* (tables, columns, terms).
- **General chat** for questions that are not about a database (for example reading uploaded documents). It offers Quick and Standard only, because Deep works on tables.
- The assistant asks back when a question is unclear, and politely declines when it is outside what the data can answer.
- Chats can be pinned, searched, shared with other members, or copied (forked) to continue separately.

### 2.2 What an answer contains
- A written answer, the result table, the **SQL** that produced it, and a chart picked to suit the data (bar, line, pie, stacked, several panels for several measures).
- A **verified badge** when an answer matches a saved, reviewed example.
- Overall figures (totals) alongside breakdowns when the question asked for them.
- Export to **Excel** and **PDF** (print report with the charts), and CSV.
- A chart editor, colour templates (palettes), light and dark themes.

### 2.3 Data sources
- **Uploaded files:** CSV, TSV, Excel, Parquet, JSON (stored as Parquet and queried with DuckDB).
- **Delta Lake folders** on the server, read where they are.
- **PostgreSQL databases** through saved connections. Rows are not copied; only descriptions are stored and rows are read when a question is asked.
- Up to 50 tables per space, with joins taken from foreign keys or defined by hand.

### 2.4 Teaching the system the business (the "knowledge")
- Table and column descriptions, synonyms, and which columns are hidden.
- Business terms and definitions, reusable SQL expressions (metrics), example questions with approved SQL, and written instructions.
- Documents the assistant can search for context (RAG).
- A **Benchmarks** area: a set of real questions with expected answers, run to measure accuracy before and after changes.

### 2.5 Security and control
- Sign-in with roles: **Admin**, **Editor**, **Viewer**; admins add users (no public sign-up).
- Spaces: each topic is a "room" with its own members; people outside it cannot see it.
- Connections accept **only read-only logins**; a login that can write is refused. An admin can have a read-only login created for them (the admin password is used once and not stored).
- Passwords for saved connections are stored encrypted.
- A **SQL guard** that allows one read-only query, checks every table and column against what the space exposes, allow-lists functions, and adds a row cap.
- **Access rules per person or group:** hide a column, show a column as empty, or show only some rows (for example `region = 'West'`). Enforced everywhere data is read, including previews and the SQL tab.
- Result rows are **not sent to the AI service** by default (an admin can switch this on per connection).

### 2.6 Running it
- **Monitoring** page: questions per day, failure rate, typical speed, thumbs up/down, a queue of answers that need review, and a way to save a corrected answer as a verified example.
- **System status** page: database checks, AI providers and keys (masked), call counts.
- Several AI providers with automatic fallback and key rotation.
- Audit trail for connections, and a large automated test suite.

---

## 3. Limitations: what it cannot do (yet)

Being honest about these is part of a good presentation. Each item says what to do about it.

| Limitation | What it means | Workaround or plan |
|---|---|---|
| **Only PostgreSQL** as an external database | No MySQL, SQL Server, Oracle, Snowflake, BigQuery or Databricks SQL connections | Add one engine at a time (the guard and schema reader are the main work per engine) |
| **One saved login per connection**, not per person | The database cannot tell *who* asked; it only sees the saved read-only login | App-level access rules cover who sees which columns and rows; for a stronger guarantee use one login per group, or PostgreSQL row-level security |
| **Access rules are app-level** | They limit what queries return, but do not protect against someone with direct access to the database or files | Keep the database and the file folder locked down separately |
| For **uploaded files**, hidden columns are hidden from the AI but not blocked in raw SQL | A determined editor could name them in the SQL tab | Use an access rule (this is enforced), not just "hide" |
| **The guard refuses SQL it cannot understand** | Unusual functions or syntax get rejected; the assistant is told why and retries | Extend the allow-list when a real need appears |
| **Charts follow fixed rules** | Unusual data shapes may fall back to a plain table; no free-form dashboard building | Use the chart editor; later, add saved dashboards |
| **Deep mode builds each analysis's text from its rows** | There is no AI-written overall narrative across the steps | Add a final summarising step (watching the privacy setting) |
| **No scheduled or emailed reports** | Nothing runs on a timer or is sent out | Planned feature (see section 4) |
| **No write-back or actions** | It never changes data, files tickets, or posts to other tools, by design | Keep read-only; add narrow, approved actions only if the business asks |
| **No single sign-on (SSO) yet** | People sign in with email and password created by an admin | Add OIDC/SAML (Azure AD, Okta, Google) for enterprise rollout |
| **No live data from other tools** (Slack, Drive, SharePoint, ticketing) | Only the three data sources above, plus uploaded documents | Add connectors one at a time |
| **Answer quality depends on the data description** | Poor names or missing definitions lead to wrong or vague answers | Use the knowledge tab and benchmarks; treat setup as part of the project |
| **Language models can still be wrong** | The guard stops harm, not mistakes of meaning | Verified badge, Monitoring review queue, benchmarks |
| **Single deployment** | No multi-tenant hosting, no built-in high-availability setup | Container and deployment hardening before large rollouts |
| The top of `README.md` still mentions Databricks / Unity Catalog from the original plan | Out of date text | Edit the README |

---

## 4. Strong things worth implementing next

Grouped by value, with a suggested order. "Why" is written for someone deciding what to fund.

### 4.1 First: make it trusted and easy to adopt
1. **Single sign-on (OIDC/SAML).** Required by almost every enterprise; removes password handling.
2. **More database engines**, starting with the ones customers actually use: MySQL/MariaDB, SQL Server, then Snowflake/BigQuery. Each engine needs its own guard rules and schema reader.
3. **Per-group or per-user database identity** where the database supports it (for example per-user logins, or setting a role per session), so the database itself enforces permissions and not only the app.
4. **Answer certification workflow:** an expert approves an answer, it becomes a verified example, and similar questions reuse it. Much of this exists; make it a clear, visible process with owners.
5. **Accuracy dashboard from benchmarks:** pass rate over time, per space, with a release gate ("do not publish a change if accuracy drops").

### 4.2 Second: make it more useful every day
6. **Saved dashboards and pinned charts.** Let a person keep an answer and refresh it, instead of re-asking.
7. **Scheduled and emailed reports** (a question run weekly, sent as PDF or Excel). Biggest "business user" request in most analytics tools.
8. **Alerts** ("tell me when failed orders go above 3%").
9. **A shared metric layer:** named metrics (revenue, active customer) defined once, used by every question and visible to all. The current SQL expressions are the start; add versioning, owners and tests.
10. **Smarter overall narrative for Deep mode:** an AI-written summary across the steps, respecting the "do not send rows to the AI" setting (for example by summarising from totals only).
11. **Question suggestions that learn:** most-asked and best-rated questions per space, shown on the start screen.

### 4.3 Third: reach beyond SQL
12. **Document and PDF analysis with citations** in the main chat (the General chat does a version of this; add page-level citations and a managed document library per space).
13. **Connectors for Slack, Google Drive, SharePoint and ticketing tools** as read-only sources.
14. **Public API and embeddable chat widget** so other company apps can ask questions (with scoped tokens).
15. **Usage and cost controls:** per-user and per-space limits, and a cost view per AI provider.

### 4.4 Platform health (do alongside)
16. Containers, backups, health checks and a documented upgrade path.
17. Observability: tracing a slow question through retrieve, plan, run and explain.
18. Data-retention settings for chats and monitoring data.

---

## 5. What is different from Databricks Genie

### 5.1 The short version

> **Genie is the best choice when the data already lives in Databricks and the company wants a managed product. Eye of Ender is the choice when the company wants the same style of experience, on its own databases and files, without moving data into one vendor's platform, and with control over the AI and the infrastructure.**

### 5.2 Side by side

| Area | Databricks Genie (from the project notes) | Eye of Ender (this system) |
|---|---|---|
| **Where it runs** | Inside the Databricks platform (managed) | On the company's own servers or cloud (self-hosted) |
| **Where the data must be** | In Unity Catalog, queried through a SQL warehouse | Where it already is: PostgreSQL, uploaded files, Delta folders; nothing is copied |
| **Data governance** | Unity Catalog: permissions, row and column policies, lineage, audit, tied to each user | The database's own read-only login plus the app's access rules and SQL guard; roles and spaces in the app |
| **Who the database sees** | Can evaluate access *as the person asking* | One saved login per connection (a known gap, see section 3) |
| **AI model** | Chosen and run by Databricks | Any provider the company configures (several, with fallback); can be switched without changing the product |
| **Does data go to the AI service?** | Handled inside Databricks' platform and its terms | By default only the question and table/column *descriptions* are sent; result rows stay home unless an admin enables it |
| **Modes** | Chat (one query), Agent (multi-step research), a faster Agent variant (Beta) | Quick, Standard, Deep (a plan of up to five analyses, each shown as a step) |
| **Semantic layer** | Unity Catalog metadata, metric views, SQL expressions, examples, instructions, trusted assets | Descriptions, synonyms, terms, SQL expressions, examples, instructions, hidden columns, joins; no separate metric-view object yet |
| **Trust signals** | Benchmarks, monitoring, certified/trusted assets | Benchmarks, Monitoring review queue, **verified badge**, corrected answers saved as examples |
| **Documents and other sources** | Agent mode can use files in Unity Catalog volumes (Beta, with stated limits) and external tools through connectors (Slack, Drive, Beta) | Uploaded files as tables; General chat over uploaded documents; no external tool connectors yet |
| **Scale and compute** | Runs on Databricks SQL warehouses, built for very large lakehouse data | Runs queries on the source database or DuckDB; suited to department and mid-size data, not petabyte lakehouse scale |
| **Integration** | Conversation APIs, OAuth, service principals, Databricks apps | Own REST API; no embeddable widget or public API product yet |
| **Cost model** | Databricks usage (warehouse compute, plus Genie features) | Servers plus AI provider usage; no per-seat licence from a platform vendor |
| **Time to start** | Fast if already on Databricks; heavy if the data is not there | Fast on any existing PostgreSQL or a spreadsheet; setup effort is mostly the knowledge |
| **Customisation** | Within the product's settings | Full control of the code: the guard, the charts, the prompts, the look |
| **Maturity and support** | Vendor-supported product with a large team | Young product owned by this team; support is ours |

### 5.3 Where Eye of Ender is genuinely stronger
- **No data movement or platform lock-in.** It works on the databases and files people already have.
- **Privacy by default.** Result rows stay inside by default; many companies cannot send rows to an outside AI.
- **Choice of AI and cost control.** Swap or mix providers, and keep a local or private model as an option.
- **Open to change.** A new rule, a new chart type, a company-specific guard check, or a custom screen can be added directly.
- **Transparent answers.** The SQL, the steps (in Deep mode) and the data used are always visible.
- **Simple for small and mid-size teams.** No lakehouse project is needed to get value.

### 5.4 Where Genie is stronger (be honest in a comparison)
- **Per-person data permissions end to end** through Unity Catalog.
- **Scale**, and the managed compute behind it.
- **A larger ecosystem:** dashboards, notebooks, governance, lineage in one place.
- **Vendor support, security certifications and a long roadmap** with a dedicated team.
- **Documents and external tools in Agent mode**, as they mature.

### 5.5 How to position it
- To a company **already on Databricks**: use Genie; Eye of Ender is not the answer there.
- To a company **on PostgreSQL, spreadsheets or mixed sources**, or one with strict data-handling rules: Eye of Ender fits, and its "result rows stay home" setting is a selling point.
- As a **bridge**: teams that expect to move to Databricks later can start here, and the knowledge they write (descriptions, definitions, examples, benchmarks) carries over in spirit.

---

## 6. Suggested roadmap summary

| Phase | Focus | Examples |
|---|---|---|
| **Now** | Finish and harden | Fix the README, deployment hardening, more tests on access rules |
| **Next (1 to 2 quarters)** | Enterprise readiness | SSO, MySQL/SQL Server, accuracy gates, scheduled reports |
| **Later** | Reach and scale | Dashboards and alerts, document library with citations, connectors, embeddable widget and API |
| **Always** | Trust | Benchmarks, review queue, verified answers, honest limits shown in the product |

---

## 7. One-line answers for questions you will be asked

- **"Is it safe?"** The AI never has write access: the database login is read-only and every query passes a guard, with access rules on top.
- **"Does our data go to the AI company?"** Not result rows, by default. Only the question and the names and descriptions of tables and columns.
- **"What if the AI is wrong?"** Every answer shows its SQL; answers can be rated, reviewed and corrected, and corrected ones become verified examples. Benchmarks measure accuracy.
- **"Can it work with Oracle or Snowflake?"** Not yet; PostgreSQL, files and Delta only. Adding engines is on the plan.
- **"Is it a replacement for Genie?"** Not for companies fully on Databricks. It is an alternative for everyone else.

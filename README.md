# Eye of Ender

Ask questions about your data in plain English. Get back the answer, the table, a chart, and the SQL that produced it. A self-hosted take on Databricks Genie.

Works with **Delta tables** (by path or in Unity Catalog), **UC Volumes**, and **uploaded files** (CSV, Excel, Parquet, JSON), and uses RAG over your schemas, business rules, and documents.

**Status:** in development. The step-by-step plan and progress are in [docs/ROADMAP.md](docs/ROADMAP.md).

## Stack

- **Backend:** Python 3.12, FastAPI, PostgreSQL 18 + pgvector, DuckDB, Databricks SQL / SDK
- **LLMs:** OpenRouter (4 keys, rotated), with Groq as fallback (4 keys)
- **Frontend:** React + Vite + TypeScript, Tailwind CSS, Motion

## Getting started

1. Activate the virtual environment (below), then set up the database with one command. From the `backend` folder:

   ```powershell
   python scripts/setup_database.py
   ```

   It asks once for your PostgreSQL `postgres` password (hidden, never saved), then creates the login, the databases, and the tables, and writes the connection into `.env` as one line, `DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE`. You can also write that line yourself. Details: **Step 0** in [docs/ROADMAP.md](docs/ROADMAP.md).
2. Put your API keys in `.env` (`OPENROUTER_API_KEY_1`…, `GROQ_API_KEY_1`…).
3. How to activate the virtual environment:

   ```powershell
   # PowerShell
   .\.venv\Scripts\Activate.ps1
   ```

   ```bash
   # Git Bash
   source .venv/Scripts/activate
   ```

   If PowerShell blocks the script, run this once:
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## Backend

From the `backend` folder, with `.venv` active:

```powershell
pip install -r requirements-dev.txt   # first time, and after pulling new packages
alembic upgrade head                  # apply database migrations (again after each step)
uvicorn app.main:app --reload         # API docs: http://127.0.0.1:8000/docs
pytest                                # tests (need the test database, see ROADMAP Step 1)
python scripts/make_sample_data.py    # sample CSV, JSON Lines and a local Delta table in data/samples
```

Health check: `GET http://127.0.0.1:8000/api/v1/health` returns `200` when PostgreSQL, pgvector, and pg_trgm are all OK, and `503` otherwise, saying which one failed.

## Frontend

From the `frontend` folder (Node 22). Keep the backend running at the same time:

```powershell
npm install          # first time only
npm run dev          # http://localhost:5173
```

**First visit:** you create the admin account. There is no public sign-up; the admin adds everyone else on the Users page.

Pages so far:
- **Ask** (everyone; the home page for viewers). It opens in your **general chat** (no data; attach documents with the paperclip or by dropping files, and ask about them; a file belongs to that one chat) and a switcher at the top moves to any of your spaces. Type **@** to point a question at a document (for example `@sales_policy_2025`). While an answer is written an animated eye shows the assistant is thinking, and the thought process appears step by step as a checklist, then the answer streams in as formatted Markdown (headings, lists, tables). Results show as a sortable, formatted table and as a chart chosen from the data: **one chart per analysis, with nothing to configure** (no type switcher or editor) and a single *Download PNG* button. A question that asks for several breakdowns (for example by gender and by birth year) gets one chart for each, never one chart that mixes them on one axis. Ask for them **combined** (or together, or in one graph) and the assistant groups by both, giving grouped bars: for each birth year, one bar per gender. If it stacks them anyway when you asked for combined, the app sends it back once to redo the query. Figures of different kinds are never drawn together: an average, a count and a total each get a chart of their own (horizontal, ranked bars with the value on each bar when there are many categories), and a result that compares several measures shows the overall figures above them, asked of the database as the same query without its grouping. When a question names several figures, the assistant lists them and the app checks that every one is a column of the result, asking for one redo if not, and saying so in the answer if it still is not; the summary covers every figure and who leads on each. CSV export is in the Table view. Ask in plain English and get the answer, the table, a chart and the SQL. Before an answer is trusted the assistant is shown how far each date column's data runs, and a filtered query that finds nothing (or only empty values) is checked once against those ranges instead of reporting a flat "no rows". Conversations are saved per person, follow-up questions understand the earlier ones, and you can edit a question and run it again. The SQL is under a collapsed panel (editors can edit and run it, or save it as an example); results download as CSV; every chart can be saved as a PNG (Download PNG). Documents are read through retrieval: only the best-matching passages (a few thousand characters, shared fairly between the documents of a chat, so "compare both" sees each) go to the model, never a whole file, and each document is listed once under the answer. The welcome screen has suggested questions; there is no Ask/Search switch: a request that clearly asks to find a table, column, term or document ("find the salary table", "which columns have dates") shows a search of what the space holds, with a button to ask it as a question instead, and anything else is a question.
- **Working with answers.** **Pin** a chat to keep it at the top of the list (rename and delete are there too); a new chat is titled by the first clause of its question, not the whole paragraph. Every answer can be saved: **CSV** (all rows), **Excel** (the rows on one sheet, the question, answer, overall figures and SQL on another) and **PDF** (the browser's print dialog, laid out on white with the charts; choose *Save as PDF*). **Quick / Standard / Deep** under the question box: *Quick* uses a faster model and writes the answer from the rows, *Standard* is one checked query, and *Deep* splits a big request (a whole workforce analysis, say) into up to five separate analyses, each written, checked, repaired and shown on its own with its own table, chart and SQL, then lists the assumptions and what the data could not answer; a part that fails does not sink the others, and no result row goes to the AI service. Answers that came from a query an editor saved as Trusted show a **Verified query** mark, and editors are offered *Save as a verified example* under a good answer. **Share** a chat so the other members of the space can read it (not change it) and **branch** it into a chat of their own, or branch any of your answers; sharing is switched off in a space that has access rules, because a shared chat holds results read under its owner's permissions.
- **Spaces** (editors and admins; the home page for them). **Settings → About** holds the tags, the suggested questions shown on a new chat, and the owner; **Knowledge → Business definitions** holds measures, filters and groupings written as SQL (tested before they are saved; default filters are added to every question that uses their table) and "when to ask" rules for ambiguous questions: a space holds tables and the people who can use them. Editors upload files (CSV, TSV, Excel, Parquet, JSON), add local Delta tables by folder, preview data, and run read-only SQL. Only an administrator adds people to a space or changes their role (the server refuses it from anyone else). The **Metadata** tab shows what the AI knows about the data: column statistics, descriptions and synonyms (editable, with an AI draft), hidden columns, searchable values, and joins between tables. The **Knowledge** tab holds instructions, glossary terms, example SQL (with a Trusted mark) and documents. **Settings** has a search tester that shows what the AI would be given for a question.
- **Sign in / Setup**, and **Account**: your profile, your **appearance** and your password change. Appearance has the mode (System, Light or Dark) and a **color template**: *Default* (teal), *Claude* (warm ivory and a clay accent) or *ChatGPT* (neutral grays and a green accent), each in light and dark with a live preview. The choice applies at once and is remembered in this browser.
- **Monitoring** (admin): how questions are being answered across all spaces (volume, failures, speed, feedback), a filterable list of every question, and a review queue. An admin can mark an answer resolved or dismissed, or save a verified corrected SQL as an example. Result data is never shown there.
- **Users** (admin): add people, set their role (admin / editor / viewer), set a password, turn an account off.
- **System status** (admin): database checks, every AI key (masked) and model, and call counts.

Checks: `npm run typecheck`, `npm run lint`, `npm test`, `npm run build`. The design rules are in [frontend/DESIGN.md](frontend/DESIGN.md).

## External databases (connections) — Phases 1 to 4

Admins can save connections to an external **PostgreSQL** server (`/api/v1/connections`, admin only).
Phase 1 saves, tests and audits a connection. Phase 2 reads its structure and lets a space use chosen tables. Phase 3 answers questions on it. Phase 4 adds the admin screens and benchmarks. Nothing connects by itself: every connection is made by an
admin, to a host the admin typed.

**Set up**

1. Make an encryption key and put it in `.env` (it encrypts the saved passwords, so keep a backup):
   `python -c "from app.core.vault import generate_key; print(generate_key())"` -> `CONNECTION_ENCRYPTION_KEY=...`
   To change it later, move the old one to `CONNECTION_ENCRYPTION_KEY_PREVIOUS`; saved passwords are re-encrypted the next time each connection is tested.
2. On the database server, make a login that can only read the tables you want to analyse:

```sql
CREATE ROLE eoe_reader LOGIN PASSWORD '<a long random password>';
GRANT CONNECT ON DATABASE sales TO eoe_reader;
GRANT USAGE ON SCHEMA public TO eoe_reader;
GRANT SELECT ON public.orders, public.customers TO eoe_reader;   -- only what should be analysed
```

3. Add the connection and press **Test**. A login that can change data, create objects, or is a
   superuser is marked **unsafe** and is not used. The database login is the real security wall;
   SQL checking in the app is only the first one.

**What protects it**

- Passwords are encrypted (AES-256-GCM) with a key that lives only in `.env`, bound to their row, and are never returned by the API, logged, or sent to the AI model. Log lines are also scanned and any `password=` or `user:pass@` is hidden.
- Hosts are checked on save and on every test: no URLs, no this-machine (`localhost`) unless `EXTERNAL_DB_ALLOW_LOOPBACK=true` (development only), no link-local or cloud-metadata addresses, never this app's own database. `EXTERNAL_DB_ALLOWED_HOSTS` can limit the hosts to a list.
- TLS with certificate checking (`verify-full`) is the default. A plain-text connection to a public address is refused.
- Every create, change, test and delete is in the audit trail (`GET /api/v1/connections/audit`), without secrets.

**Known limit:** the host name is resolved by the app and again by the database driver. A DNS answer that changes in between is not caught by the address check; certificate checking (`verify-full`, the default) and `EXTERNAL_DB_ALLOWED_HOSTS` close it.

**Phase 2: choosing tables (admins only)**

- `GET /api/v1/connections/{id}/schema` lists the tables and views the login can read, with columns, types, comments, primary keys and foreign keys. Only the database's catalogs are read, never rows. A table, column or schema the login cannot read is not listed, so the database's own permissions decide what can ever be offered. The connection must be tested first, and the login is re-checked as read-only on every use.
- `POST /api/v1/spaces/{space_id}/tables/external` attaches chosen tables to a space (at most 50). Columns are read from the database at that moment, not from the browser. Table and column comments become the starting descriptions; foreign keys become **confirmed** joins (a key over several columns is reported as skipped). Nothing is copied. A space uses either files or one connection. Customer values are not shared with the AI or indexed unless an admin switches that on per column.
- `POST /api/v1/spaces/{space_id}/tables/external/refresh` compares the saved tables with the database. Without `?apply=true` it only reports (new, removed or retyped columns, tables that are gone, foreign-key changes). Applying keeps editors' descriptions and hand-made joins, and never deletes a table.
- A connection that has tables cannot be deleted, and its host, port and database cannot change.
- Profiling and join-guessing are file features and are refused for these tables (their descriptions come from the database's comments, their joins from its foreign keys).

**Phase 3: asking questions of the database**

Questions, edited SQL, table previews, saved examples and definitions all go through one checked path: *guard, then read-only run*.

1. **SQL guard** (`app/engine/pg_sql_guard.py`). One statement, and only a query. Anything that writes, locks, sets or reads files is refused wherever it appears (also inside a sub-query or CTE). Functions must be on an allow-list (`set_config`, `pg_read_file`, `dblink`, `pg_sleep` and every other unlisted function are refused). Only the space's own tables, by plain name: no schemas, no system tables. Columns are checked against what the space shows the assistant: a column an admin hid cannot be named in any clause or spelling, `SELECT *` expands only to visible columns, and whole-row references are refused. The text sent to the database is generated from the checked query (real, quoted `"schema"."table"` names, a row cap) and checked once more.
2. **Read-only run.** A fresh connection per use. Before each use the login is re-checked as read-only, and the query runs in a read-only transaction with its own statement timeout and a row cap. Stop cancels the query on the server.
3. **Errors** from the database are shortened to what the assistant needs to correct a query (for example *column "x" does not exist*); anything about the server, login or network gets a fixed message.

The assistant writes PostgreSQL for these spaces, using your rules, terms, joins, hidden columns and trusted examples. Example SQL and definitions are saved only after they have run on the database.

**Your data and the AI service.** The question, the table and column names and their descriptions are sent to the AI service. **Result rows are not**, unless an admin turns on *share results with the AI* for the connection (off by default). With it off, the summary and chart are made locally from the rows, no explanation call is made, and earlier answers' text is kept out of later prompts. Values of columns are not shown to the AI or indexed unless switched on per column.

**Limits.** Only PostgreSQL. SQL the guard cannot understand is refused, so an unusual function or syntax may need to be rewritten (the assistant is told why and tries again). Column names with capital letters must be quoted, as in PostgreSQL. Hidden-column enforcement applies to external databases; for uploaded files, hidden columns are hidden from the assistant but not blocked in SQL. For enforcement that holds for every query on any space, use an access rule.

**Phase 4: screens and benchmarks**

- **Connections page** (admins, in the side menu): add, edit, test and delete connections; the test shows exactly why a login was refused (for example *can change data in "public"."orders"*); a copy-ready script for a read-only login; the activity trail. The password field is write-only (leave it empty when editing to keep the saved one). The *let the AI service see result rows* switch is here, off by default.
- **Data tab of a space** (admins): pick tables from a connection (searchable, with columns, keys and comments; at most 50), then *Check for changes* / *Apply these changes* to follow the database. A space uses uploaded files or one database, so the upload controls hide for a database space. On the Metadata tab, file-only buttons (profiling, finding joins, value toggles) are hidden for database tables; *Hide from AI* also blocks the column in SQL.
- **Benchmarks tab** (editors): a benchmark is a question plus SQL known to answer it. *Run* lets the assistant answer each question itself (same context, SQL guard and repair attempts as in a chat) and compares the **result rows** with the reference, never the SQL text. The same rows in any order are right unless a question is marked *row order matters* (rankings). Values are compared, not column names, and numbers to about 9 digits. Outcomes: correct, wrong result, no working query, no query written (it asked or declined), reference broken (set aside from the score). Stored details say how many rows differ but never quote a value, so a database's rows are not copied into the app. A run goes on in the background, one at a time per space, and each question costs one or more AI calls (up to `BENCHMARK_MAX_ITEMS`, default 50, per space). Passing a benchmark shows the assistant answers these questions correctly; it is not a guarantee for other questions.

**Permissions, compared with Databricks Genie**

| Layer | Here |
|---|---|
| Who can use the assistant | Space roles: *viewers* ask questions, *editors* change the space, admins manage everything. People who are not members cannot see the space at all. |
| Which data it may use | Only tables an admin attached to the space (at most 50). A table the login can read but nobody attached, or one created later, is refused until an admin attaches it. |
| Which SQL may run | Read-only: the SQL guard, a login that is checked as read-only before every use (a login that can change data, create objects or is a superuser is refused, like not granting MODIFY or MANAGE), and a read-only transaction. |
| Which columns | Columns an admin hides cannot be named in SQL; the login's own column privileges and row-level-security policies are applied by PostgreSQL itself. |
| Who manages connections | Admins only (like USE CONNECTION). Space editors cannot attach a database's tables. |

**What is different, and what closes the gap.** Genie evaluates data permissions as *each person asking*. This app still uses **one saved login per connection** to reach the database, so per-person *database* identities are not supported. What it adds is **access rules** (below), enforced in the app where every query is checked, so different people see different columns and rows of the same tables. For a stronger guarantee than the app's own guard, make a separate read-only login (and connection and space) for each group, or use PostgreSQL row-level security tied to that login.

**Access rules (Access tab of a space, admins only).** Three kinds: *hide a column* (it does not exist for them: not in `SELECT *`, not by name), *show a column as empty* (every value reads NULL) and *show only some rows* (a condition such as `region = 'West'`). A rule is for the space's viewers, for its viewers and editors, for everyone including admins, or for one named person. Rules are applied where data is read, so they hold for the assistant, the SQL tab, previews, joins, CTEs and sub-queries alike: a file space's DuckDB views are built without the hidden columns and only with the permitted rows, and the PostgreSQL guard puts a filtered sub-query in front of every table it rewrites. A row filter may only compare the table's own columns with values (no sub-queries, other tables or functions) and must run on the table before it is saved. The assistant is never told about a column that is hidden or masked for the person asking, nor offered its values. Only admins can read or change rules, since an editor could otherwise lift the rule that limits them. Limits: the rules restrict what queries return; they are not a defence against someone with direct access to the database or the files, and the Metadata tab (a management screen for editors) still shows a hidden column's statistics.

**Chatting with a database:** on the Connections page, press *Chat with it* on a working connection. It creates a space, takes you to the table picker, and *Start chatting* appears once tables are added. The space then appears in the chat's space switcher like any other.

**Keeping `postgres` (or another powerful login) without ever using it for questions**

A login that can change data, create objects or is a superuser is never used to answer questions. You do not have to give it up, though: it can be used **once**, to make a read-only login.

- *Add connection -> Make one for me*: type the admin login (for example `postgres`) and its password. The app uses it once to create a login named `eoe_reader_<random>` with a random password that **can only SELECT** (no superuser, no create database/role, no replication, no row-level-security bypass, no right to create anything), grants it `CONNECT` and `SELECT` on the tables of the schemas you name (every non-system schema if you leave it empty), and saves **only the new login**. The admin password is never stored, logged or returned.
- A connection that is already saved with a powerful login shows **Make it read-only**. It does the same with the saved login, switches the connection to the new read-only login, and replaces the stored password, so the powerful one is no longer kept.
- It all happens in one transaction: a failure leaves no half-made login. No existing login, table or setting is changed, and tables created later are not readable by the new login until it is granted them (and an admin attaches them to a space).
- The admin login must be able to create logins (a superuser, or one with CREATEROLE); otherwise the app says so and the script on the Connections page can be used instead.

**Table sizes.** PostgreSQL only knows a table's size after the table has been analysed, so a database table's row count is often unknown. It is then shown as "size not known" (stored as -1), never as 0, and the assistant is told it may not conclude that a table is empty from a size. Sizes that are known are marked "about", because they are estimates.

**Questions with answers to pick from.** When the assistant needs to ask something ("Which revenue do you mean?"), it also offers 2 to 4 short answers that the data can actually give. The answer card shows them as chips you can tick (one or several), with a box to write your own or add words; *Send* sends it as your next message and the assistant reads it together with its question. The answers are saved with the message, so they are still there after a reload; only the latest question in a chat can be answered this way.

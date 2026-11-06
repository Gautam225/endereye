# Genie Agent Context Components

Oct 27, 2026 · @dhruv

## Overview

A Genie Agent (renamed from Genie space) is a curated configuration that domain experts fill with datasets, sample queries and text guidance, so Genie can turn business questions into SQL. Genie runs on a compound AI system: several interacting components rather than one large language model. ([Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts))

When a question arrives, Genie filters the available context and keeps only what is relevant to that question. The official docs list the context it draws on:

| Context given to the model | What it contains | How Genie uses it |
| --- | --- | --- |
| Unity Catalog table metadata | Table names, descriptions, defined primary key and foreign key relationships | Converts the prompt to SQL |
| Column names and descriptions | Column-level metadata | Filtered to the relevant columns |
| Knowledge store context | Agent-level metadata added by authors, including column values useful for query generation | Used without changing Unity Catalog metadata |
| Example SQL queries | Queries saved under SQL Queries | Only the relevant examples are selected |
| SQL functions | Every SQL function added to the agent | All are included |
| Instructions | Text saved as General instructions | Included as plain-text guidance |
| Prompt and response history | The current chat | Oldest turns are dropped if token limits are reached |

Two things are deliberately not context. Benchmarks are used only to measure accuracy; Genie never learns from benchmark questions or their SQL. Details such as table owner and table size are also excluded by default; information schema views can expose them. ([Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts))

The four boxes in the architecture map onto this list: Instructions supply rules and terms, Example SQL supplies query patterns, Trusted assets supply verified SQL, and the Knowledge store supplies synonyms, joins and other semantic definitions.

&#91;image: Databricks Genie architecture: entry points, Genie Agent components, AI engine, Unity Catalog, execution and data sources\]

## Instructions (rules, terms)

Instructions are plain-text notes, written in the **Text** tab, that tell Genie how to read your data and answer questions. They can cover business rules, preferred terminology, date formats and other domain context. ([Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts))

**What they give the model.** General text instructions are applied to every prompt. They help Genie handle the jargon, logic and concepts specific to a domain. You can write one comprehensive note or group instructions by topic. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

**Types of rules and terms Databricks shows as examples:**

| Category | Documented example |
| --- | --- |
| Company-specific business information | The fiscal year starts in February, so FY26 runs from 1 February 2026 to 31 January 2027 |
| Formatting: response language | Always answer in Spanish |
| Formatting: numbers | Round decimals to two places unless told otherwise |
| Formatting: identifiers | Leave out commas in any column whose name contains Id, id or \_id |

**When not to use them.** Text instructions are only for context that applies globally and fits no other format. Guidance relevant to just some questions belongs in an example query, a SQL function, or table comments and metadata. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

**Keep them consistent.** Genie is nondeterministic, so conflicting or ambiguous guidance raises the risk of unwanted answers. Reviewing and resolving inconsistencies is a key setup task. Business logic defined as SQL expressions gives more consistent results than text instructions, because Genie applies the SQL exactly rather than interpreting prose. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

## Example SQL (query patterns)

Example SQL queries are reference answers to common questions, managed in the **Examples** tab of **Configure**. Genie picks the relevant ones from the agent's query library for each question. ([Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts))

**What they give the model.** Each example pairs a sample question with the SQL that answers it. Databricks lists two ways Genie uses them ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality)):

- **Matching question:** Genie can run the example query directly as the answer.
- **Similar question:** Genie borrows clues from the example to shape the SQL it writes.

**How to write them.** Title each example with the most typical way a user would phrase the question, which helps Genie match prompts to it. Focus on logic unique to your organization and data. Databricks' own sample returns total open pipeline by region, counting an opportunity only when it is tagged as pipeline and its stage is not closed. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

**Static or parameterized.** Queries can be fixed or take parameters. A parameter is added with **Add parameter** or by typing a colon and a name, such as `:parameter_name`, in the editor. Each parameter has three settings ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality)):

| Setting | Detail |
| --- | --- |
| Keyword | The name used in the query; changed only by editing the query text |
| Data type | String (default), Date, Date and Time, Decimal or Integer |
| Comment | Describes allowed values or limits, helping Genie pick the right value |

If a user's input does not match the parameter's data type, Genie treats it as the wrong type, which can produce inaccurate results.

**Usage guidance.** Each example can carry a note explaining when it is especially relevant, added under **Usage guidance** on the example. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

**Example SQL vs SQL expressions.** SQL expressions define reusable business concepts, while example queries teach Genie how to approach common question formats. For instance, if users often ask for "a breakdown of performance," an example query can show that this means closed sales by region, sales rep and manager. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

Users with CAN EDIT permission on the agent can see the query behind each response, which helps troubleshooting.

## Trusted assets (verified SQL)

Trusted assets are parameterized example queries and SQL functions whose exact logic an agent author has verified. When Genie answers with one, the answer comes from that verified logic, and Genie marks it as a verified answer. ([Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts), [Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

| Trusted asset type | What it gives the model | When it produces a verified answer | Required permission |
| --- | --- | --- | --- |
| Parameterized example SQL query | A fixed query structure with typed parameters that Genie fills from the user's question | In chat mode, when the exact text of the parameterized query is used in the response; users can then edit the parameter value and rerun it | Authors need at least CAN EDIT on the agent to add or remove trusted assets |
| SQL function registered in Unity Catalog | A callable function Genie runs with parameters from the user; scalar (returns one value) or table-valued (returns rows) | When Genie calls the function to answer | Users need EXECUTE on the function |

Source for the table: [Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality)

**Why SQL functions are different.** Functions suit questions whose logic is too complex for a static or parameterized query. Genie cannot see or change the SQL inside a function, so this approach fits logic that should stay hidden or fixed. The function's description is shown next to it when attached to an agent, and functions can be shared across teams. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

**Context treatment.** Every SQL function added to the agent is included in Genie's context, while example queries are filtered for relevance. ([Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts))

## Knowledge store (synonyms, joins)

The knowledge store is a set of curated semantic definitions scoped to one agent; it never changes Unity Catalog metadata or other Databricks assets. It has five parts. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

| Part | What it gives the model |
| --- | --- |
| Agent-level metadata | Agent-specific descriptions for tables and columns, plus business terms and synonyms |
| Agent-level data customization | Focused datasets, for example with columns hidden, without changing the underlying tables |
| Prompt matching | Real column values that help Genie match the user's words to data and correct misspellings |
| Join relationships | Defined table relationships so Genie writes correct JOIN statements |
| SQL expressions | Structured definitions of measures, filters and fields (dimensions) that capture business logic |

### Table and column metadata

The default table description is the Unity Catalog one; authors can edit it with directions that help Genie write SQL for the agent, or reset it. For each column, authors can set an agent-specific description and **synonyms**: business terms and keywords that link user language to column names. Hiding a column removes it from Genie's context without affecting the data or permissions. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

### Prompt matching

User questions are conversational and may contain misspellings, so their values may not match the data. Databricks' example: asked about car sales in Florida, Genie without access to the `state` values might filter on `ILIKE '%Florida%'` and find nothing; with entity matching it knows the data stores `FL` and filters on `state = 'FL'`. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

| Component | What it provides | Limits and rules |
| --- | --- | --- |
| Format assistance | Representative values for all eligible columns, showing data types and formatting patterns | Values are generated with the author's data permissions and shared with all agent users; turning it off also turns off entity matching |
| Entity matching | Curated lists of distinct values for columns users name specific entries in (state codes, product categories, status codes, department names) | Up to 120 columns; up to 1,024 distinct values per column, each up to 127 characters; string columns only; requires format assistance; stored in the workspace storage bucket |

Row filters exclude a whole table from prompt matching; column masks exclude only the masked columns. Authors must turn off entity matching for views over filtered or masked tables and for dynamic views. When new values appear or formats change, use **Refresh prompt matching**. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

### Join relationships

Authors add a join under **Configure > Examples > Add > Joins** by choosing left and right tables, a join condition (for example `accounts.id = opportunity.accountid`, or a SQL expression for complex cases) and a relationship type: many to one, one to many or one to one. For multiple joins between the same tables or self-joins, Genie aliases the right-hand table automatically. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

Primary and foreign keys defined in Unity Catalog are saved automatically as join relationships through knowledge mining. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

### SQL expressions

Each expression has a name, SQL code, synonyms and instructions. Genie applies them exactly as written. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

| Type | What the code does | Databricks example |
| --- | --- | --- |
| Filter | Evaluates to a true/false condition | High-value orders: `orders.amount > 10000`; synonyms large orders, big deals |
| Measure | Aggregates across many rows (KPIs) | Win rate: closed-won count divided by all opportunities; synonyms close rate, conversion rate |
| Field | Transforms each row's value (attributes for grouping) | Deal size: Small under 10,000, Medium under 50,000, otherwise Large |

### Knowledge mining

Genie also suggests knowledge store updates. When an author gives a response a thumbs-up or downloads its results, Genie analyzes the query and may propose new SQL expressions or join relationships for the author to review. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

## Limits and scope

Each Genie Agent has two separate limits: 100 instructions and 200 knowledge store snippets. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

| Limit | Per agent | What counts | What does not count |
| --- | --- | --- | --- |
| Instructions | 100 | Each example SQL query, each SQL function, and the whole General instructions block (counts as one) | Knowledge store items |
| Knowledge store snippets | 200 | Table descriptions, join relationships, SQL expressions (measures, filters, fields) | Text instructions, example queries, SQL functions, column descriptions, prompt matching settings |
| Entity matching | 120 columns | Columns with entity matching on; 1,024 values each, up to 127 characters | Columns with format assistance only |

**Scope.** All knowledge store settings live inside the agent. They do not alter Unity Catalog metadata, so one team can tailor descriptions without affecting others. ([Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality))

**Data access is per user.** Queries run on the warehouse with compute credentials embedded by the author, but Unity Catalog checks data access as each end user. Row filters and column masks apply per user, and a question about data a user cannot access returns an empty response. ([Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts))

**Benchmarks are separate.** They measure accuracy only and are never used as context. ([Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts))

## Best practices from Databricks

Databricks' core advice is to prefer structured SQL context over prose: SQL expressions for business terms, example SQL for complex questions, and text instructions only as a last resort. ([Curate an effective Genie Agent](https://docs.databricks.com/aws/en/genie-agents/best-practices))

**Choosing the right component:**

| Need | Use | Databricks example |
| --- | --- | --- |
| Common metrics, filters or dimensions | SQL expressions in the knowledge store | Define `revenue`, `active_customers`, `gross_margin`, `recent_sales` |
| Hard-to-interpret, multi-part or complex questions | Example SQL queries | "Breakdown my team's performance"; best products among recently joined customers |
| Guidance that only natural language can express | Text instructions | Ask for a time period when customer performance is requested without one; round percentages to two decimals in summaries |

**Other documented recommendations:**

- **Document datasets well.** Quality table and column descriptions in Unity Catalog are critical. Resolve ambiguous columns and pre-join tables with views or metric views.
- **Start small.** Aim for five or fewer tables and limit columns. Agents support up to 50 tables, views or metric views.
- **Keep instructions few and focused.** Too many can lower effectiveness, especially in long conversations, because Genie may struggle to prioritize.
- **Be specific, not vague.** Instead of a general request to clarify sales questions, state exactly which missing details (such as product name and sales channel) trigger a clarification and what to ask.
- **Avoid conflicts across types.** If text instructions say round to two decimals, example SQL must also round to two decimals.
- **Structure clarification rules** with a trigger condition, the missing details, the required action and an example question, placed at the end of general instructions.
- **Customize summaries** with a final section titled "Instructions you must follow when providing summaries." Only text instructions affect summaries; example SQL and SQL expressions do not, and summary length cannot be controlled.
- **Test, then benchmark.** Be the agent's first user, examine the generated SQL, and turn reviewed questions into benchmark questions.

All points above: [Curate an effective Genie Agent](https://docs.databricks.com/aws/en/genie-agents/best-practices)

## Sources

Every fact in this document comes from these official Databricks pages, opened on 27 October 2026:

- [Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts) (Databricks on AWS, last updated 12 October 2026)
- [Tune Genie Agent quality](https://learn.microsoft.com/en-us/azure/databricks/genie-agents/tune-quality) (Azure Databricks, last updated 11 September 2026)
- [Curate an effective Genie Agent](https://docs.databricks.com/aws/en/genie-agents/best-practices) (Databricks on AWS, last updated 11 September 2026)

Genie features change often, and several are in Preview or Beta, so check these pages for your cloud and workspace before relying on a specific limit.

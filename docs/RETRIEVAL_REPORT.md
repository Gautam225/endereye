# Retrieval report (Step 6)

Produced by `tests/test_knowledge.py::test_retrieval_finds_the_right_context_for_a_test_set_of_questions`
(run `pytest tests/test_knowledge.py -k retrieval_finds -s` in `backend` to print it again).

**Setup:** one space with two tables (`sales`, `customers`) with descriptions and synonyms, one detected
join, 3 instructions, 3 glossary terms, 4 example questions with SQL, and one policy document
(Discounts table, Returns, Shipping, Commission). Models: `BAAI/bge-small-en-v1.5` (embeddings) and
`Xenova/ms-marco-MiniLM-L-6-v2` (reranker). Pipeline: vector top 40 + BM25 top 40, fusion, rerank 30,
keep 5 to 10.

| Question | Right passage in final list | Passages shown |
| --- | --- | --- |
| total revenue by region | yes, #1 | 5 |
| which products sell the most | yes, #2 | 5 |
| what was our turnover last month | yes, #1 | 5 |
| how many units were ordered | yes, #1 | 5 |
| price of one item | yes, #1 | 5 |
| when was the order placed | yes, #1 | 5 |
| customer signup date | yes, #1 | 5 |
| list customers by type | yes, #1 | 5 |
| which zone has the highest sales | yes, #1 | 5 |
| how are orders linked to customers | yes, #1 | 5 |
| what is an active customer | yes, #1 | 5 |
| average order value definition | yes, #1 | 5 |
| when does the financial year start | yes, #1 | 5 |
| should cancelled orders count towards revenue | yes, #1 | 5 |
| how many decimals should amounts have | yes, #1 | 5 |
| what is the return window | yes, #1 | 5 |
| what discount does a gold customer get | yes, #1 | 5 |
| is shipping free | yes, #1 | 5 |
| how much commission do sales reps earn | yes, #1 | 5 |
| customers who stopped buying | yes, #1 | 5 |
| monthly trend of revenue | yes, #1 | 5 |
| new customers each month | yes, #1 | 5 |

**Recall: 22/22 = 100%** (target: at least 90%).

**Reading it honestly**

- The space is small (about 30 chunks), so almost any retriever does well. Treat 100% as proof that the
  plumbing works, not as a promise for a large space.
- Every question showed exactly 5 passages: most reranker scores are below the 0.0 threshold, so the
  minimum of 5 applies. Step 12 tunes `RERANK_THRESHOLD` on a larger benchmark.
- "which products sell the most" ranked #2, behind the revenue-by-region example; the right example was
  still shown.

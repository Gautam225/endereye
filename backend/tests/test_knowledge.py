"""Knowledge, documents and search end to end, with the real local models (needs the test DB)."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

import asyncio
import io
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_spaces import admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.services import knowledge

pytestmark = pytest.mark.db

REGIONS = ["North", "South", "East", "West"]
PRODUCTS = ["Laptop", "Monitor", "Webcam", "Keyboard", "Headset"]
STATUSES = ["completed", "completed", "completed", "cancelled", "returned"]


def sales_csv() -> bytes:
    rows = ["order_id,order_date,customer_id,region,product,quantity,unit_price,amount,status"]
    for i in range(1, 61):
        quantity, price = 1 + i % 4, 1000 + 250 * (i % 7)
        rows.append(
            f"{i},2025-{1 + i % 12:02d}-{1 + i % 27:02d},{1 + i % 12},{REGIONS[i % 4]},"
            f"{PRODUCTS[i % 5]},{quantity},{price},{quantity * price},{STATUSES[i % 5]}"
        )
    return ("\n".join(rows) + "\n").encode()


def customers_csv() -> bytes:
    rows = ["customer_id,name,segment,region,joined_on"]
    segments = ["Consumer", "Enterprise", "Small Business"]
    for i in range(1, 13):
        rows.append(f"{i},Customer {i},{segments[i % 3]},{REGIONS[i % 4]},2024-{i:02d}-15")
    return ("\n".join(rows) + "\n").encode()


POLICY = """# Sales Policy 2025

This policy explains discounts, returns, shipping and commission for the sales team.

## Discounts

Discounts apply from the second quarter and depend on the customer tier.

| Tier | Discount | Minimum yearly spend | Free shipping |
| --- | --- | --- | --- |
| Bronze | 5% | 10000 | No |
| Silver | 10% | 50000 | No |
| Gold | 15% | 100000 | Yes |
| Platinum | 25% | 500000 | Yes |

## Returns

Returns are accepted within thirty days of delivery. The product must be unused and in its
original packaging. Refunds are paid to the original payment method within seven working days.

## Shipping

Orders above 5000 rupees ship free. Smaller orders pay a flat fee of 99 rupees. Delivery
takes three to five working days inside India.

## Commission

Sales representatives earn 2 percent commission on completed orders. Commission is paid every
quarter, after returns have been deducted.
"""

# (table, column) -> (description, synonyms)
COLUMNS = {
    ("sales", "amount"): ("Order value in rupees after discount", ["revenue", "turnover"]),
    ("sales", "quantity"): ("Number of units ordered", []),
    ("sales", "unit_price"): ("Price of one unit in rupees", []),
    ("sales", "order_date"): ("Date the order was placed", []),
    ("sales", "region"): ("Sales region of the order", ["zone"]),
    ("sales", "status"): ("Order state: completed, cancelled or returned", []),
    ("customers", "segment"): ("Customer type: Consumer, Enterprise or Small Business", []),
    ("customers", "joined_on"): ("Date the customer signed up", ["signup date"]),
    ("customers", "name"): ("Full name of the customer", []),
}
ITEMS = [
    {
        "kind": "instruction",
        "body": "The fiscal year starts on 1 April. FY26 runs from 1 April 2025 to 31 March 2026.",
    },
    {"kind": "instruction", "body": "Always exclude cancelled orders when calculating revenue."},
    {"kind": "instruction", "body": "Round money to two decimals and show amounts in rupees."},
    {
        "kind": "glossary",
        "title": "Active customer",
        "body": "A customer with at least one completed order in the last 90 days.",
    },
    {
        "kind": "glossary",
        "title": "Average order value",
        "body": "Total revenue divided by the number of completed orders. Also called AOV.",
    },
    {
        "kind": "glossary",
        "title": "Churned customer",
        "body": "A customer who has not placed a completed order in the last 180 days.",
    },
    {
        "kind": "example_sql",
        "title": "What is the total revenue by region?",
        "body": "SELECT region, sum(amount) AS revenue FROM sales "
        "WHERE status = 'completed' GROUP BY 1",
        "trusted": True,
    },
    {
        "kind": "example_sql",
        "title": "Which are the top 5 products by revenue?",
        "body": "SELECT product, sum(amount) AS revenue FROM sales WHERE status = 'completed' "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
    },
    {
        "kind": "example_sql",
        "title": "Show the monthly revenue trend",
        "body": "SELECT date_trunc('month', order_date) AS month, sum(amount) AS revenue "
        "FROM sales WHERE status = 'completed' GROUP BY 1 ORDER BY 1",
    },
    {
        "kind": "example_sql",
        "title": "How many customers joined each month?",
        "body": "SELECT date_trunc('month', joined_on) AS month, count(*) AS customers "
        "FROM customers GROUP BY 1 ORDER BY 1",
    },
]


def build_space(boss: Any, data_dir: Path) -> str:
    space_id = new_space(boss)
    ids = {}
    for name, content in (("sales", sales_csv()), ("customers", customers_csv())):
        response = boss.upload(space_id, f"{name}.csv", content)
        assert response.status_code == 201, response.text
        ids[name] = response.json()["id"]
    boss.patch(
        f"/spaces/{space_id}/tables/{ids['sales']}/metadata",
        json={"description": "One row per customer order, including cancelled and returned ones"},
    )
    boss.patch(
        f"/spaces/{space_id}/tables/{ids['customers']}/metadata",
        json={"description": "One row per customer with their segment and sign-up date"},
    )
    boss.post(f"/spaces/{space_id}/joins/detect")
    metadata = {t["name"]: t for t in boss.get(f"/spaces/{space_id}/metadata").json()}
    for (table, column), (description, synonyms) in COLUMNS.items():
        found = next(c for c in metadata[table]["columns"] if c["name"] == column)
        response = boss.patch(
            f"/spaces/{space_id}/tables/{ids[table]}/columns/{found['id']}",
            json={"description": description, "synonyms": synonyms},
        )
        assert response.status_code == 200, response.text
    for item in ITEMS:
        response = boss.post(f"/spaces/{space_id}/knowledge", json=item)
        assert response.status_code == 201, response.text
    document = boss.post(
        f"/spaces/{space_id}/documents", files={"file": ("sales_policy_2025.md", POLICY.encode())}
    )
    assert document.status_code == 201 and document.json()["status"] == "ready", document.text
    return space_id


def search(boss: Any, space_id: str, question: str) -> dict[str, Any]:
    response = boss.get(f"/spaces/{space_id}/search", params={"q": question})
    assert response.status_code == 200, response.text
    return response.json()


# ── The retrieval evaluation ─────────────────────────────────────────────────


def passage(
    kind: str | None = None,
    header: str | None = None,
    text: str | None = None,
    question: str | None = None,
):
    """A test for one passage: all the given parts must match (case-insensitive)."""

    def matches(p: dict[str, Any]) -> bool:
        return (
            (kind is None or p["source_type"] == kind)
            and (header is None or header.lower() in p["header"].lower())
            and (text is None or text.lower() in p["text"].lower())
            and (question is None or question.lower() in p["meta"].get("question", "").lower())
        )

    return matches


# (question, what the right answer looks like, in the final passages)
EVALUATION = [
    ("total revenue by region", passage("example_sql", question="revenue by region")),
    ("which products sell the most", passage("example_sql", question="top 5 products")),
    ("what was our turnover last month", passage("column", header="sales.amount")),
    ("how many units were ordered", passage("column", header="sales.quantity")),
    ("price of one item", passage("column", header="sales.unit_price")),
    ("when was the order placed", passage("column", header="sales.order_date")),
    ("customer signup date", passage("column", header="customers.joined_on")),
    ("list customers by type", passage("column", header="customers.segment")),
    ("which zone has the highest sales", passage("column", header="sales.region")),
    (
        "how are orders linked to customers",
        passage("table", text="sales.customer_id = customers.customer_id"),
    ),
    ("what is an active customer", passage("glossary", header="Active customer")),
    ("average order value definition", passage("glossary", header="Average order value")),
    ("when does the financial year start", passage("instruction", text="fiscal year starts")),
    (
        "should cancelled orders count towards revenue",
        passage("instruction", text="exclude cancelled"),
    ),
    ("how many decimals should amounts have", passage("instruction", text="two decimals")),
    ("what is the return window", passage("document", text="thirty days")),
    ("what discount does a gold customer get", passage("document", text="| Gold | 15% |")),
    ("is shipping free", passage("document", text="ship free")),
    ("how much commission do sales reps earn", passage("document", text="2 percent commission")),
    ("customers who stopped buying", passage("glossary", header="Churned customer")),
    ("monthly trend of revenue", passage("example_sql", question="monthly revenue trend")),
    ("new customers each month", passage("example_sql", question="customers joined each month")),
]


def test_retrieval_finds_the_right_context_for_a_test_set_of_questions(
    api: TestClient, data_dir: Path
) -> None:
    boss = admin(api)
    space_id = build_space(boss, data_dir)

    lines, found = [], 0
    for question, matches in EVALUATION:
        result = search(boss, space_id, question)
        rank = next((i for i, p in enumerate(result["passages"], 1) if matches(p)), None)
        found += rank is not None
        lines.append(
            f"| {question} | {'yes, #' + str(rank) if rank else 'NO'} | {len(result['passages'])} |"
        )
    recall = found / len(EVALUATION)
    report = "\n".join(
        [
            "| Question | Right passage in final list | Passages shown |",
            "| --- | --- | --- |",
            *lines,
            f"\nRecall: {found}/{len(EVALUATION)} = {recall:.0%}",
        ]
    )
    print("\n" + report)
    assert recall >= 0.9, report


# ── Behaviour ────────────────────────────────────────────────────────────────


def test_search_shows_every_stage_for_every_candidate(api: TestClient, data_dir: Path) -> None:
    boss = admin(api)
    space_id = build_space(boss, data_dir)

    result = search(boss, space_id, "total revenue by region")

    hits = result["hits"]
    assert 5 <= len(result["passages"]) <= 10
    kept = [h for h in hits if h["final_rank"] is not None]
    assert [h["final_rank"] for h in kept] == list(range(1, len(kept) + 1))
    assert hits[: len(kept)] == kept  # kept ones come first
    top = hits[0]
    assert top["fused_rank"] is not None and top["rerank_score"] is not None
    assert top["vector_rank"] is not None or top["bm25_rank"] is not None
    assert set(result["timings_ms"]) == {"embed", "vector", "bm25", "fuse", "rerank", "join"}
    scored = [h["rerank_score"] for h in hits if h["rerank_score"] is not None]
    assert len(scored) <= 30 and scored[: len(kept)] == sorted(scored[: len(kept)], reverse=True)


def test_editing_metadata_updates_what_can_be_found(api: TestClient, data_dir: Path) -> None:
    boss = admin(api)
    space_id = build_space(boss, data_dir)
    sales = {t["name"]: t for t in boss.get(f"/spaces/{space_id}/metadata").json()}["sales"]
    unit = next(c for c in sales["columns"] if c["name"] == "unit_price")
    before = boss.get(f"/spaces/{space_id}/index").json()["chunks"]

    boss.patch(
        f"/spaces/{space_id}/tables/{sales['id']}/columns/{unit['id']}",
        json={"synonyms": ["sticker price", "list price"]},
    )
    found = search(boss, space_id, "what is the sticker price")["passages"]
    boss.patch(
        f"/spaces/{space_id}/tables/{sales['id']}/columns/{unit['id']}", json={"hidden": True}
    )
    after_hide = boss.get(f"/spaces/{space_id}/index").json()["chunks"]
    hidden = search(boss, space_id, "what is the sticker price")["passages"]

    assert any(p["header"] == "sales.unit_price" and "sticker price" in p["text"] for p in found)
    assert after_hide["column"] == before["column"] - 1  # no card for a hidden column
    assert not any(p["header"] == "sales.unit_price" for p in hidden)


def test_an_unchanged_space_is_not_embedded_again(api: TestClient, data_dir: Path) -> None:
    boss = admin(api)
    space_id = build_space(boss, data_dir)

    rebuilt = boss.post(f"/spaces/{space_id}/index/rebuild").json()

    assert rebuilt == {"added": 0, "updated": 0, "removed": 0}
    status = boss.get(f"/spaces/{space_id}/index").json()
    assert status["documents"] == 1 and status["failed_documents"] == 0
    assert status["chunks"]["table"] == 2 and status["chunks"]["column"] == 14
    assert status["chunks"]["instruction"] == 3 and status["chunks"]["glossary"] == 3
    assert status["chunks"]["example_sql"] == 4 and status["chunks"]["document"] >= 4


def test_removing_things_removes_their_chunks(api: TestClient, data_dir: Path) -> None:
    boss = admin(api)
    space_id = build_space(boss, data_dir)
    tables = {t["name"]: t for t in boss.get(f"/spaces/{space_id}/tables").json()}
    items = boss.get(f"/spaces/{space_id}/knowledge", params={"kind": "instruction"}).json()
    document = boss.get(f"/spaces/{space_id}/documents").json()[0]

    assert boss.delete(f"/spaces/{space_id}/tables/{tables['customers']['id']}").status_code == 204
    assert boss.delete(f"/spaces/{space_id}/knowledge/{items[0]['id']}").status_code == 204
    assert boss.delete(f"/spaces/{space_id}/documents/{document['id']}").status_code == 204

    chunks = boss.get(f"/spaces/{space_id}/index").json()["chunks"]
    assert chunks["table"] == 1 and chunks["column"] == 9 and chunks["instruction"] == 2
    assert "document" not in chunks
    assert not list((data_dir / "spaces" / space_id / "documents").glob("*"))
    result = search(boss, space_id, "what is the return window")
    assert not any(p["source_type"] == "document" for p in result["passages"])


def test_knowledge_items_are_validated_and_only_editors_change_them(
    api: TestClient, data_dir: Path
) -> None:
    boss = admin(api)
    space_id = new_space(boss)
    boss.upload(space_id, "sales.csv", sales_csv())
    viewer = person(api, boss, "vera@example.com", "viewer")
    outsider = person(api, boss, "olga@example.com", "editor")
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})
    url = f"/spaces/{space_id}/knowledge"

    assert boss.post(url, json={"kind": "glossary", "body": "no term"}).status_code == 422
    assert boss.post(url, json={"kind": "instruction", "body": ""}).status_code == 422
    assert (
        boss.post(url, json={"kind": "instruction", "body": "x", "trusted": True}).status_code
        == 422
    )
    bad_table = boss.post(
        url, json={"kind": "example_sql", "title": "q", "body": "SELECT * FROM secrets"}
    )
    assert bad_table.status_code == 400
    forbidden = boss.post(
        url, json={"kind": "example_sql", "title": "q", "body": "DROP TABLE sales"}
    )
    assert forbidden.status_code == 400
    item = boss.post(
        url,
        json={
            "kind": "example_sql",
            "title": "Total?",
            "body": "SELECT sum(amount) FROM sales",
            "note": "totals",
        },
    ).json()
    assert (item["trusted"], item["note"]) == (False, "totals")

    updated = boss.patch(f"{url}/{item['id']}", json={"trusted": True}).json()
    assert updated["trusted"] is True
    assert (
        boss.patch(f"{url}/{item['id']}", json={"body": "SELECT * FROM nowhere"}).status_code == 400
    )

    assert viewer.get(url).status_code == 200
    assert viewer.post(url, json={"kind": "instruction", "body": "x"}).status_code == 403
    assert viewer.patch(f"{url}/{item['id']}", json={"trusted": False}).status_code == 403
    assert viewer.delete(f"{url}/{item['id']}").status_code == 403
    assert viewer.get(f"/spaces/{space_id}/search", params={"q": "x"}).status_code == 403
    assert viewer.get(f"/spaces/{space_id}/index").status_code == 403
    assert viewer.post(f"/spaces/{space_id}/index/rebuild").status_code == 403
    assert outsider.get(url).status_code == 404
    assert outsider.get(f"/spaces/{space_id}/search", params={"q": "x"}).status_code == 404


def test_documents_of_every_kind_are_read_and_bad_ones_are_kept_as_failed(
    api: TestClient, data_dir: Path
) -> None:
    docx = pytest.importorskip("docx")
    boss = admin(api)
    space_id = new_space(boss)
    base = f"/spaces/{space_id}/documents"

    word = docx.Document()
    word.add_heading("Warranty terms", level=1)
    word.add_paragraph("Every laptop carries a warranty of twenty four months from purchase.")
    buffer = io.BytesIO()
    word.save(buffer)
    html = (
        b"<html><body><h1>Holiday calendar</h1><p>The office is closed on Diwali.</p></body></html>"
    )
    uploads = {
        "terms.docx": buffer.getvalue(),
        "calendar.html": html,
        "notes.txt": b"Plain notes about the quarterly review meeting.",
    }
    for name, content in uploads.items():
        response = boss.post(base, files={"file": (name, content)})
        assert response.status_code == 201, response.text
        assert (response.json()["status"], response.json()["chunk_count"] > 0) == ("ready", True)

    broken = boss.post(base, files={"file": ("blank.md", b"   \n  \n")})
    assert broken.status_code == 201
    assert broken.json()["status"] == "failed" and broken.json()["chunk_count"] == 0
    assert "blank.md" in broken.json()["error"]
    unsupported = boss.post(base, files={"file": ("movie.mp4", b"1234")})
    assert (unsupported.status_code, code(unsupported)) == (400, "file_type")
    empty = boss.post(base, files={"file": ("empty.txt", b"")})
    assert empty.status_code == 400

    passages = search(boss, space_id, "how long is the laptop warranty")["passages"]
    assert any("twenty four months" in p["text"] for p in passages)
    assert any(
        "Diwali" in p["text"]
        for p in search(boss, space_id, "when is the office closed")["passages"]
    )
    assert [d["status"] for d in boss.get(base).json()].count("failed") == 1
    assert boss.get(f"/spaces/{space_id}/index").json()["failed_documents"] == 1


def test_a_pdf_keeps_its_table_rows_together(api: TestClient, data_dir: Path) -> None:
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4).build(
        [
            Paragraph("Support levels", getSampleStyleSheet()["Heading1"]),
            Table(
                [
                    ["Level", "Response time", "Price"],
                    ["Basic", "two days", "free"],
                    ["Premium", "four hours", "9000"],
                ]
            ),
        ]
    )
    boss = admin(api)
    space_id = new_space(boss)

    response = boss.post(
        f"/spaces/{space_id}/documents", files={"file": ("support.pdf", buffer.getvalue())}
    )

    assert response.json()["status"] == "ready", response.text
    passages = search(boss, space_id, "how fast is premium support")["passages"]
    assert any(
        "Premium" in line and "four hours" in line and "9000" in line
        for p in passages
        for line in p["text"].splitlines()
    )


def test_the_first_question_works_in_an_empty_space(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)

    result = search(boss, space_id, "anything at all")

    assert result["hits"] == [] and result["passages"] == []


def test_no_stored_chunk_is_longer_than_the_embedder_can_read(
    api: TestClient, data_dir: Path, sql: Any
) -> None:
    from app.rag.models import MAX_EMBED_TOKENS, ModelConfig, get_embedder

    models = Path(__file__).resolve().parents[2] / "data" / "models"
    embedder = get_embedder(ModelConfig("BAAI/bge-small-en-v1.5", "unused", models))
    boss = admin(api)
    space_id = build_space(boss, data_dir)
    sentences = (
        f"Clause {i} says region {i % 9} must file a report on day {i % 28}." for i in range(900)
    )
    long_text = " ".join(sentences)
    table_rows = [f"| C{i} | Meaning of code {i} |" for i in range(400)]
    big_table = "\n".join(["| Code | Meaning |", "| --- | --- |", *table_rows])
    documents = {"long.md": f"# Long\n\n{long_text}", "table.md": f"# Codes\n\n{big_table}"}
    for name, body in documents.items():
        response = boss.post(f"/spaces/{space_id}/documents", files={"file": (name, body.encode())})
        assert response.status_code == 201 and response.json()["status"] == "ready"
    boss.post(f"/spaces/{space_id}/knowledge", json={"kind": "instruction", "body": long_text})

    rows = sql("SELECT header, text FROM chunks WHERE space_id = :s", {"s": space_id})

    assert len(rows) > 60  # the big documents alone make dozens of chunks
    longest = max(embedder.count(f"{header}\n{text}") for header, text in rows)
    assert longest <= MAX_EMBED_TOKENS, longest


def test_a_document_is_saved_at_once_and_read_in_the_background(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)

    response = boss.api.post(
        f"/api/v1/spaces/{space_id}/documents",
        headers=boss.headers,
        files={"file": ("policy.md", POLICY.encode())},
    )

    assert response.status_code == 201
    assert response.json()["status"] in ("processing", "ready")
    document = response.json()
    for _ in range(200):
        listed = boss.get(f"/spaces/{space_id}/documents").json()
        if listed[0]["status"] != "processing":
            break
        time.sleep(0.05)
    assert (listed[0]["id"], listed[0]["status"]) == (document["id"], "ready")
    assert listed[0]["chunk_count"] > 0


def test_documents_left_processing_by_a_restart_are_marked_failed(
    settings: Any, api: TestClient, sql: Any
) -> None:
    from app.db.session import create_engine, create_sessionmaker

    boss = admin(api)
    space_id = new_space(boss)
    document = boss.post(
        f"/spaces/{space_id}/documents", files={"file": ("policy.md", POLICY.encode())}
    ).json()
    sql("UPDATE documents SET status = 'processing' WHERE id = :i", {"i": document["id"]})

    engine = create_engine(settings)

    async def restart() -> int:
        try:
            return await knowledge.fail_interrupted_documents(create_sessionmaker(engine))
        finally:
            await engine.dispose()

    assert asyncio.run(restart()) == 1
    listed = boss.get(f"/spaces/{space_id}/documents").json()
    assert listed[0]["status"] == "failed" and "Upload it again" in listed[0]["error"]

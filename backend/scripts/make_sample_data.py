"""Make sample data for trying out spaces (Step 4).

From the backend folder, with .venv active:

    pip install -r requirements-dev.txt     # once: the Delta writer is a dev tool
    python scripts/make_sample_data.py

It writes, under DATA_DIR/samples (data/samples by default):

  sales.csv          600 orders: date, region, city, product, quantity, price, amount
  customers.jsonl    120 customers, one JSON object per line
  orders_delta/      a local Delta table with two versions (an initial load, then an append)

Upload the files on a space's Data tab, and add the Delta table with its folder path
(DATA_DIR is always allowed, so no LOCAL_DATA_ROOTS change is needed). The numbers are
random but the same on every run. Run it again with --force to rebuild the samples.
"""

import argparse
import csv
import datetime as dt
import json
import random
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_FILES = ("sales.csv", "customers.jsonl", "orders_delta")

REGIONS = {
    "West": ["Ahmedabad", "Surat", "Mumbai", "Pune"],
    "North": ["Delhi", "Jaipur", "Lucknow"],
    "South": ["Bengaluru", "Chennai", "Hyderabad", "Kochi"],
    "East": ["Kolkata", "Bhubaneswar", "Patna"],
}
PRODUCTS = {
    "Laptop": 58_000,
    "Monitor": 14_500,
    "Keyboard": 1_800,
    "Mouse": 900,
    "Headset": 3_200,
    "Webcam": 4_100,
}
SEGMENTS = ["Consumer", "Small business", "Enterprise"]


def data_dir() -> Path:
    """DATA_DIR from .env (relative paths start at the project folder), else data/."""
    from dotenv import dotenv_values

    configured = dotenv_values(PROJECT_ROOT / ".env").get("DATA_DIR") or "data"
    path = Path(configured).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def customers(rng: random.Random) -> list[dict]:
    first = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Isha", "Arjun", "Sara", "Vihaan", "Anaya"]
    last = ["Shah", "Patel", "Iyer", "Gupta", "Reddy", "Das", "Mehta", "Nair", "Singh", "Rao"]
    rows = []
    for number in range(1, 121):
        region = rng.choice(list(REGIONS))
        rows.append(
            {
                "customer_id": number,
                "name": f"{rng.choice(first)} {rng.choice(last)}",
                "segment": rng.choice(SEGMENTS),
                "region": region,
                "city": rng.choice(REGIONS[region]),
                "joined_on": (
                    dt.date(2023, 1, 1) + dt.timedelta(days=rng.randrange(900))
                ).isoformat(),
            }
        )
    return rows


def orders(
    rng: random.Random, people: list[dict], first_id: int, count: int, start: dt.date
) -> list[dict]:
    rows = []
    for offset in range(count):
        person = rng.choice(people)
        product = rng.choice(list(PRODUCTS))
        quantity = rng.choices([1, 2, 3, 5, 10], weights=[50, 25, 12, 8, 5])[0]
        price = round(PRODUCTS[product] * rng.uniform(0.9, 1.1), 2)
        rows.append(
            {
                "order_id": first_id + offset,
                "order_date": (start + dt.timedelta(days=rng.randrange(365))).isoformat(),
                "customer_id": person["customer_id"],
                "region": person["region"],
                "city": person["city"],
                "product": product,
                "quantity": quantity,
                "unit_price": price,
                "amount": round(price * quantity, 2),
            }
        )
    return sorted(rows, key=lambda row: (row["order_date"], row["order_id"]))


def write_delta(folder: Path, first: list[dict], second: list[dict]) -> None:
    try:
        import pyarrow as pa
        from deltalake import write_deltalake
    except ImportError:
        sys.exit(
            "The Delta writer is missing. Install the dev tools first:\n"
            "  pip install -r requirements-dev.txt"
        )

    def table(rows: list[dict]) -> "pa.Table":
        columns = {name: [row[name] for row in rows] for name in rows[0]}
        columns["order_date"] = [dt.date.fromisoformat(value) for value in columns["order_date"]]
        return pa.table(columns)

    write_deltalake(str(folder), table(first))  # version 0
    write_deltalake(str(folder), table(second), mode="append")  # version 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="folder to write to (default: DATA_DIR/samples)")
    parser.add_argument("--force", action="store_true", help="replace samples made earlier")
    args = parser.parse_args()

    out = (args.out or data_dir() / "samples").resolve()
    existing = [name for name in SAMPLE_FILES if (out / name).exists()]
    if existing and not args.force:
        sys.exit(
            f"Samples already exist in {out} ({', '.join(existing)}). Use --force to rebuild them."
        )
    out.mkdir(parents=True, exist_ok=True)
    for name in existing:  # only the files this script makes
        target = out / name
        shutil.rmtree(target) if target.is_dir() else target.unlink()

    rng = random.Random(42)
    people = customers(rng)
    sales = orders(rng, people, first_id=1, count=600, start=dt.date(2025, 1, 1))
    with (out / "sales.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(sales[0]))
        writer.writeheader()
        writer.writerows(sales)
    with (out / "customers.jsonl").open("w", encoding="utf-8") as file:
        file.writelines(json.dumps(person) + "\n" for person in people)
    write_delta(
        out / "orders_delta",
        orders(rng, people, first_id=10_001, count=400, start=dt.date(2025, 1, 1)),
        orders(rng, people, first_id=20_001, count=150, start=dt.date(2026, 1, 1)),
    )

    print(f"Sample data written to {out}")
    print(f"  sales.csv          {len(sales)} rows  -> upload it on a space's Data tab")
    print(f"  customers.jsonl    {len(people)} rows  -> upload it too")
    print("  orders_delta/      550 rows, Delta version 1 -> add it with this folder path:")
    print(f"                     {out / 'orders_delta'}")


if __name__ == "__main__":
    main()

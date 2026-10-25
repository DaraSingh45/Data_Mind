"""Deterministic sample data so Data Mind can be tried without your own files.

* customer_churn.csv — a deliberately messy CSV (currency strings, mixed date
  formats, spelling variants, outliers, duplicates, a leaky column).
* retail.db — a SQLite database with customers, products and orders tables
  linked by foreign keys, for trying the database connector.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.config import SAMPLES_DIR

SAMPLES = {
    "customer_churn": {"file": "customer_churn.csv", "title": "Customer churn (messy CSV)",
                       "description": "3,040 telecom customers with currency strings, mixed date formats, spelling variants, outliers, duplicates and a leaky column. Target: churn."},
    "retail_db": {"file": "retail.db", "title": "Retail store (SQLite database)",
                  "description": "Customers, products and orders tables linked by foreign keys. Try joining them in the database connector."},
}


def _churn(rng: np.random.Generator, n: int = 3000) -> pd.DataFrame:
    contract = rng.choice(["Monthly", "Annual", "Two-year"], n, p=[0.55, 0.3, 0.15])
    plan = rng.choice(["Basic", "Standard", "Premium"], n, p=[0.45, 0.35, 0.2])
    region = rng.choice(["North", "South", "East", "West", "Central"], n)
    tenure = rng.integers(1, 72, n)
    tickets = rng.poisson(1.6, n)
    satisfaction = rng.integers(1, 6, n).astype(float)
    last_login = rng.gamma(1.4, 9, n).round()
    base_price = {"Basic": 499, "Standard": 899, "Premium": 1499}
    charges = np.array([base_price[p] for p in plan]) * rng.uniform(0.85, 1.25, n)
    total_spend = charges * tenure * rng.uniform(0.9, 1.1, n)
    age = rng.normal(39, 12, n).clip(18, 80).round()

    logit = (-2.1 + 1.5 * (contract == "Monthly") - 0.9 * (contract == "Two-year") + 0.35 * tickets
             - 0.45 * (satisfaction - 3) + 0.03 * last_login - 0.025 * tenure + 0.0006 * (charges - 900))
    churn = rng.random(n) < 1 / (1 + np.exp(-logit))

    start = pd.Timestamp("2025-10-01") - pd.to_timedelta(tenure * 30, unit="D")
    fmt = rng.choice(3, n)
    signup = [d.strftime(["%Y-%m-%d", "%d/%m/%Y", "%b %d, %Y"][f]) for d, f in zip(start, fmt)]
    gender = rng.choice(["Male", "Female", "male", "M", "female", "F", "MALE"], n, p=[0.32, 0.32, 0.1, 0.08, 0.1, 0.05, 0.03])
    region_messy = np.array([r if rng.random() > 0.12 else rng.choice([r.lower(), f" {r} ", r.upper()]) for r in region])
    sources = ["Google", "Facebook", "Friend", "TV", "Instagram", "Billboard", "Radio", "Newspaper", "Email", "Partner"] + \
              [f"Event {i}" for i in range(1, 16)]
    p = np.array([0.22, 0.18, 0.16, 0.1, 0.1, 0.05, 0.04, 0.03, 0.03, 0.03] + [0.006] * 15)
    referral = rng.choice(sources, n, p=p / p.sum())
    notes_pool = ["", "", "", "Called about billing twice this month and was unhappy with the response",
                  "Asked for an upgrade to premium plan", "Network issues reported in the evening hours",
                  "Very happy with service, recommended to family", "Wants a cheaper plan or will consider switching"]
    refund = np.where(churn, rng.choice(["Yes", "No"], n, p=[0.93, 0.07]), rng.choice(["Yes", "No"], n, p=[0.02, 0.98]))

    df = pd.DataFrame({
        "customer_id": [f"C{i:05d}" for i in range(1, n + 1)],
        "signup_date": signup,
        "gender": gender,
        "age": age,
        "region": region_messy,
        "plan": plan,
        "contract": contract,
        "monthly_charges": [f"₹{c:,.2f}" for c in charges],
        "total_spend": total_spend.round(2),
        "support_tickets": tickets,
        "satisfaction_score": satisfaction,
        "last_login_days": last_login,
        "discount": [f"{d}%" for d in rng.choice([0, 5, 10, 15, 20], n)],
        "referral_source": referral,
        "email": [f"user{i}@example.com" for i in range(1, n + 1)],
        "agent_notes": rng.choice(notes_pool, n),
        "refund_issued": refund,
        "churn": np.where(churn, "Yes", "No"),
    })
    # messiness
    for col, frac in [("age", 0.06), ("satisfaction_score", 0.18), ("gender", 0.03), ("last_login_days", 0.04)]:
        df.loc[rng.random(n) < frac, col] = np.nan
    df["monthly_charges"] = df["monthly_charges"].astype(object)
    df.loc[rng.random(n) < 0.04, "monthly_charges"] = None
    df.loc[rng.choice(n, 12, replace=False), "age"] = rng.choice([150, 199, 5], 12)
    df.loc[rng.choice(n, 25, replace=False), "total_spend"] *= 15
    df["agent_notes"] = df["agent_notes"].replace("", np.nan)
    dups = df.sample(40, random_state=1)
    return pd.concat([df, dups], ignore_index=True)


def _retail(path: Path, rng: np.random.Generator) -> None:
    cats = {"Electronics": (2000, 60000), "Home": (300, 8000), "Fashion": (400, 6000), "Books": (150, 1500), "Sports": (500, 12000)}
    products = []
    pid = 1
    for cat, (lo, hi) in cats.items():
        for i in range(12):
            products.append((pid, f"{cat} item {i + 1}", cat, round(float(rng.uniform(lo, hi)), 2)))
            pid += 1
    cities = [("Mumbai", "Maharashtra"), ("Pune", "Maharashtra"), ("Bengaluru", "Karnataka"), ("Chennai", "Tamil Nadu"),
              ("Kochi", "Kerala"), ("Delhi", "Delhi"), ("Hyderabad", "Telangana"), ("Kolkata", "West Bengal"), ("Jaipur", "Rajasthan")]
    customers = []
    for cid in range(1, 401):
        city, state = cities[rng.integers(len(cities))]
        joined = pd.Timestamp("2023-01-01") + pd.Timedelta(days=int(rng.integers(0, 900)))
        customers.append((cid, f"Customer {cid}", city, state, str(rng.choice(["Consumer", "Corporate", "Home Office"], p=[0.6, 0.25, 0.15])), joined.date().isoformat()))
    orders = []
    for oid in range(1, 4001):
        cid = int(rng.integers(1, 401))
        p = products[int(rng.integers(len(products)))]
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=int(rng.integers(0, 640)))
        season = 1.6 if day.month in (10, 11) else 1.0
        qty = int(max(1, rng.poisson(1.3 * season)))
        orders.append((oid, cid, p[0], day.date().isoformat(), qty, float(rng.choice([0, 0, 0.05, 0.1, 0.2])),
                       str(rng.choice(["Delivered", "Delivered", "Delivered", "Returned", "Cancelled"]))))
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE products(product_id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL);
    CREATE TABLE customers(customer_id INTEGER PRIMARY KEY, name TEXT, city TEXT, state TEXT, segment TEXT, joined_on TEXT);
    CREATE TABLE orders(order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id),
        product_id INTEGER REFERENCES products(product_id), order_date TEXT, quantity INTEGER, discount REAL, status TEXT);
    """)
    con.executemany("INSERT INTO products VALUES (?,?,?,?)", products)
    con.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)
    con.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", orders)
    con.commit()
    con.close()


def ensure_samples() -> None:
    rng = np.random.default_rng(7)
    churn_path = SAMPLES_DIR / "customer_churn.csv"
    if not churn_path.exists():
        _churn(rng).to_csv(churn_path, index=False)
    db_path = SAMPLES_DIR / "retail.db"
    if not db_path.exists():
        _retail(db_path, np.random.default_rng(11))

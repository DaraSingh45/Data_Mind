import pandas as pd

from app.engine.profiler import category_variants
from app.insights.query import _find_columns
from datamind_transformers import parse_numeric


def test_numbers_with_units_and_multipliers():
    s = pd.Series(["₹60,000", "5.53 Lakh", "162,940 km", "18.5k", "1497 CC", "null bhp", "1.2 Cr", "CAR-100996", "Manual"])
    out = parse_numeric(s).tolist()
    assert out[:5] == [60000.0, 553000.0, 162940.0, 18500.0, 1497.0]
    assert pd.isna(out[5]) and out[6] == 12_000_000.0 and pd.isna(out[7]) and pd.isna(out[8])


def test_short_codes_and_aliases_merge():
    fuel = pd.Series(["Petrol"] * 5 + ["petrol", "P", "Diesel", "D", "EV", "Electric", "CNG", "cng"])
    m = category_variants(fuel)
    assert {m.get(v, v) for v in fuel} == {"Petrol", "Diesel", "Electric", "CNG"}
    owner = pd.Series(["First", "1st", "Second", "2nd", "Fourth & Above"])
    assert category_variants(owner)["1st"] == "First"
    # ambiguous code stays as is: 'F' could be First or Fourth
    assert "F" not in category_variants(pd.Series(["First", "Fourth", "F"]))


def test_excluding_one_column_does_not_pull_in_its_neighbour():
    cols = ["Seller Type", "Seller Phone", "Listed Price", "monthly_charges"]
    assert _find_columns("ignore seller phone", cols) == ["Seller Phone"]
    assert _find_columns("charges by month", cols) == ["monthly_charges"]

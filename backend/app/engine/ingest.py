"""Loading raw files robustly: encoding, delimiter and header detection."""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pandas as pd
from charset_normalizer import from_bytes

SUPPORTED = (".csv", ".tsv", ".txt", ".xlsx", ".xls", ".parquet", ".json")


def detect_encoding(raw: bytes) -> str:
    best = from_bytes(raw[:200_000]).best()
    return (best.encoding if best else "utf-8") or "utf-8"


def detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in [",", ";", "\t", "|"]}
        return max(counts, key=counts.get)


def read_any(path: Path) -> tuple[pd.DataFrame, dict]:
    """Reads a data file and returns (dataframe, detection report)."""
    ext = path.suffix.lower()
    report: dict = {"file": path.name, "format": ext.lstrip(".")}
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    elif ext == ".parquet":
        df = pd.read_parquet(path)
    elif ext == ".json":
        df = pd.read_json(path)
    else:
        raw = path.read_bytes()
        enc = detect_encoding(raw)
        text = raw.decode(enc, errors="replace")
        delim = detect_delimiter(text[:20_000])
        report.update(encoding=enc, delimiter={"\t": "tab"}.get(delim, delim))
        df = pd.read_csv(io.StringIO(text), sep=delim, low_memory=False, skipinitialspace=True)
    # Clean header names: strip, collapse whitespace, de-duplicate.
    seen: dict[str, int] = {}
    cols = []
    for i, c in enumerate(df.columns):
        name = " ".join(str(c).split()) or f"column_{i + 1}"
        if name.lower().startswith("unnamed:"):
            name = f"column_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        cols.append(name)
    df.columns = cols
    df = df.dropna(how="all")  # fully empty rows
    df = df.loc[:, ~df.isna().all()] if len(df) else df  # fully empty columns
    report.update(rows=int(len(df)), columns=int(df.shape[1]))
    return df.reset_index(drop=True), report


def to_storable(df: pd.DataFrame) -> pd.DataFrame:
    """Make a dataframe safe to write as parquet (mixed object columns -> string)."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].astype("string")
    return out

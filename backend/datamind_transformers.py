"""
datamind_transformers.py
========================

Portable runtime for pipelines produced by Data Mind.

Every pipeline Data Mind exports (``pipeline.joblib``) is built from a plain
JSON *plan* using the classes in this file. Ship this file next to the
pipeline and you can transform new raw data without Data Mind installed:

    import joblib, pandas as pd
    import datamind_transformers  # noqa: F401  (needed so joblib can unpickle)
    pipe = joblib.load("pipeline.joblib")
    X_new = pipe.transform(pd.read_csv("new_data.csv"))

Only depends on pandas, numpy and scikit-learn.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, OneToOneFeatureMixin, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import (
    MinMaxScaler,
    OneHotEncoder,
    OrdinalEncoder,
    RobustScaler,
    StandardScaler,
    TargetEncoder,
)

# ---------------------------------------------------------------------------
# Value parsing helpers (stateless)
# ---------------------------------------------------------------------------

_CURRENCY_RE = re.compile(r"[\s$€£¥₹,]|(?i:rs\.?|inr|usd|eur)")
_MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "l": 1e5, "lac": 1e5, "lacs": 1e5, "lakh": 1e5, "lakhs": 1e5,
                "cr": 1e7, "crore": 1e7, "crores": 1e7, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
TRUE_SET = {"yes", "y", "true", "t", "1", "1.0", "on"}
FALSE_SET = {"no", "n", "false", "f", "0", "0.0", "off"}


def parse_numeric(series: pd.Series) -> pd.Series:
    """Parse numbers stored as text: '₹1,200', '45%', ' 3.5 ', '(200)'."""
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return series.astype("float64")
    s = series.astype("string").str.strip()
    pct = s.str.endswith("%", na=False)
    neg = s.str.match(r"^\(.*\)$", na=False)
    s = s.str.replace("%", "", regex=False).str.replace(r"[()]", "", regex=True)
    s = s.str.replace(_CURRENCY_RE, "", regex=True)
    s = s.str.replace(r"(?i)^(nan|none|null|n/?a|-|\?|)$", "", regex=True)
    # a number followed by a unit: '5.53lakh', '162940km', '1497cc', '18.5k', '20kmpl', 'null bhp'
    parts = s.str.extract(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)([a-z/]{0,12})$", flags=re.I)
    unit = parts[1].str.lower().fillna("")
    mult = unit.map(_MULTIPLIERS).astype("float64").fillna(1.0)
    s = s.str.replace(r"(?i)^(?:nan|none|null|n/?a)[a-z/]{0,12}$", "", regex=True)  # 'null bhp'
    s = s.where(parts[0].isna(), parts[0])
    out = pd.to_numeric(s.replace("", pd.NA), errors="coerce").astype("float64") * mult.values
    out = out.where(~neg, -out)
    out = out.where(~pct, out / 100.0)
    return out


def parse_datetime(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    s = series.astype("string").str.strip()
    try:
        return pd.to_datetime(s, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(s, errors="coerce")


def parse_boolean(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype("float64")
    s = series.astype("string").str.strip().str.lower()
    out = pd.Series(np.nan, index=series.index, dtype="float64")
    out[s.isin(TRUE_SET)] = 1.0
    out[s.isin(FALSE_SET)] = 0.0
    return out


def normalize_text(series: pd.Series) -> pd.Series:
    s = series.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    s = s.replace(r"(?i)^(nan|none|null|n/?a|-|\?|)$", pd.NA, regex=True)
    return s


# ---------------------------------------------------------------------------
# Stage 1: Cleaner — stateless, turns raw columns into typed, tidy columns
# ---------------------------------------------------------------------------

class Cleaner(BaseEstimator, TransformerMixin):
    """Applies per-column type repair and category normalisation from a plan."""

    def __init__(self, plan: dict | None = None):
        self.plan = plan

    def fit(self, X: pd.DataFrame, y: Any = None):
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        plan = self.plan or {}
        out = {}
        for col in plan.get("columns", []):
            name = col["column"]
            if col.get("role") == "drop" or name not in X.columns:
                continue
            s = X[name]
            fix = col.get("dtype_fix")
            if fix == "numeric":
                s = parse_numeric(s)
            elif fix == "datetime":
                s = parse_datetime(s)
            elif fix == "boolean":
                s = parse_boolean(s)
            elif fix in ("category", "text") or col.get("normalize_text"):
                s = normalize_text(s)
            if col.get("normalize_text") and fix not in ("numeric", "datetime", "boolean"):
                s = normalize_text(s)
                cmap = col.get("category_map") or {}
                if cmap:
                    lower_map = {str(k).strip().lower(): v for k, v in cmap.items()}
                    s = s.map(lambda v: lower_map.get(str(v).strip().lower(), v) if pd.notna(v) else v)
                    s = s.astype("string")
            out[name] = s
        return pd.DataFrame(out, index=X.index)


# ---------------------------------------------------------------------------
# Stage 2: Featurizer — expands datetimes and free text into numeric features
# ---------------------------------------------------------------------------

DATETIME_PARTS = ("year", "month", "day", "dayofweek", "is_weekend")


def _to_float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("float64")


class Featurizer(BaseEstimator, TransformerMixin):
    def __init__(self, plan: dict | None = None):
        self.plan = plan

    def fit(self, X: pd.DataFrame, y: Any = None):
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        X = X.copy()
        for col in (self.plan or {}).get("columns", []):
            name = col["column"]
            if name not in X.columns:
                continue
            if col.get("datetime_features"):
                d = parse_datetime(X[name])
                X[f"{name}__year"] = _to_float(d.dt.year)
                X[f"{name}__month"] = _to_float(d.dt.month)
                X[f"{name}__day"] = _to_float(d.dt.day)
                X[f"{name}__dayofweek"] = _to_float(d.dt.dayofweek)
                X[f"{name}__is_weekend"] = _to_float(d.dt.dayofweek >= 5).where(d.notna())
                X = X.drop(columns=[name])
            elif col.get("text_features"):
                t = X[name].astype("string")
                X[f"{name}__length"] = _to_float(t.str.len())
                X[f"{name}__words"] = _to_float(t.str.split().str.len())
                X = X.drop(columns=[name])
        return X


# ---------------------------------------------------------------------------
# Small learned transformers
# ---------------------------------------------------------------------------

class OutlierHandler(OneToOneFeatureMixin, BaseEstimator, TransformerMixin):
    """clip_iqr: clip to [Q1-1.5IQR, Q3+1.5IQR]; winsorize: clip to [p1, p99];
    log1p: signed log transform. Bounds are learned on training data only."""

    def __init__(self, method: str = "none"):
        self.method = method

    def fit(self, X, y=None):
        A = np.asarray(X, dtype="float64")
        _remember(self, X)
        if self.method == "clip_iqr":
            q1 = np.nanpercentile(A, 25, axis=0)
            q3 = np.nanpercentile(A, 75, axis=0)
            iqr = q3 - q1
            self.lower_, self.upper_ = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        elif self.method == "winsorize":
            self.lower_ = np.nanpercentile(A, 1, axis=0)
            self.upper_ = np.nanpercentile(A, 99, axis=0)
        return self

    def transform(self, X):
        A = np.asarray(X, dtype="float64").copy()
        if self.method in ("clip_iqr", "winsorize"):
            A = np.clip(A, self.lower_, self.upper_)
        elif self.method == "log1p":
            A = np.sign(A) * np.log1p(np.abs(A))
        return A


class RareGrouper(OneToOneFeatureMixin, BaseEstimator, TransformerMixin):
    """Replaces categories rarer than ``threshold`` (share of rows) with 'Other'."""

    def __init__(self, threshold: float = 0.0):
        self.threshold = threshold

    def fit(self, X, y=None):
        A = np.asarray(X, dtype=object)
        _remember(self, X)
        self.keep_ = []
        for j in range(A.shape[1]):
            vc = pd.Series(A[:, j]).value_counts(normalize=True)
            self.keep_.append(set(vc[vc >= self.threshold].index) if self.threshold > 0 else None)
        return self

    def transform(self, X):
        A = np.asarray(X, dtype=object).copy()
        for j, keep in enumerate(self.keep_):
            if keep is not None:
                mask = np.array([v not in keep for v in A[:, j]])
                A[mask, j] = "Other"
        return A


class FrequencyEncoder(OneToOneFeatureMixin, BaseEstimator, TransformerMixin):
    def fit(self, X, y=None):
        A = np.asarray(X, dtype=object)
        _remember(self, X)
        self.maps_ = [pd.Series(A[:, j]).value_counts(normalize=True).to_dict() for j in range(A.shape[1])]
        return self

    def transform(self, X):
        A = np.asarray(X, dtype=object)
        cols = [np.array([m.get(v, 0.0) for v in A[:, j]], dtype="float64") for j, m in enumerate(self.maps_)]
        return np.column_stack(cols) if cols else np.empty((A.shape[0], 0))


class ToObject(OneToOneFeatureMixin, BaseEstimator, TransformerMixin):
    """Casts to object dtype with real NaN so sklearn imputers/encoders accept it."""

    def fit(self, X, y=None):
        _remember(self, X)
        return self

    def transform(self, X):
        df = pd.DataFrame(X).astype(object)
        return df.where(pd.notna(df), np.nan).to_numpy(dtype=object)


class ToFloat(OneToOneFeatureMixin, BaseEstimator, TransformerMixin):
    def fit(self, X, y=None):
        _remember(self, X)
        return self

    def transform(self, X):
        return pd.DataFrame(X).apply(pd.to_numeric, errors="coerce").to_numpy(dtype="float64")


# ---------------------------------------------------------------------------
# Plan -> sklearn pipeline
# ---------------------------------------------------------------------------

def _remember(est, X) -> None:
    """Record input feature names so sklearn's pandas output keeps real column names."""
    est.n_features_in_ = np.asarray(X).shape[1] if np.asarray(X).ndim == 2 else 1
    if hasattr(X, "columns"):
        est.feature_names_in_ = np.asarray(list(X.columns), dtype=object)


_SCALERS = {"standard": StandardScaler, "robust": RobustScaler, "minmax": MinMaxScaler}


def feature_kind(col: dict) -> str:
    """'numeric' or 'categorical' after cleaning, for a feature column."""
    if col.get("kind") in ("numeric", "categorical"):
        return col["kind"]
    if col.get("dtype_fix") in ("numeric", "boolean"):
        return "numeric"
    if col.get("semantic_type") in ("numeric", "boolean", "integer", "float") and col.get("dtype_fix") is None:
        return "numeric"
    return "categorical"


def _numeric_steps(col: dict) -> list:
    steps: list = [("to_float", ToFloat())]
    if col.get("outliers", "none") != "none":
        steps.append(("outliers", OutlierHandler(col["outliers"])))
    strategy = col.get("impute", "median")
    if strategy in ("mean", "median", "most_frequent"):
        steps.append(("impute", SimpleImputer(strategy=strategy, add_indicator=bool(col.get("add_missing_flag")))))
    elif strategy == "constant":
        steps.append(("impute", SimpleImputer(strategy="constant", fill_value=0.0, add_indicator=bool(col.get("add_missing_flag")))))
    else:  # always guarantee no NaN reaches the model
        steps.append(("impute", SimpleImputer(strategy="median")))
    scaler = _SCALERS.get(col.get("scale", "none"))
    if scaler:
        steps.append(("scale", scaler()))
    return steps


def _categorical_steps(col: dict, task: str) -> list:
    steps: list = [("to_object", ToObject())]
    if col.get("impute") == "constant":
        steps.append(("impute", SimpleImputer(strategy="constant", fill_value="Missing")))
    else:
        steps.append(("impute", SimpleImputer(strategy="most_frequent")))
    if float(col.get("rare_threshold") or 0) > 0:
        steps.append(("rare", RareGrouper(float(col["rare_threshold"]))))
    enc = col.get("encode", "onehot")
    if enc == "target" and task in ("classification", "regression"):
        # fixed folds so cross-fitted encodings are reproducible run to run
        steps.append(("encode", TargetEncoder(cv=KFold(n_splits=5, shuffle=True, random_state=0))))
    elif enc == "ordinal":
        steps.append(("encode", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)))
    elif enc == "frequency" or enc == "target":
        steps.append(("encode", FrequencyEncoder()))
    else:
        steps.append(("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=False, max_categories=30)))
    return steps


def _est_name(i: int, name: str) -> str:
    """sklearn estimator names may not contain '__'."""
    return f"t{i}_" + re.sub(r"_{2,}", "_", re.sub(r"[^0-9A-Za-z_]", "_", str(name)))


def build_pipeline(plan: dict) -> Pipeline:
    """Builds the full raw-data -> model-ready pipeline described by ``plan``."""
    task = plan.get("task", "none")
    target = plan.get("target")
    transformers = []
    for col in plan.get("columns", []):
        name = col["column"]
        if col.get("role") != "feature" or name == target:
            continue
        if col.get("datetime_features"):
            for part in DATETIME_PARTS:
                transformers.append((_est_name(len(transformers), f"{name}_{part}"),
                                     Pipeline([("impute", SimpleImputer(strategy="median"))]), [f"{name}__{part}"]))
            continue
        if col.get("text_features"):
            for part in ("length", "words"):
                transformers.append((_est_name(len(transformers), f"{name}_{part}"),
                                     Pipeline([("impute", SimpleImputer(strategy="median"))]), [f"{name}__{part}"]))
            continue
        steps = _numeric_steps(col) if feature_kind(col) == "numeric" else _categorical_steps(col, task)
        transformers.append((_est_name(len(transformers), name), Pipeline(steps), [name]))

    columns = ColumnTransformer(transformers, remainder="drop", verbose_feature_names_out=False)
    columns.set_output(transform="pandas")
    pipe = Pipeline([("clean", Cleaner(plan)), ("featurize", Featurizer(plan)), ("columns", columns)])
    return pipe

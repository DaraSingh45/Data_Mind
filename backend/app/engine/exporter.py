"""Writes every artifact of a run: data, pipeline, reproducible script, report."""
from __future__ import annotations

import html
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib

from ..core.config import TRANSFORMERS_FILE

REPRODUCE_TEMPLATE = '''"""
Reproduces the Data Mind preparation for dataset: {dataset}
Generated {generated}

Usage:
    python reproduce.py path/to/raw.csv            # rebuild the pipeline from the plan and refit
    python reproduce.py path/to/new.csv --apply    # apply the saved, already-fitted pipeline

Requires: pandas, numpy, scikit-learn (and datamind_transformers.py next to this file).
"""
import json
import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.model_selection import train_test_split

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # so datamind_transformers.py next to this file is importable
import datamind_transformers as dmt  # noqa: E402
PLAN = json.loads((HERE / "plan.json").read_text())


def main(path: str, apply_only: bool = False) -> None:
    raw = pd.read_csv(path, low_memory=False)
    if apply_only:
        pipe = joblib.load(HERE / "pipeline.joblib")
        out = pipe.transform(raw)
        out.to_csv(HERE / "transformed_new.csv", index=False)
        print(f"Wrote transformed_new.csv with shape {{out.shape}}")
        return

    target, task = PLAN.get("target"), PLAN.get("task")
    cleaned = dmt.Cleaner(PLAN).transform(raw)
    keep = ~raw.duplicated() if PLAN.get("drop_duplicates") else pd.Series(True, index=raw.index)
    if target:
        keep &= cleaned[target].notna()
    idx = raw.index[keep]
    split = PLAN["split"]
    stratify = cleaned.loc[idx, target].astype(str) if split["strategy"] == "stratified" and target else None
    if split["strategy"] == "time" and split.get("time_column"):
        order = cleaned.loc[idx, split["time_column"]].sort_values(kind="stable").index
        cut = int(len(order) * (1 - split["test_size"]))
        train_idx, test_idx = order[:cut], order[cut:]
    else:
        train_idx, test_idx = train_test_split(idx, test_size=split["test_size"], random_state=split["seed"], stratify=stratify)

    y = None
    if target:
        y = cleaned.loc[train_idx, target]
        y = y.astype(str).astype(object) if task == "classification" else y.astype(float)
    pipe = dmt.build_pipeline(PLAN)
    X_train = pipe.fit_transform(raw.loc[train_idx], y)
    X_test = pipe.transform(raw.loc[test_idx])
    if target:
        X_train[target] = cleaned.loc[train_idx, target].values
        X_test[target] = cleaned.loc[test_idx, target].values
    X_train.to_csv(HERE / "train_reproduced.csv", index=False)
    X_test.to_csv(HERE / "test_reproduced.csv", index=False)
    joblib.dump(pipe, HERE / "pipeline_reproduced.joblib")
    print(f"train {{X_train.shape}}, test {{X_test.shape}} written.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], apply_only="--apply" in sys.argv)
'''


def export_all(run_dir: Path, dataset_name: str, plan: dict, result: dict, checks: dict,
               profile: dict, decisions: list[dict], verdict: dict | None) -> dict[str, Any]:
    out = run_dir / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    result["cleaned"].to_csv(out / "cleaned.csv", index=False)
    result["train"].to_csv(out / "train.csv", index=False)
    result["test"].to_csv(out / "test.csv", index=False)
    joblib.dump(result["pipeline"], out / "pipeline.joblib")
    shutil.copy(TRANSFORMERS_FILE, out / "datamind_transformers.py")
    (out / "plan.json").write_text(json.dumps(plan, indent=2, default=str), "utf-8")
    (out / "decisions.json").write_text(json.dumps(decisions, indent=2, default=str), "utf-8")
    (out / "reproduce.py").write_text(
        REPRODUCE_TEMPLATE.format(dataset=dataset_name, generated=datetime.now().strftime("%Y-%m-%d %H:%M")), "utf-8")
    (out / "report.html").write_text(render_report(dataset_name, plan, result, checks, profile, decisions, verdict), "utf-8")

    files = []
    for p in sorted(out.iterdir()):
        files.append({"name": p.name, "size": p.stat().st_size, "kind": _kind(p.name)})
    with zipfile.ZipFile(run_dir / "datamind_outputs.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in out.iterdir():
            z.write(p, arcname=p.name)
    return {"files": files, "zip": "datamind_outputs.zip"}


def _kind(name: str) -> str:
    return {"csv": "data", "joblib": "pipeline", "py": "code", "json": "plan", "html": "report"}.get(name.rsplit(".", 1)[-1], "file")


def render_report(dataset: str, plan: dict, result: dict, checks: dict, profile: dict,
                  decisions: list[dict], verdict: dict | None) -> str:
    e = html.escape
    st = result["stats"]
    rows_ck = "".join(
        f"<tr><td><span class='pill {c['status']}'>{c['status']}</span></td><td>{e(c['name'])}</td><td>{e(c['detail'])}</td></tr>"
        for c in checks["checks"])
    rows_dec = "".join(
        f"<tr><td><b>{e(c['column'])}</b><div class='muted'>{e(c.get('semantic_type', ''))}</div></td>"
        f"<td>{e(c.get('role', ''))}</td><td>{e(_ops(c))}</td><td>{e(c.get('reason', ''))}</td>"
        f"<td>{e(c.get('source', ''))}</td></tr>"
        for c in plan["columns"])
    base = checks.get("baseline") or {}
    base_html = ""
    if base:
        base_html = (f"<p>Model: {e(base.get('model', ''))} · metric <b>{e(base.get('metric', ''))}</b> · "
                     f"prepared test <b>{base.get('prepared_test')}</b> · naive test <b>{base.get('naive_test')}</b> · "
                     f"CV {base.get('prepared_cv_mean')} ± {base.get('prepared_cv_std')}</p>")
    log_html = "".join(f"<li><b>{e(d.get('stage', ''))}</b> — {e(d.get('message', ''))}</li>" for d in decisions[-60:])
    verdict_html = ""
    if verdict:
        verdict_html = f"<p><b>Verifier:</b> {e(verdict.get('verdict', ''))} — {e(verdict.get('summary', ''))}</p>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Data Mind report — {e(dataset)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:Inter,system-ui,sans-serif;margin:0;background:#0b0f19;color:#e6e8ef}}
main{{max-width:1100px;margin:auto;padding:32px 20px}}h1{{margin:0 0 4px;font-size:28px}}
h2{{margin-top:36px;font-size:18px;color:#a5b4fc}}.muted{{color:#8b93a7;font-size:12px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:20px}}
.card{{background:#131a2a;border:1px solid #232c42;border-radius:12px;padding:14px}}.card b{{font-size:22px;display:block}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}}td,th{{border-bottom:1px solid #232c42;padding:8px;text-align:left;vertical-align:top}}
.pill{{padding:2px 8px;border-radius:99px;font-size:11px;text-transform:uppercase}}.pass{{background:#123b2a;color:#4ade80}}
.warn{{background:#3b2f12;color:#fbbf24}}.fail{{background:#3b1212;color:#f87171}}
</style></head><body><main>
<h1>Data Mind preparation report</h1><div class="muted">{e(dataset)} · generated {datetime.now():%Y-%m-%d %H:%M}</div>
<div class="grid">
<div class="card"><span class="muted">Raw rows</span><b>{st['raw_rows']:,}</b></div>
<div class="card"><span class="muted">Train / test</span><b>{st['train_rows']:,} / {st['test_rows']:,}</b></div>
<div class="card"><span class="muted">Columns → features</span><b>{st['columns_in']} → {st['features_out']}</b></div>
<div class="card"><span class="muted">Duplicates removed</span><b>{st['duplicates_removed']}</b></div>
<div class="card"><span class="muted">Target</span><b>{e(str(plan.get('target') or '—'))}</b></div>
<div class="card"><span class="muted">Checks passed</span><b>{checks['summary']['passed']}/{checks['summary']['total']}</b></div>
</div>
<h2>Verification</h2>{verdict_html}{base_html}
<table><tr><th>Status</th><th>Check</th><th>Detail</th></tr>{rows_ck}</table>
<h2>Column decisions</h2><table><tr><th>Column</th><th>Role</th><th>Operations</th><th>Reason</th><th>By</th></tr>{rows_dec}</table>
<h2>Plan notes</h2><ul>{''.join(f'<li>{e(n)}</li>' for n in plan.get('notes', []))}</ul>
<h2>Agent log</h2><ul>{log_html}</ul>
</main></body></html>"""


def _ops(c: dict) -> str:
    if c.get("role") == "drop":
        return "drop"
    if c.get("role") == "target":
        return "target"
    ops = []
    if c.get("dtype_fix"):
        ops.append(f"cast {c['dtype_fix']}")
    if c.get("category_map"):
        ops.append(f"merge {len(c['category_map'])} variants")
    if c.get("impute") not in (None, "none"):
        ops.append(f"impute {c['impute']}")
    if c.get("add_missing_flag"):
        ops.append("missing flag")
    if c.get("outliers") not in (None, "none"):
        ops.append(c["outliers"])
    if c.get("rare_threshold"):
        ops.append(f"rare<{c['rare_threshold']}")
    if c.get("encode") not in (None, "none"):
        ops.append(f"{c['encode']} encode")
    if c.get("scale") not in (None, "none"):
        ops.append(f"{c['scale']} scale")
    if c.get("datetime_features"):
        ops.append("date features")
    if c.get("text_features"):
        ops.append("text features")
    return ", ".join(ops) or "keep"

"""Data Mind API: datasets, database import, intake chat, agent runs with a
live event stream, results, insights + insight chat, settings."""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import prompts
from .agent.graph import graph_definition
from .agent.intake import intake_reply
from .agent.llm import LLM, ollama_models, test_provider
from .agent.runner import manager, read_meta
from .core.config import DATASETS_DIR, FRONTEND_DIST, RUNS_DIR, SAMPLES_DIR
from .core.events import bus
from .core.settings import load_settings, merge_update, public_settings, save_settings
from .db import connector
from .engine.ingest import SUPPORTED, read_any, to_storable
from .engine.profiler import guess_targets, profile_dataframe
from .insights.engine import detect_roles
from .insights.query import answer
from .samples.generate import SAMPLES, ensure_samples

@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_samples()
    yield


app = FastAPI(title="Data Mind", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


def _json_safe(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


def _preview(df: pd.DataFrame, n: int = 50) -> dict:
    head = df.head(n).astype(object).where(pd.notna(df.head(n)), None)
    return {"columns": [str(c) for c in df.columns], "rows": _json_safe(head.values.tolist())}


# ---------------------------------------------------------------------------
# datasets
# ---------------------------------------------------------------------------

def _save_dataset(df: pd.DataFrame, name: str, source: str, report: dict, original: Path | None = None) -> dict:
    ds_id = uuid.uuid4().hex[:10]
    d = DATASETS_DIR / ds_id
    d.mkdir(parents=True)
    if original is not None:
        target = d / ("raw" + original.suffix.lower())
        shutil.copy(original, target)
    else:
        target = d / "raw.csv"
        df.to_csv(target, index=False)
    prof = profile_dataframe(df)
    (d / "profile.json").write_text(json.dumps(prof, default=str), "utf-8")
    meta = {"id": ds_id, "name": name, "source": source, "file": target.name, "rows": int(len(df)), "columns": int(df.shape[1]),
            "created_at": time.time(), "report": report}
    (d / "meta.json").write_text(json.dumps(meta, default=str), "utf-8")
    return meta


def _dataset(ds_id: str) -> tuple[dict, Path]:
    d = DATASETS_DIR / re.sub(r"[^a-z0-9]", "", ds_id)
    if not (d / "meta.json").exists():
        raise HTTPException(404, "Dataset not found")
    meta = json.loads((d / "meta.json").read_text("utf-8"))
    return meta, d / meta["file"]


def _dataset_payload(meta: dict, path: Path) -> dict:
    df, _ = read_any(path)
    prof = json.loads((path.parent / "profile.json").read_text("utf-8"))
    return {"dataset": meta, "preview": _preview(df),
            "profile": {k: prof[k] for k in ("rows", "columns", "duplicate_rows", "missing_cells_pct", "type_counts", "strong_correlations")}
            | {"columns_detail": [{"name": c["name"], "type": c["semantic_type"], "missing_pct": c["missing_pct"], "unique": c["unique"],
                                   "warnings": c["warnings"], "stats": c.get("stats"), "top_values": c.get("top_values", [])[:6]}
                                  for c in prof["column_profiles"]]},
            "candidates": guess_targets(prof)}


@app.post("/api/datasets/upload")
async def upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "data.csv").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(400, f"Unsupported file type {suffix}. Use CSV, TSV, Excel, Parquet or JSON.")
    tmp = DATASETS_DIR / f"_upload_{uuid.uuid4().hex}{suffix}"
    with tmp.open("wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
    try:
        df, report = read_any(tmp)
        if df.empty:
            raise HTTPException(400, "The file has no rows.")
        meta = _save_dataset(df, file.filename or "upload", "upload", report, original=tmp)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not read this file: {e}")
    finally:
        tmp.unlink(missing_ok=True)
    return _dataset_payload(meta, DATASETS_DIR / meta["id"] / meta["file"])


@app.get("/api/samples")
def samples():
    return [{"id": k, **v} for k, v in SAMPLES.items()]


@app.post("/api/samples/{sample_id}")
def load_sample(sample_id: str):
    if sample_id == "customer_churn":
        path = SAMPLES_DIR / "customer_churn.csv"
        df, report = read_any(path)
        meta = _save_dataset(df, "customer_churn.csv", "sample", report, original=path)
        return _dataset_payload(meta, DATASETS_DIR / meta["id"] / meta["file"])
    if sample_id == "retail_db":
        return {"database_url": f"sqlite:///{(SAMPLES_DIR / 'retail.db').as_posix()}"}
    raise HTTPException(404, "Unknown sample")


@app.get("/api/datasets")
def list_datasets():
    out = []
    for d in sorted(DATASETS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if (d / "meta.json").exists():
            out.append(json.loads((d / "meta.json").read_text("utf-8")))
    return out


@app.get("/api/datasets/{ds_id}")
def get_dataset(ds_id: str):
    meta, path = _dataset(ds_id)
    return _dataset_payload(meta, path)


# ---------------------------------------------------------------------------
# databases
# ---------------------------------------------------------------------------

class DBRequest(BaseModel):
    url: str
    tables: list[str] = []
    table: str | None = None
    sql: str | None = None
    joins: list[dict] = []
    base: str | None = None
    limit: int = 100_000
    name: str | None = None


def _db_error(e: Exception) -> HTTPException:
    msg = str(e).split("\n")[0]
    if "No module named" in msg:
        msg += " — install the database driver (see README: psycopg2-binary for PostgreSQL, pymysql for MySQL)."
    return HTTPException(400, msg)


@app.post("/api/db/connect")
def db_connect(req: DBRequest):
    try:
        return connector.describe_database(req.url)
    except Exception as e:
        raise _db_error(e)


@app.post("/api/db/joins")
def db_joins(req: DBRequest):
    try:
        db = connector.describe_database(req.url)
        return {"joins": connector.suggest_joins(db, req.tables)}
    except Exception as e:
        raise _db_error(e)


def _db_sql(req: DBRequest, db: dict | None = None) -> str:
    if req.sql:
        return req.sql.strip().rstrip(";")
    if req.joins and req.base:
        return connector.build_join_sql(db or connector.describe_database(req.url), req.base, req.joins)
    if req.table:
        return connector.table_sql(req.table, req.url)
    raise HTTPException(400, "Choose a table, a join or write a SELECT query.")


@app.post("/api/db/preview")
def db_preview(req: DBRequest):
    try:
        sql = _db_sql(req)
        df = connector.run_query(req.url, sql, 50)
        return {"sql": sql, "preview": _preview(df)}
    except HTTPException:
        raise
    except Exception as e:
        raise _db_error(e)


@app.post("/api/db/import")
def db_import(req: DBRequest):
    try:
        sql = _db_sql(req)
        df = connector.run_query(req.url, sql, req.limit)
    except HTTPException:
        raise
    except Exception as e:
        raise _db_error(e)
    if df.empty:
        raise HTTPException(400, "The query returned no rows.")
    name = req.name or (req.base and f"{req.base}_joined") or req.table or "query"
    meta = _save_dataset(to_storable(df), f"{name}.csv", "database",
                         {"sql": sql, "rows": len(df), "columns": df.shape[1], "dialect": connector.dialect_of(req.url)})
    return _dataset_payload(meta, DATASETS_DIR / meta["id"] / meta["file"])


# ---------------------------------------------------------------------------
# intake chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    dataset_id: str
    messages: list[dict] = []


@app.post("/api/chat/intake")
def chat_intake(req: ChatRequest):
    meta, path = _dataset(req.dataset_id)
    prof = json.loads((path.parent / "profile.json").read_text("utf-8"))
    return intake_reply(prof, req.messages, load_settings())


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    dataset_id: str
    messages: list[dict] = []
    intent: dict = {}


@app.get("/api/graph")
def graph():
    return graph_definition()


@app.post("/api/runs")
def start_run(req: RunRequest):
    meta, path = _dataset(req.dataset_id)
    run_id = manager.start(meta, path, req.messages, req.intent or {}, load_settings())
    return {"run_id": run_id}


@app.get("/api/runs")
def list_runs():
    return manager.list()


def _run_dir(run_id: str) -> Path:
    d = RUNS_DIR / re.sub(r"[^0-9A-Za-z-]", "", run_id)
    if not d.exists():
        raise HTTPException(404, "Run not found")
    return d


def _read(d: Path, name: str) -> Any:
    p = d / name
    return json.loads(p.read_text("utf-8")) if p.exists() else None


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    d = _run_dir(run_id)
    meta = read_meta(run_id) or {}
    prof = _read(d, "profile.json")
    return _json_safe({
        "meta": meta, "result": _read(d, "result.json"), "plan": _read(d, "plan.json"), "verdict": _read(d, "verdict.json"),
        "target_info": _read(d, "target_info.json"),
        "profile": None if not prof else {k: prof[k] for k in ("rows", "columns", "duplicate_rows", "missing_cells_pct", "type_counts")}
        | {"columns_detail": [{"name": c["name"], "type": c["semantic_type"], "missing_pct": c["missing_pct"], "unique": c["unique"],
                               "warnings": c["warnings"], "stats": c.get("stats"), "top_values": c.get("top_values", [])[:6]} for c in prof["column_profiles"]]},
    })


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    d = _run_dir(run_id)
    shutil.rmtree(d)
    return {"deleted": run_id}


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str):
    _run_dir(run_id)
    return bus.all(run_id)


@app.get("/api/runs/{run_id}/stream")
def run_stream(run_id: str, after: int = -1):
    _run_dir(run_id)

    def gen():
        last = after
        idle = 0
        while True:
            events = bus.since(run_id, last, timeout=10)
            if not events:
                idle += 1
                yield ": ping\n\n"
                status = (read_meta(run_id) or {}).get("status")
                if status in ("completed", "failed") and idle > 1:
                    return
                continue
            idle = 0
            for e in events:
                last = e["seq"]
                yield f"data: {json.dumps(e, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ResumeRequest(BaseModel):
    value: Any


@app.post("/api/runs/{run_id}/resume")
def resume_run(run_id: str, req: ResumeRequest):
    _run_dir(run_id)
    try:
        manager.resume(run_id, req.value)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@app.get("/api/runs/{run_id}/table")
def run_table(run_id: str, which: str = Query("cleaned", pattern="^(cleaned|train|test|raw)$"),
              offset: int = 0, limit: int = Query(100, le=1000)):
    d = _run_dir(run_id)
    path = d / "raw.parquet" if which == "raw" else d / "outputs" / f"{which}.csv"
    if not path.exists():
        raise HTTPException(404, "Not available yet")
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, low_memory=False)
    page = df.iloc[offset: offset + limit]
    return {"total": int(len(df)), "offset": offset, **_preview(page, limit)}


@app.get("/api/runs/{run_id}/files/{name}")
def run_file(run_id: str, name: str):
    d = _run_dir(run_id)
    if name == "datamind_outputs.zip":
        p = d / name
    else:
        p = d / "outputs" / Path(name).name
    if not p.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(p, filename=p.name)


# ---------------------------------------------------------------------------
# insights
# ---------------------------------------------------------------------------

@app.get("/api/runs/{run_id}/insights")
def run_insights(run_id: str):
    d = _run_dir(run_id)
    data = _read(d, "insights.json")
    if data is None:
        raise HTTPException(404, "Insights are not ready yet")
    return data


class InsightChat(BaseModel):
    message: str
    history: list[dict] = []


_cleaned_cache: dict[str, pd.DataFrame] = {}


@app.post("/api/runs/{run_id}/insights/chat")
def insight_chat(run_id: str, req: InsightChat):
    d = _run_dir(run_id)
    if not (d / "cleaned.parquet").exists():
        raise HTTPException(404, "Run the agent first")
    if run_id not in _cleaned_cache:
        _cleaned_cache[run_id] = pd.read_parquet(d / "cleaned.parquet")
    df = _cleaned_cache[run_id]
    plan = _read(d, "plan.json")
    settings = load_settings()
    llm = LLM(settings)
    llm_spec = None
    llm_reply = None
    if llm.enabled:
        roles = detect_roles(df, plan)
        share = llm.may_share_labels()
        schema = []
        for c in df.columns:
            item: dict[str, Any] = {"name": c, "dtype": str(df[c].dtype),
                                    "role": next((r for r in ("measure", "dimension", "time", "flag", "text") if c in roles[r]),
                                                 "target" if c == roles["target"] else "other")}
            if share and item["role"] == "dimension":
                item["labels"] = [str(v) for v in df[c].dropna().unique()[:12]]
            schema.append(item)
        convo = "\n".join(f"{m['role']}: {m['content']}" for m in req.history[-6:])
        data = llm.complete_json(prompts.QUERY_SYSTEM,
                                 f"COLUMNS: {json.dumps(schema)}\nTARGET: {roles['target']}\nRECENT CHAT:\n{convo}\nREQUEST: {req.message}", "insight_chat")
        if data and isinstance(data.get("spec"), dict):
            llm_spec, llm_reply = data["spec"], data.get("reply")
    res = answer(req.message, df, plan, llm=llm if llm.enabled else None, llm_spec=llm_spec)
    if llm_reply and res.get("source") == "llm" and res.get("chart") is not None:
        res["reply"] = f"{llm_reply}\n\n{res['reply']}"
    return _json_safe(res)


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

@app.get("/api/settings")
def get_settings():
    s = load_settings()
    return {"settings": public_settings(s), "ollama_models": ollama_models(s.llm.ollama_base_url)}


@app.put("/api/settings")
def put_settings(body: dict):
    try:
        s = merge_update(load_settings(), body)
    except Exception as e:
        raise HTTPException(400, f"Invalid settings: {e}")
    save_settings(s)
    return {"settings": public_settings(s)}


class TestRequest(BaseModel):
    provider: str


@app.post("/api/settings/test")
def settings_test(req: TestRequest):
    if req.provider not in ("ollama", "groq", "gemini"):
        raise HTTPException(400, "Unknown provider")
    return test_provider(load_settings(), req.provider)


@app.get("/api/ollama/models")
def get_ollama_models(base_url: str | None = None):
    return {"models": ollama_models(base_url or load_settings().llm.ollama_base_url)}


@app.get("/api/health")
def health():
    s = load_settings()
    return {"ok": True, "provider": s.llm.provider, "version": app.version}


# ---------------------------------------------------------------------------
# frontend (production build)
# ---------------------------------------------------------------------------

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        f = FRONTEND_DIST / full_path
        if full_path and f.is_file():
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")

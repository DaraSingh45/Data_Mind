"""The Data Mind agent as a LangGraph state machine.

    ingest → profile → understand ⇄ clarify → plan ⇄ validate → review → execute
          → checks → verify ─(revise)→ plan … ─(approve)→ export → insights

    execute / checks / export / insights ─(crash)→ repair ─(fixed plan)→ plan …

* Code does all work on data. The LLM (if configured) only proposes plan
  changes, verifies results and writes narrative.
* ``clarify`` and ``review`` pause the graph with ``interrupt()`` to ask the
  user; the run resumes when they answer in the UI.
"""
from __future__ import annotations

import json
import operator
import re
import time
import traceback
from typing import Annotated, Any, Callable, TypedDict

import pandas as pd
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..core.events import bus
from ..engine.checks import run_checks
from ..engine.executor import execute_plan
from ..engine.exporter import _ops, export_all
from ..engine.heuristic import build_heuristic_plan, heuristic_revision
from ..engine.ingest import read_any, to_storable
from ..engine.plan import apply_changes, apply_dataset_changes, validate_plan
from ..engine.profiler import guess_targets, infer_task, profile_dataframe, target_analysis
from ..engine.repair import diagnose, probe_columns, rule_fix
from ..insights.engine import generate_insights, template_narrative
from . import prompts
from .context import RunContext, get_ctx

NO_TARGET = "No target — just clean and explore"

STAGES = [
    {"id": "ingest", "label": "Ingest", "desc": "Load file, detect encoding & delimiter"},
    {"id": "profile", "label": "Profile", "desc": "Types, missing, outliers, variants"},
    {"id": "understand", "label": "Understand goal", "desc": "Target and task from your chat"},
    {"id": "clarify", "label": "Ask you", "desc": "Clarify the goal when unsure"},
    {"id": "plan", "label": "Plan", "desc": "Rules draft, LLM refines"},
    {"id": "validate", "label": "Validate plan", "desc": "Schema, whitelist, leakage rules"},
    {"id": "review", "label": "Your review", "desc": "Approve or override decisions"},
    {"id": "execute", "label": "Execute", "desc": "Split, fit on train only"},
    {"id": "checks", "label": "Quality checks", "desc": "Tests + baseline model"},
    {"id": "verify", "label": "Verify", "desc": "Approve or send back"},
    {"id": "export", "label": "Export", "desc": "CSV, pipeline, script, report"},
    {"id": "insights", "label": "Insights", "desc": "Scored findings + narrative"},
    {"id": "repair", "label": "Self-repair", "desc": "Diagnose the error, fix the plan, retry"},
]

# Stages whose crashes the agent tries to fix itself (Settings → Agent → Self-repair attempts).
REPAIRABLE = {"execute", "checks", "export", "insights"}


class AgentState(TypedDict, total=False):
    run_id: str
    messages: list[dict]
    intent: dict
    pending_question: dict | None
    plan: dict
    plan_errors: list[str]
    plan_attempts: int
    revise_loops: int
    feedback: list[str]
    pending_changes: list[dict]
    user_overrides: dict
    user_answers: dict
    keep_columns: list[str]
    review_done: bool
    replan_for_answers: bool
    checks: dict
    verdict: dict
    outputs: dict
    repair_retry: str
    decisions: Annotated[list[dict], operator.add]
    failure: dict | None          # the crash the repair stage should handle next
    repairs: list[dict]           # every repair attempt so far (shown in the UI)
    repair_changes: list[dict]    # plan changes made by self-repair, re-applied on every re-plan
    repair_dataset: dict          # dataset-level changes made by self-repair


# ---------------------------------------------------------------------------
# node wrapper: events + timing + error reporting
# ---------------------------------------------------------------------------

def stage(name: str) -> Callable:
    label = next(s["label"] for s in STAGES if s["id"] == name)

    def deco(fn: Callable[[AgentState, RunContext], tuple[dict, dict]]):
        def wrapper(state: AgentState) -> dict:
            run_id = state["run_id"]
            ctx = get_ctx(run_id)
            ctx.current_node = name
            bus.emit(run_id, "node_started", name, f"{label} started")
            started = time.time()
            try:
                updates, summary = fn(state, ctx)
            except GraphBubbleUp:  # interrupt() — the run pauses for the user
                raise
            except Exception as e:
                tb = traceback.format_exc()
                try:
                    cols = list(ctx.raw_df().columns)
                except Exception:  # noqa: BLE001 - ingest itself may have failed
                    cols = []
                info = diagnose(name, e, tb, cols)
                info.update(label=label, traceback=tb[-4000:])
                history = list(state.get("repairs") or [])
                limit = ctx.settings.agent.max_repair_attempts
                if name in REPAIRABLE and len(history) < limit:
                    bus.emit(run_id, "node_error", name, f"{label} failed: {info['reason']}",
                             {**info, "attempt": len(history) + 1, "limit": limit})
                    return {"failure": info}
                why = ("" if name in REPAIRABLE else " This stage can't be repaired automatically.") if limit else \
                    " Self-repair is off (Settings → Agent)."
                if name in REPAIRABLE and history and len(history) >= limit:
                    why = f" Gave up after {len(history)} repair attempt{'s' if len(history) != 1 else ''}."
                ctx.failure = {**info, "attempts": history, "limit": limit, "why_stopped": why.strip()}
                bus.emit(run_id, "node_failed", name, f"{label} failed: {info['reason']}", ctx.failure)
                raise
            secs = round(time.time() - started, 2)
            msg = summary.pop("message", f"{label} done")
            bus.emit(run_id, "node_completed", name, msg, {**summary, "seconds": secs})
            updates = dict(updates)
            updates["decisions"] = [{"stage": name, "message": msg, "ts": time.time()}]
            return updates
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# nodes
# ---------------------------------------------------------------------------

@stage("ingest")
def ingest(state: AgentState, ctx: RunContext):
    df, report = read_any(ctx.dataset_path)
    ctx.raw = df
    to_storable(df).to_parquet(ctx.run_dir / "raw.parquet", index=False)
    ctx.log(f"Read {report['rows']:,} rows × {report['columns']} columns from {report['file']}.")
    if report.get("encoding"):
        ctx.log(f"Detected encoding {report['encoding']} and delimiter '{report['delimiter']}'.")
    return {}, {"message": f"Loaded {report['rows']:,} rows × {report['columns']} columns", "report": report}


@stage("profile")
def profile(state: AgentState, ctx: RunContext):
    prof = profile_dataframe(ctx.raw_df())
    ctx.profile = prof
    ctx.save_json("profile.json", prof)
    warn = sum(len(c["warnings"]) for c in prof["column_profiles"])
    for c in prof["column_profiles"]:
        if c["warnings"]:
            ctx.log(f"{c['name']}: {', '.join(c['warnings'])}")
    types = ", ".join(f"{v} {k}" for k, v in prof["type_counts"].items())
    return {}, {"message": f"Profiled {prof['columns']} columns ({types}); {warn} issues found",
                "type_counts": prof["type_counts"], "duplicates": prof["duplicate_rows"], "issues": warn,
                "columns": [{"name": c["name"], "type": c["semantic_type"], "missing": c["missing_pct"], "warnings": c["warnings"]}
                            for c in prof["column_profiles"]]}


@stage("understand")
def understand(state: AgentState, ctx: RunContext):
    prof = ctx.profile_or_load()
    df = ctx.raw_df()
    cols = list(df.columns)
    intent = dict(state.get("intent") or {})
    if intent.get("target") not in cols:
        intent["target"] = None
    pending = None
    candidates = guess_targets(prof)

    if not intent.get("target_confirmed") and not intent.get("target") and intent.get("task") != "none":
        if ctx.llm.enabled and state.get("messages"):
            share = ctx.llm.may_share_labels()
            convo = "\n".join(f"{m['role']}: {m['content']}" for m in state["messages"][-8:])
            data = ctx.llm.complete_json(prompts.UNDERSTAND_SYSTEM,
                                         f"PROFILE:\n{prompts.dataset_brief(prof, share, ctx.settings.privacy.max_labels_per_column)}\n\n"
                                         f"CANDIDATE TARGETS: {candidates}\nCONVERSATION:\n{convo}", "understand")
            if data:
                if data.get("target") in cols:
                    intent["target"] = data["target"]
                    intent["task"] = data.get("task") if data.get("task") in ("classification", "regression") else None
                    ctx.log(f"LLM read the goal as: predict '{data['target']}' ({data.get('reason', '')})")
                elif data.get("task") == "none":
                    intent["task"] = "none"
                if data.get("goal"):
                    intent["goal"] = data["goal"]
        if not intent.get("target") and intent.get("task") != "none":
            mode = ctx.settings.agent.human_review
            if candidates and mode != "never":
                pending = {
                    "kind": "questions", "id": "target",
                    "title": "I need one detail before planning",
                    "questions": [{
                        "id": "target", "header": "Goal",
                        "question": "Which column should a model learn to predict?",
                        "options": [{"value": c, "label": f"Predict {c}", "description": _target_hint(prof, c)} for c in candidates]
                                   + [{"value": "__none__", "label": NO_TARGET, "description": "Prepare the data for analysis and dashboards only."}],
                        "allow_other": True,
                        "other_placeholder": "Describe your goal, e.g. 'predict monthly_charges'",
                    }],
                }
                ctx.log("Goal is ambiguous — asking you to choose the target.")
            elif candidates:
                intent["target"] = candidates[0]
                ctx.log(f"Auto-selected target '{candidates[0]}' (review mode is 'never').")

    target = intent.get("target")
    target_info = None
    if target and not pending:
        task = intent.get("task") if intent.get("task") in ("classification", "regression") else infer_task(df, target, prof)
        intent["task"] = task
        target_info = target_analysis(df, target, task, prof)
        ctx.target_info = target_info
        ctx.save_json("target_info.json", target_info)
        if task == "classification":
            ctx.log(f"Classes: {target_info.get('classes')} (imbalance {target_info.get('imbalance_ratio')}:1)")
        top = [f"{d['column']} ({d['score']:.2f})" for d in target_info["leakage"][:3]]
        ctx.log(f"Strongest single-column signals: {', '.join(top)}")
    elif not pending:
        intent["task"] = "none"
    msg = ("Waiting for you to choose the target" if pending else
           f"Goal: predict '{target}' ({intent['task']})" if target else "Goal: clean and explore (no target)")
    return {"intent": intent, "pending_question": pending}, {"message": msg, "intent": intent, "candidates": candidates}


def _target_hint(prof: dict, col: str) -> str:
    c = next(c for c in prof["column_profiles"] if c["name"] == col)
    if c.get("top_values"):
        return f"{c['semantic_type']}: " + ", ".join(f"{v['value']} ({v['count']})" for v in c["top_values"][:3])
    return f"{c['semantic_type']}, {c['unique']} distinct values"


@stage("clarify")
def clarify(state: AgentState, ctx: RunContext):
    q = state.get("pending_question")
    intent = dict(state.get("intent") or {})
    if not q:
        return {}, {"message": "Nothing to clarify"}
    answer = interrupt(q)
    if isinstance(answer, dict) and isinstance(answer.get("answers"), dict):
        value = answer["answers"].get("target")
        text = "" if value in [o["value"] for o in q["questions"][0]["options"]] else str(value or "")
    else:
        value = (answer or {}).get("answer") if isinstance(answer, dict) else answer
        text = (answer or {}).get("text", "") if isinstance(answer, dict) else ""
    cols = list(ctx.raw_df().columns)
    if value == "__none__" or value == NO_TARGET:
        intent.update(target=None, task="none")
    elif value in cols:
        intent.update(target=value, task=None)
    else:  # free text: try to find a column name in it
        from ..insights.query import _find_columns
        found = _find_columns(str(value or text), cols)
        intent.update(target=found[0] if found else None, task=None if found else "none")
    if text:
        intent["notes"] = (intent.get("notes", "") + " " + text).strip()
    intent["target_confirmed"] = True
    bus.emit(ctx.run_id, "input_received", "clarify", f"You chose: {intent.get('target') or NO_TARGET}")
    return {"intent": intent, "pending_question": None}, {"message": f"Target set to {intent.get('target') or 'none'}"}


@stage("plan")
def plan(state: AgentState, ctx: RunContext):
    prof = ctx.profile_or_load()
    intent = state.get("intent") or {}
    prep = ctx.settings.prep
    target_info = ctx.target_info_or_load()
    draft = build_heuristic_plan(prof, intent, target_info, prep)
    keep = set(state.get("keep_columns") or [])
    if keep:
        _keep_columns(draft, keep, prof, intent, prep)
    for col in intent.get("exclude_columns") or []:
        draft, _ = apply_changes(draft, [{"column": col, "field": "role", "value": "drop",
                                          "reason": "You asked to exclude this column."}], "user")
    overrides = state.get("user_overrides") or {}
    if overrides:
        changes = [{"column": c, "field": f, "value": v, "reason": "Set by you in review."} for c, fs in overrides.items() for f, v in fs.items()]
        draft, applied = apply_changes(draft, changes, "user")
        if applied:
            ctx.log("Kept your overrides: " + "; ".join(applied))
    repair_changes = state.get("repair_changes") or []
    if repair_changes:
        draft, applied = apply_changes(draft, repair_changes, "repair")
        applied += apply_dataset_changes(draft, state.get("repair_dataset") or {})
        ctx.log("Kept self-repair fixes: " + ("; ".join(applied) if applied else "already in place"))
    elif state.get("repair_dataset"):
        apply_dataset_changes(draft, state["repair_dataset"])
    pending = state.get("pending_changes") or []
    if pending:
        draft, applied = apply_changes(draft, pending, "verifier")
        ctx.log("Applied verifier revisions: " + "; ".join(applied))
    n_rules = len(draft["columns"])
    ctx.log(f"Rules engine drafted decisions for {n_rules} columns.")

    llm_summary = None
    if ctx.llm.enabled:
        share = ctx.llm.may_share_labels()
        compact = [{"column": c["column"], "role": c["role"], "kind": c.get("kind"), "type": c.get("semantic_type"),
                    "ops": _ops(c), "reason": c.get("reason", "")[:160]} for c in draft["columns"]]
        user = (f"GOAL: {json.dumps({k: intent.get(k) for k in ('target', 'task', 'goal', 'notes')})}\n"
                f"PROFILE:\n{prompts.dataset_brief(prof, share, ctx.settings.privacy.max_labels_per_column)}\n"
                f"TARGET ANALYSIS: {json.dumps({k: (target_info or {}).get(k) for k in ('classes', 'imbalance_ratio', 'leakage')}, default=str)[:3000]}\n"
                f"DRAFT PLAN: {json.dumps(compact)}\n"
                f"DATASET SETTINGS: {json.dumps({k: draft[k] for k in ('split', 'imbalance', 'drop_duplicates')})}")
        fb = list(state.get("plan_errors") or []) + list(state.get("feedback") or [])
        if fb:
            user += "\nFIX THESE PROBLEMS FROM THE LAST ATTEMPT:\n- " + "\n- ".join(fb)
        if state.get("user_answers"):
            user += f"\nTHE USER ANSWERED YOUR QUESTIONS: {json.dumps(state['user_answers'])}. Do not ask again."
        data = ctx.llm.complete_json(prompts.PLAN_SYSTEM, user, "plan")
        if data:
            protected = set(overrides) | keep | {c.get("column") for c in repair_changes}
            changes = [c for c in data.get("changes") or [] if c.get("column") not in protected and c.get("column") != draft.get("target")]
            draft, applied = apply_changes(draft, changes, "llm")
            applied += apply_dataset_changes(draft, {k: v for k, v in (data.get("dataset_changes") or {}).items() if k in ("imbalance", "split")})
            llm_summary = data.get("summary")
            ctx.log(f"LLM refined {len(applied)} decisions" + (f": {'; '.join(applied[:8])}" if applied else " (draft accepted as is)."))
            if not state.get("review_done"):
                for i, q in enumerate(data.get("questions") or []):
                    if isinstance(q, dict) and q.get("question") and q.get("options"):
                        draft["questions"].append({"id": f"llm{i}", "question": str(q["question"]), "options": [str(o) for o in q["options"]][:5],
                                                   "column": q.get("column"), "default": str(q["options"][0])})
            if llm_summary:
                draft["notes"].insert(0, llm_summary)
        else:
            ctx.log("LLM unavailable — using the rules-engine plan.")
    if state.get("review_done"):
        draft["questions"] = []
    ctx.save_json("plan.json", draft)
    kept = sum(c["role"] == "feature" for c in draft["columns"])
    dropped = sum(c["role"] == "drop" for c in draft["columns"])
    by_llm = sum(c.get("source") == "llm" for c in draft["columns"])
    return ({"plan": draft, "pending_changes": [], "feedback": []},
            {"message": f"Plan: keep {kept}, drop {dropped} columns" + (f", {by_llm} refined by LLM" if by_llm else ""),
             "columns": [{"column": c["column"], "role": c["role"], "ops": _ops(c), "reason": c.get("reason", ""), "source": c.get("source"),
                          "confidence": c.get("confidence")} for c in draft["columns"]],
             "questions": draft["questions"], "notes": draft["notes"], "llm_summary": llm_summary})


def _keep_columns(draft: dict, keep: set[str], prof: dict, intent: dict, prep) -> None:
    """Re-derive feature settings for columns the user chose to keep despite a leakage flag."""
    no_leak = build_heuristic_plan(prof, intent, None, prep)
    alt = {c["column"]: c for c in no_leak["columns"]}
    for i, c in enumerate(draft["columns"]):
        if c["column"] in keep and c["column"] in alt and alt[c["column"]]["role"] == "feature":
            draft["columns"][i] = {**alt[c["column"]], "source": "user", "reason": "Kept by you: available at prediction time. " + alt[c["column"]]["reason"]}
    draft["questions"] = [q for q in draft["questions"] if q.get("column") not in keep]


@stage("validate")
def validate(state: AgentState, ctx: RunContext):
    prof = ctx.profile_or_load()
    sem = {c["name"]: c["semantic_type"] for c in prof["column_profiles"]}
    cols = list(ctx.raw_df().columns)
    _, errors = validate_plan(state["plan"], cols, sem)
    attempts = int(state.get("plan_attempts") or 0)
    if not errors:
        return {"plan_errors": [], "plan_attempts": 0}, {"message": "Plan is valid: every operation is allowed and consistent", "errors": []}
    attempts += 1
    for e in errors:
        ctx.log(f"Rejected: {e}")
    if attempts <= ctx.settings.agent.max_plan_retries and ctx.llm.enabled:
        return ({"plan_errors": errors, "plan_attempts": attempts},
                {"message": f"Plan rejected ({len(errors)} problems) — sending back to the planner", "errors": errors})
    # Out of retries: fall back to the rules-engine plan, which is always valid.
    fallback = build_heuristic_plan(prof, state.get("intent") or {}, ctx.target_info_or_load(), ctx.settings.prep)
    _, errors2 = validate_plan(fallback, cols, sem)
    if errors2:
        raise RuntimeError(f"rules-engine plan invalid: {errors2}")
    ctx.save_json("plan.json", fallback)
    ctx.log("Falling back to the rules-engine plan after repeated invalid proposals.")
    return ({"plan": fallback, "plan_errors": [], "plan_attempts": 0},
            {"message": "Invalid proposals discarded — using the rules-engine plan", "errors": errors})


@stage("review")
def review(state: AgentState, ctx: RunContext):
    plan_d = state["plan"]
    mode = ctx.settings.agent.human_review
    questions = plan_d.get("questions") or []
    low = [c for c in plan_d["columns"] if c.get("role") != "target" and (c.get("confidence") or 1) < 0.7]
    first_time = not state.get("review_done")
    ask_cards = mode == "on_uncertainty" and bool(questions) and first_time
    show_plan = mode == "always" and first_time
    need = ask_cards or show_plan
    answers: dict = {}
    overrides: dict = {}
    if ask_cards:
        payload = {
            "kind": "questions", "id": "plan_questions",
            "title": "A few things I'm not sure about" if len(questions) > 1 else "One thing I'm not sure about",
            "questions": [_card(q) for q in questions],
        }
        reply = interrupt(payload) or {}
        answers = reply.get("answers") or {}
        bus.emit(ctx.run_id, "input_received", "review", f"You answered {len(answers)} question(s)")
    elif show_plan:
        payload = {
            "kind": "review", "id": "plan_review",
            "title": "Review the preparation plan",
            "question": (f"I have {len(questions)} question(s) and {len(low)} low-confidence decision(s). "
                         "Approve the plan, answer the questions or override any column." if (questions or low) else
                         "Here is the plan. Approve it or override any column before I run it."),
            "plan": {"target": plan_d.get("target"), "task": plan_d.get("task"), "split": plan_d.get("split"),
                     "imbalance": plan_d.get("imbalance"), "notes": plan_d.get("notes"),
                     "columns": [{k: c.get(k) for k in ("column", "role", "kind", "semantic_type", "impute", "outliers", "encode",
                                                         "scale", "reason", "source", "confidence")} | {"ops": _ops(c)}
                                 for c in plan_d["columns"]]},
            "questions": questions,
            "low_confidence": [c["column"] for c in low],
        }
        reply = interrupt(payload) or {}
        answers = reply.get("answers") or {}
        overrides = reply.get("overrides") or {}
        bus.emit(ctx.run_id, "input_received", "review",
                 f"Plan approved with {len(answers)} answer(s) and {sum(len(v) for v in overrides.values())} override(s)")
    else:
        for q in questions:
            if q.get("default"):
                answers[q["id"]] = q["default"]
        if questions:
            ctx.log(f"Auto-applied {len(questions)} default answer(s) (review mode: {mode}).")

    keep = set(state.get("keep_columns") or [])
    llm_answers = {}
    for q in questions:
        a = str(answers.get(q["id"], q.get("default")) or "")
        if q["id"].startswith("leak:") and _means_keep(a):
            keep.add(q["column"])
        elif q["id"].startswith("llm") and a:
            llm_answers[q["question"]] = a
        if a and a not in (q.get("options") or []):
            ctx.log(f"Your note on '{q.get('column') or q['id']}': {a}")
    user_overrides = dict(state.get("user_overrides") or {})
    for col, fields in overrides.items():
        user_overrides.setdefault(col, {}).update(fields)

    updates: dict[str, Any] = {"review_done": True, "user_overrides": user_overrides, "keep_columns": sorted(keep),
                               "user_answers": {**(state.get("user_answers") or {}), **llm_answers}}
    # Anything that changes the plan goes back through plan → validate.
    if keep - set(state.get("keep_columns") or []) or overrides or llm_answers:
        updates["replan_for_answers"] = True
        return updates, {"message": "Applying your answers — re-planning", "answers": answers, "overrides": overrides}
    updates["replan_for_answers"] = False
    return updates, {"message": "Plan approved" + (" by you" if need else " automatically (no open questions)"),
                     "answers": answers}


def _card(q: dict) -> dict:
    """A plan question as a question card: options with short descriptions plus 'Other'."""
    if q["id"].startswith("leak:"):
        col = q["column"]
        return {"id": q["id"], "header": col, "question": q["question"], "allow_other": True,
                "other_placeholder": "Tell me how this column is collected…",
                "options": [{"value": q["options"][0], "label": "Drop it",
                             "description": "It's recorded after the outcome, so using it would leak the answer."},
                            {"value": q["options"][1], "label": "Keep it",
                             "description": "It's known at prediction time, so the model can use it."}]}
    return {"id": q["id"], "header": q.get("column") or "Plan", "question": q["question"], "allow_other": True,
            "options": [{"value": o, "label": o, "description": ""} for o in q.get("options") or []]}


def _means_keep(answer: str) -> bool:
    a = answer.lower()
    if a.startswith("keep"):
        return True
    if a.startswith("drop"):
        return False
    # free-text answer: keep only if it clearly says the value is available before the outcome
    return bool(re.search(r"\b(keep|before|available|known at|at prediction|upfront)\b", a)) and not re.search(r"\b(after|drop|remove|leak)\b", a)


@stage("execute")
def execute(state: AgentState, ctx: RunContext):
    res = execute_plan(ctx.raw_df(), state["plan"])
    ctx.result = res
    for line in res["log"]:
        ctx.log(line)
    st = res["stats"]
    return {}, {"message": f"{st['columns_in']} columns → {st['features_out']} features; {st['train_rows']:,} train / {st['test_rows']:,} test rows",
                "stats": st}


@stage("checks")
def checks(state: AgentState, ctx: RunContext):
    a = ctx.settings.agent
    baseline = a.run_baseline_model and not ctx.flags.get("skip_baseline")
    if a.run_baseline_model and not baseline:
        ctx.log("Baseline model skipped by self-repair.")
    ck = run_checks(ctx.raw_df(), state["plan"], ctx.result, baseline, a.baseline_max_rows)
    for c in ck["checks"]:
        ctx.log(f"[{c['status'].upper()}] {c['name']} — {c['detail']}")
    s = ck["summary"]
    return {"checks": ck}, {"message": f"{s['passed']}/{s['total']} checks passed, {s['warnings']} warnings, {s['failed']} failed",
                            "summary": s, "checks": ck["checks"], "baseline": ck.get("baseline")}


@stage("verify")
def verify(state: AgentState, ctx: RunContext):
    ck = state["checks"]
    loops = int(state.get("revise_loops") or 0)
    changes, feedback = heuristic_revision(state["plan"], ck)
    failed = [c for c in ck["checks"] if c["status"] == "fail"]
    summary = ("All checks passed." if not failed and not changes else
               f"{len(failed)} failed check(s); {len(changes)} fix(es) proposed.")
    base = ck.get("baseline") or {}
    if base.get("delta") is not None:
        summary += f" Prepared data scores {base['prepared_test']:.3f} {base['metric']} vs {base['naive_test']:.3f} for a naive baseline."
    concerns: list[str] = list(feedback)
    source = "rules"
    if ctx.llm.enabled:
        user = json.dumps({"checks": ck["checks"], "baseline": base, "comparisons": ck.get("comparisons", [])[:12],
                           "plan": [{"column": c["column"], "role": c["role"], "ops": _ops(c)} for c in state["plan"]["columns"]],
                           "stats": ctx.result["stats"]}, default=str)
        data = ctx.llm.complete_json(prompts.VERIFY_SYSTEM, user, "verify")
        if data:
            source = "llm"
            summary = data.get("summary") or summary
            concerns += [str(c) for c in data.get("concerns") or []][:6]
            if data.get("verdict") == "revise":
                changes += [c for c in data.get("changes") or [] if isinstance(c, dict)]
    can_loop = loops < ctx.settings.agent.max_revise_loops
    verdict = "revise" if changes and can_loop else "approve"
    if changes and not can_loop:
        concerns.append("Revision limit reached — exporting the best result so far.")
    v = {"verdict": verdict, "summary": summary, "concerns": concerns, "source": source, "loop": loops}
    ctx.save_json("verdict.json", v)
    for c in concerns:
        ctx.log(f"Concern: {c}")
    upd: dict[str, Any] = {"verdict": v}
    if verdict == "revise":
        upd.update(pending_changes=changes, revise_loops=loops + 1, feedback=feedback or concerns, review_done=True)
        return upd, {"message": f"Sending back to the planner with {len(changes)} change(s)", "verdict": v}
    return upd, {"message": "Verified — output approved", "verdict": v}


@stage("export")
def export(state: AgentState, ctx: RunContext):
    res = ctx.result
    ctx.save_parquet("cleaned.parquet", res["cleaned"])
    out = export_all(ctx.run_dir, ctx.dataset_name, state["plan"], res, state["checks"], ctx.profile_or_load(),
                     state.get("decisions") or [], state.get("verdict"))
    summary = {
        "stats": res["stats"], "feature_names": res["feature_names"], "checks": state["checks"],
        "verdict": state.get("verdict"), "plan": state["plan"], "intent": state.get("intent"), "files": out["files"],
        "llm_calls": ctx.llm.calls, "repairs": state.get("repairs") or [],
    }
    ctx.save_json("result.json", summary)
    ctx.log(f"Wrote {len(out['files'])} files: " + ", ".join(f["name"] for f in out["files"]))
    return {"outputs": out}, {"message": f"Exported {len(out['files'])} files", "files": out["files"]}


@stage("insights")
def insights(state: AgentState, ctx: RunContext):
    cleaned = ctx.load_parquet("cleaned.parquet")
    s = ctx.settings.insights
    safe = bool(ctx.flags.get("insights_safe"))
    res = generate_insights(cleaned, state["plan"], ctx.profile_or_load(), s.max_insights, s.significance_level, safe=safe)
    for sk in res.get("skipped") or []:
        ctx.log(f"Skipped an analysis that failed: {sk}")
    narrative = None
    if s.narrative and ctx.llm.enabled and res["insights"]:
        brief = [{"title": i["title"], "text": i["text"], "stats": i.get("stats")} for i in res["insights"]]
        narrative = ctx.llm.complete_json(prompts.NARRATIVE_SYSTEM, json.dumps({"kpis": res["kpis"], "insights": brief}, default=str), "narrative")
        if narrative:
            narrative["source"] = "llm"
    res["narrative"] = narrative or template_narrative(res)
    ctx.save_json("insights.json", res)
    ctx.log(f"Considered {res['candidates_considered']} candidate insights; kept the top {len(res['insights'])}.")
    return {}, {"message": f"{len(res['insights'])} insights ready", "headline": res["narrative"].get("headline")}


@stage("repair")
def repair(state: AgentState, ctx: RunContext):
    failure = dict(state.get("failure") or {})
    history = list(state.get("repairs") or [])
    attempt = len(history) + 1
    limit = ctx.settings.agent.max_repair_attempts
    stage_label = failure.get("label", failure.get("stage"))
    ctx.log(f"Attempt {attempt} of {limit}: {stage_label} failed — {failure.get('reason')}")
    ctx.log(f"Error: {failure.get('error_type')}: {failure.get('error', '')[:300]}")
    plan_d = state.get("plan") or {}

    # 1) find the culprit columns by running the failing step one column at a time
    culprits: dict[str, str] = {}
    if failure.get("stage") in ("execute", "checks") and plan_d:
        a = ctx.settings.agent

        def run_step(df: pd.DataFrame, p: dict):
            r = execute_plan(df, p)
            if failure["stage"] == "checks":
                run_checks(df, p, r, a.run_baseline_model and not ctx.flags.get("skip_baseline"), 2000)

        ctx.log("Testing each column on its own to find the one that breaks…")
        culprits = probe_columns(ctx.raw_df(), plan_d, run_step)
        if culprits:
            for c, err in culprits.items():
                ctx.log(f"Culprit: '{c}' → {err}")
        else:
            ctx.log("No single column is to blame (the step fails even without them, or most fail alike) — fixing the plan as a whole.")

    # 2) rules-engine fix
    fix = rule_fix(failure, plan_d, history, culprits)
    changes, dataset, notes, source = list(fix["changes"]), dict(fix["dataset"]), list(fix["notes"]), "rules"
    diagnosis = failure.get("reason")

    # 3) ask the LLM for a fix (if configured) and merge it in
    if ctx.llm.enabled and failure.get("stage") in ("execute", "checks"):
        user = json.dumps({
            "stage": failure.get("stage"), "error": f"{failure.get('error_type')}: {failure.get('error')}",
            "traceback_tail": (failure.get("traceback") or "")[-1500:], "culprit_columns": culprits,
            "plan": [{"column": c["column"], "role": c["role"], "kind": c.get("kind"), "ops": _ops(c)} for c in plan_d.get("columns", [])],
            "dataset": {k: plan_d.get(k) for k in ("target", "task", "split", "imbalance")},
            "earlier_attempts": [{"stage": h["stage"], "reason": h["reason"], "fixes": h["fixes"]} for h in history],
        }, default=str)
        data = ctx.llm.complete_json(prompts.REPAIR_SYSTEM, user, "repair")
        if data:
            source = "llm+rules"
            diagnosis = str(data.get("diagnosis") or diagnosis)
            llm_changes = [c for c in data.get("changes") or [] if isinstance(c, dict) and c.get("column") != plan_d.get("target")]
            changes = llm_changes + [c for c in changes if (c["column"], c["field"]) not in {(x.get("column"), x.get("field")) for x in llm_changes}]
            if isinstance(data.get("dataset_changes"), dict):
                dataset.update({k: v for k, v in data["dataset_changes"].items() if k in ("imbalance", "split")})
            notes.insert(0, f"LLM: {diagnosis}")

    # 4) check the fix is allowed before trying it
    test_plan = json.loads(json.dumps(plan_d)) if plan_d else None
    applied: list[str] = []
    if test_plan:
        test_plan, applied = apply_changes(test_plan, changes, "repair")
        applied += apply_dataset_changes(test_plan, dataset)
    ctx.flags.update(fix["flags"])
    if fix["flags"].get("wait"):
        time.sleep(float(fix["flags"]["wait"]))
    for n in notes:
        ctx.log(n)
    if applied:
        ctx.log("Plan changes: " + "; ".join(applied[:12]) + (" …" if len(applied) > 12 else ""))

    record = {"attempt": attempt, "limit": limit, "stage": failure.get("stage"), "label": stage_label,
              "error_type": failure.get("error_type"), "error": failure.get("error"), "reason": failure.get("reason"),
              "hint": failure.get("hint"), "diagnosis": diagnosis, "culprits": list(culprits), "fixes": notes,
              "changes": applied, "source": source, "safe_columns": fix["safe_columns"], "ts": time.time()}
    history.append(record)
    retry = "insights" if failure.get("stage") == "insights" else "plan"
    upd: dict[str, Any] = {"failure": None, "repairs": history, "repair_retry": retry,
                           "repair_changes": list(state.get("repair_changes") or []) + changes,
                           "repair_dataset": {**(state.get("repair_dataset") or {}), **dataset},
                           "review_done": True, "revise_loops": 0}
    what = "re-running insights" if retry == "insights" else "re-planning and trying again"
    return upd, {"message": f"Fix {attempt}/{limit} for {stage_label}: {notes[0] if notes else 'retrying'} — {what}",
                 "repair": record}


# ---------------------------------------------------------------------------
# routing + graph
# ---------------------------------------------------------------------------

def after_understand(state: AgentState) -> str:
    return "clarify" if state.get("pending_question") else "plan"


def after_validate(state: AgentState) -> str:
    return "plan" if state.get("plan_errors") else "review"


def after_review(state: AgentState) -> str:
    return "plan" if state.get("replan_for_answers") else "execute"


def after_verify(state: AgentState) -> str:
    return "plan" if (state.get("verdict") or {}).get("verdict") == "revise" else "export"


def _or_repair(nxt: str) -> Callable[[AgentState], str]:
    def route(state: AgentState) -> str:
        return "repair" if state.get("failure") else nxt
    return route


def after_repair(state: AgentState) -> str:
    return state.get("repair_retry") or "plan"


def build_graph():
    g = StateGraph(AgentState)
    for name, fn in [("ingest", ingest), ("profile", profile), ("understand", understand), ("clarify", clarify),
                     ("plan", plan), ("validate", validate), ("review", review), ("execute", execute),
                     ("checks", checks), ("verify", verify), ("export", export), ("insights", insights), ("repair", repair)]:
        g.add_node(name, fn)
    g.add_edge(START, "ingest")
    g.add_edge("ingest", "profile")
    g.add_edge("profile", "understand")
    g.add_conditional_edges("understand", after_understand, {"clarify": "clarify", "plan": "plan"})
    g.add_edge("clarify", "understand")
    g.add_edge("plan", "validate")
    g.add_conditional_edges("validate", after_validate, {"plan": "plan", "review": "review"})
    g.add_conditional_edges("review", after_review, {"plan": "plan", "execute": "execute"})
    g.add_conditional_edges("execute", _or_repair("checks"), {"checks": "checks", "repair": "repair"})
    g.add_conditional_edges("checks", _or_repair("verify"), {"verify": "verify", "repair": "repair"})
    g.add_conditional_edges("verify", after_verify, {"plan": "plan", "export": "export"})
    g.add_conditional_edges("export", _or_repair("insights"), {"insights": "insights", "repair": "repair"})
    g.add_conditional_edges("insights", _or_repair(END), {END: END, "repair": "repair"})
    g.add_conditional_edges("repair", after_repair, {"plan": "plan", "insights": "insights"})
    return g.compile(checkpointer=InMemorySaver())


GRAPH = build_graph()

EDGES = [
    {"from": "ingest", "to": "profile"}, {"from": "profile", "to": "understand"},
    {"from": "understand", "to": "clarify", "kind": "conditional", "label": "unsure"},
    {"from": "clarify", "to": "understand", "kind": "loop"},
    {"from": "understand", "to": "plan"}, {"from": "plan", "to": "validate"},
    {"from": "validate", "to": "plan", "kind": "loop", "label": "invalid"},
    {"from": "validate", "to": "review"},
    {"from": "review", "to": "plan", "kind": "loop", "label": "answers"},
    {"from": "review", "to": "execute"}, {"from": "execute", "to": "checks"}, {"from": "checks", "to": "verify"},
    {"from": "verify", "to": "plan", "kind": "loop", "label": "revise"},
    {"from": "verify", "to": "export"}, {"from": "export", "to": "insights"},
    {"from": "execute", "to": "repair", "kind": "conditional", "label": "error"},
    {"from": "checks", "to": "repair", "kind": "conditional", "label": "error"},
    {"from": "export", "to": "repair", "kind": "conditional", "label": "error"},
    {"from": "insights", "to": "repair", "kind": "conditional", "label": "error"},
    {"from": "repair", "to": "plan", "kind": "loop", "label": "retry with fix"},
    {"from": "repair", "to": "insights", "kind": "loop", "label": "retry"},
]


def graph_definition() -> dict:
    return {"stages": STAGES, "edges": EDGES}


def to_df(x: Any) -> pd.DataFrame:  # pragma: no cover - helper for typing
    return x

"""Start-page chat: understand the dataset and what the user wants before a run."""
from __future__ import annotations

import json
import re

from ..core.settings import Settings
from ..engine.profiler import guess_targets
from ..insights.query import _find_columns
from . import prompts
from .llm import LLM

CLEAN_ONLY = re.compile(r"\b(just|only)\s+(clean|explore|prepare)|no target|explore|eda|dashboard|insight|clean (it|the data)\b", re.I)
PREDICT = re.compile(r"\b(predict|forecast|classif|regress|target|model|estimate|churn|default|fraud)\w*", re.I)
EXCLUDE = re.compile(r"\b(?:ignore|exclude|drop|remove|don'?t use)\s+(?:the\s+)?(?:column\s+)?([\w ,]+)", re.I)


def describe(profile: dict) -> str:
    issues = []
    cols = profile["column_profiles"]
    if profile["duplicate_rows"]:
        issues.append(f"{profile['duplicate_rows']} duplicate rows")
    text_nums = [c["name"] for c in cols if "numbers stored as text" in c["warnings"]]
    if text_nums:
        issues.append(f"numbers stored as text in {', '.join(text_nums[:3])}")
    variants = [c["name"] for c in cols if c.get("variants")]
    if variants:
        issues.append(f"inconsistent labels in {', '.join(variants[:3])}")
    missing = sorted([c for c in cols if c["missing_pct"] > 0], key=lambda c: -c["missing_pct"])
    if missing:
        issues.append(f"missing values (worst: {missing[0]['name']} {missing[0]['missing_pct']:.0%})")
    ids = [c["name"] for c in cols if c["semantic_type"] in ("id", "email", "phone", "url")]
    if ids:
        issues.append(f"identifier columns ({', '.join(ids[:3])})")
    outl = [c["name"] for c in cols if any("outliers" in w for w in c["warnings"])]
    if outl:
        issues.append(f"outliers in {', '.join(outl[:3])}")
    return "; ".join(issues)


RUN_NOW = re.compile(r"\b(run|start|go( ahead)?|do it|begin|proceed|let'?s go|prepare|clean it|execute)\b", re.I)


def _task_for(profile: dict, target: str) -> str:
    c = next((c for c in profile["column_profiles"] if c["name"] == target), None)
    if not c:
        return "classification"
    if c["semantic_type"] in ("boolean", "categorical"):
        return "classification"
    st = c.get("stats") or {}
    return "classification" if st.get("is_integer") and c["unique"] <= 10 else "regression"


def _type_summary(profile: dict) -> str:
    return ", ".join(f"{v} {k}" for k, v in sorted(profile["type_counts"].items(), key=lambda kv: -kv[1]))


def heuristic_reply(profile: dict, messages: list[dict]) -> dict:
    """Rule-based understanding of the user's request. Returns the reply, the
    extracted intent, the concrete steps that were performed (shown in the UI)
    and the action the agent takes next."""
    cols = [c["name"] for c in profile["column_profiles"]]
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    last = user_msgs[-1] if user_msgs else ""
    all_user = " ".join(user_msgs)
    intent: dict = {"target": None, "task": None, "goal": None, "exclude_columns": [], "notes": all_user[-500:]}
    candidates = guess_targets(profile)
    steps: list[dict] = []
    rows, ncols = profile["rows"], profile["columns"]
    n_issues = sum(len(c["warnings"]) for c in profile["column_profiles"]) + (1 if profile["duplicate_rows"] else 0)

    if not user_msgs:
        steps = [
            {"label": "Loaded the dataset", "detail": f"{rows:,} rows × {ncols} columns"},
            {"label": "Profiled every column", "detail": _type_summary(profile)},
            {"label": "Scanned for problems", "detail": f"{n_issues} found" + (f" — {describe(profile)}" if n_issues else "")},
            {"label": "Looked for an outcome column", "detail": f"'{candidates[0]}' looks like one" if candidates else "none obvious"},
        ]
        reply = ("Tell me what you want to do with this data — for example "
                 + (f"*predict {candidates[0]}*" if candidates else "*predict a column*")
                 + " or *just clean it and show insights*. If you'd rather not explain, press **Run** and I'll ask only what I need.")
        return {"reply": reply, "intent": intent, "ready": False, "action": "wait", "steps": steps,
                "source": "rules", "candidates": candidates}

    steps.append({"label": "Read your request", "detail": f"“{last[:90]}”"})
    mentioned = _find_columns(all_user, cols)
    for m in EXCLUDE.finditer(all_user):
        intent["exclude_columns"] += [c for c in _find_columns(m.group(1), cols)]
    targets = [c for c in mentioned if c not in intent["exclude_columns"]]
    steps.append({"label": "Matched it to your columns", "detail": ", ".join(mentioned) if mentioned else "no column names mentioned"})
    if CLEAN_ONLY.search(last) and not PREDICT.search(last):
        intent.update(task="none", goal="Clean the data and explore insights")
    elif targets and PREDICT.search(all_user):
        intent.update(target=targets[0], goal=f"Predict {targets[0]}")
    elif targets and len(targets) == 1 and re.search(r"\b(target|label|outcome)\b", all_user, re.I):
        intent.update(target=targets[0], goal=f"Predict {targets[0]}")
    if intent["target"]:
        intent["task"] = _task_for(profile, intent["target"])
        steps.append({"label": "Set the goal", "detail": f"predict '{intent['target']}' ({intent['task']})"})
    elif intent["task"] == "none":
        steps.append({"label": "Set the goal", "detail": "clean and explore — no prediction target"})
    else:
        steps.append({"label": "Set the goal", "detail": "still unclear"})
    if intent["exclude_columns"]:
        steps.append({"label": "Noted columns to leave out", "detail": ", ".join(intent["exclude_columns"])})

    ready = bool(intent["target"] or intent["task"] == "none")
    wants_run = bool(RUN_NOW.search(last))
    if ready:
        what = f"prepare the data to predict **{intent['target']}**" if intent["target"] else "clean the data and build an insights dashboard"
        reply = (f"Understood — I'll {what}"
                 + (f", leaving out {', '.join(intent['exclude_columns'])}" if intent["exclude_columns"] else "")
                 + f". There are {n_issues} problems to fix. Starting the run now; I'll stop and ask you if anything is unclear.")
        action = "run"
    elif wants_run:
        reply = "Starting now. I'm not sure what you want to predict yet, so I'll ask you during the run."
        action = "run"
    else:
        hint = f" For example: *predict {candidates[0]}*." if candidates else ""
        reply = "I couldn't tell the goal from that. Which column should I predict, or should I *just clean and explore*?" + hint
        action = "wait"
    return {"reply": reply, "intent": intent, "ready": ready, "action": action, "steps": steps,
            "source": "rules", "candidates": candidates}


def intake_reply(profile: dict, messages: list[dict], settings: Settings) -> dict:
    base = heuristic_reply(profile, messages)
    llm = LLM(settings)
    if not llm.enabled or not any(m["role"] == "user" for m in messages):
        return base
    share = llm.may_share_labels()
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in messages[-10:])
    data = llm.complete_json(prompts.INTAKE_SYSTEM,
                             f"PROFILE:\n{prompts.dataset_brief(profile, share, settings.privacy.max_labels_per_column)}\n\n"
                             f"CANDIDATE TARGETS: {base['candidates']}\nCONVERSATION:\n{convo}", "intake")
    call = llm.calls[-1] if llm.calls else {}
    llm_step = {"label": f"Asked {call.get('provider', 'the model')} · {call.get('model', '')}",
                "detail": f"{call.get('seconds', '?')} s" + ("" if call.get("ok") else f" — failed: {str(call.get('error', ''))[:80]}; used the rules engine")}
    if not data or not data.get("reply"):
        base["steps"].insert(1, llm_step)
        base["llm_error"] = call.get("error")
        return base
    cols = {c["name"] for c in profile["column_profiles"]}
    intent = data.get("intent") or {}
    clean = {
        "target": intent.get("target") if intent.get("target") in cols else None,
        "task": intent.get("task") if intent.get("task") in ("classification", "regression", "none") else None,
        "goal": intent.get("goal"),
        "exclude_columns": [c for c in intent.get("exclude_columns") or [] if c in cols],
        "notes": intent.get("notes") or base["intent"].get("notes"),
    }
    if clean["task"] != "none" and not clean["target"]:
        clean["task"] = None
    if clean["target"] and not clean["task"]:
        clean["task"] = _task_for(profile, clean["target"])
    ready = bool(clean["target"]) or clean["task"] == "none"
    steps = [base["steps"][0], llm_step,
             {"label": "Set the goal", "detail": (f"predict '{clean['target']}' ({clean['task']})" if clean["target"]
                                                  else "clean and explore" if clean["task"] == "none" else "still unclear")}]
    if clean["exclude_columns"]:
        steps.append({"label": "Noted columns to leave out", "detail": ", ".join(clean["exclude_columns"])})
    action = "run" if ready or base["action"] == "run" else "wait"
    return {"reply": str(data["reply"]), "intent": clean, "ready": ready, "action": action, "steps": steps,
            "source": "llm", "candidates": base["candidates"], "llm": json.loads(json.dumps(call, default=str))}

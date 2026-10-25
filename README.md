# Data Mind

**An AI agent that turns raw data into model-ready data — and shows you what the data says.**

Load a messy CSV, Excel file or database table, tell Data Mind what you want in plain English, and watch a LangGraph agent profile the data, plan every fix, validate the plan, ask you when it is unsure, execute it without test-set leakage, verify the result against a baseline model, export a reproducible pipeline, and build an insights dashboard you can chat with.

It runs entirely on your laptop. The LLM (local Ollama, or Groq / Gemini) only *plans and verifies* from column statistics. It never sees your rows and never runs code; deterministic tools do all the work.

![Simulation canvas](docs/screenshots/agent.png)

The run plays out on a **simulation canvas**: a 2D world of connected blocks you can zoom (scroll), pan (drag) and rearrange (drag a block). The active block glows and a pulse travels along the edge it came from; the camera follows the agent, there is a minimap, full-screen mode, and any finished run can be replayed at 0.5×–4×.

---

## What it does

| Stage | What happens |
|---|---|
| **Ingest** | Reads CSV/TSV/Excel/Parquet/JSON or imports from PostgreSQL, MySQL, SQLite (any SQLAlchemy database). Detects encoding, delimiter and messy headers. |
| **Profile** | Semantic types (ID, email, currency-as-text, percentages, dates in mixed formats, booleans, free text), missing values, outliers, skew, spelling variants (`M` / `male` / `MALE` → `Male`), duplicates, correlations. |
| **Understand goal** | Reads your chat to decide the target and task. Detects target leakage: columns that predict the answer because they are recorded *after* it. |
| **Ask you** | Only when something is genuinely unclear (no clear target, a column that may leak the answer), the run pauses and shows a question card: numbered options with a short explanation each, plus **Other** to answer in your own words. |
| **Plan** | A rules engine drafts a decision for every column with a reason and a confidence score. If an LLM is configured, it refines the draft with semantic understanding. |
| **Validate** | Every proposal is checked against a strict whitelist schema (Pydantic). Invalid plans are sent back to the planner with the errors. |
| **Your review** | Your answers are applied and the plan is rebuilt. Set *Always review* in Settings to approve or override every column before it runs. |
| **Execute** | Splits first (stratified / random / time-based), then fits imputation, outlier bounds, encoders and scalers on the **training split only**. |
| **Quality checks** | No missing values, all numeric, no constant features, rows reconcile, single-feature leakage scan, and a **baseline model** comparing raw vs. prepared data. |
| **Verify** | Rules + LLM decide to approve or send the plan back with fixes. |
| **Export** | `train.csv`, `test.csv`, `cleaned.csv`, a fitted `pipeline.joblib`, a standalone `reproduce.py`, `plan.json` and an HTML report. |
| **Insights** | A schema-agnostic insight engine tests dozens of patterns (drivers of the target, trends with anomaly detection, segment differences, distributions, Pareto concentration, correlations), scores them by effect size and significance, and shows the best as an interactive dashboard. |

### Self-repair when something breaks

If the Execute, Quality checks, Export or Insights stage crashes, the run doesn't just stop:

1. The block turns red and a strip above the canvas explains the failure in plain language ("A column still had text where a number was expected (value: '1497 CC')").
2. The **Self-repair** block runs the failing step on one column at a time to find the culprit (and does a control run with no columns, so a global problem isn't blamed on a column).
3. It changes the plan: the safest treatment for the culprit column, then dropping it if it fails again; if no column is to blame, a more conservative plan (random split, simpler encodings, no outlier step) and then a safe mode. With an LLM connected, the error, traceback and earlier attempts are sent to the model too, and its whitelisted fix is merged in.
4. The run goes back through plan → validate → execute with the fix, up to **Settings → Agent behaviour → Self-repair attempts** (0–5, default 2; 0 turns it off).

A run that recovered shows **Self-repaired after N attempts** with each attempt's cause and fixes. A run that gives up shows what went wrong, what you can do, every attempt the agent made, and the full technical traceback (copyable), with a **Try again** button.

Then **ask your data**: "churn rate by contract for the North region", "monthly revenue trend", "top 5 cities by orders". Each answer is computed from the cleaned data, drawn as a chart, and can be pinned to the dashboard.

| Start page | A question card when the agent is unsure |
|---|---|
| ![Start](docs/screenshots/start.png) | ![Review](docs/screenshots/review.png) |
| **Insights + chat** | **Prepared data + verification** |
| ![Insights](docs/screenshots/insights.png) | ![Data](docs/screenshots/data.png) |

---

## Quick start

You need **Python 3.10+**. Node.js 18+ is only needed if you change the frontend; a built copy is included.

**macOS / Linux**
```bash
./start.sh
```

**Windows**
```bat
start.bat
```

Both scripts create a virtual environment, install the Python packages, build the frontend if Node.js is available, and open **http://localhost:8000**.

Manual start:
```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Try it in 30 seconds: on the start page click **Customer churn CSV**, then type `predict churn` to the agent. It shows each step it takes (read your request → matched columns → set the goal), then starts the run after a 3-second countdown (**Not yet** cancels). Press **Run now** without a goal and it will ask you with a question card instead.

**Why replies are instant without an LLM:** the default provider is the rules engine, which is deterministic and answers in milliseconds. The chip in the agent header shows which brain is active; click it to connect Ollama, Groq or Gemini for real model reasoning (each LLM step is then shown with its timing). Live runs are played back at a readable pace so you can watch every block, even when the work itself takes a second; turn this off under **Settings → Appearance → Follow runs at a readable pace**.

---

## Configuration: the `.env` file

API keys, the LLM provider and model names live in **`backend/.env`**. It is created from `backend/.env.example` on the first start:

```ini
# heuristic | ollama | groq | gemini   ("heuristic" = rules engine, no LLM)
DATAMIND_LLM_PROVIDER=heuristic

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b

GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
```

Edit it in any text editor and restart, or change these values in **Settings → Models**, which writes them back to `.env`. Variables already set in your shell take priority. `.env` is in `.gitignore`, so keys never end up on GitHub. Other preferences (privacy, agent behaviour, preparation defaults, theme) are stored separately in `backend/data/settings.json`.

### Choosing the LLM (all free)

Data Mind works with no LLM at all (the rules engine). Adding one improves planning, verification and summaries.

| Provider | Setup | Notes |
|---|---|---|
| **Rules engine only** | nothing | Deterministic, offline, fast. |
| **Ollama** (local) | Install from [ollama.com](https://ollama.com), then `ollama pull llama3.2:3b` | Private, free, runs on 8 GB RAM. `qwen2.5:3b` or `llama3.1:8b` plan better if you have the memory. |
| **Groq** | Free API key at [console.groq.com](https://console.groq.com) → `GROQ_API_KEY` | Very fast hosted open models. Free tier has rate limits. |
| **Gemini** | Free API key at [aistudio.google.com](https://aistudio.google.com) → `GEMINI_API_KEY` | Free tier has rate limits. |

With **fallback** on, if the chosen provider fails or hits a rate limit, Data Mind tries the next one, and finally continues with the rules engine, so a run never fails because of an LLM.

**Privacy:** the LLM receives only column statistics (types, missing share, ranges, skew, warnings). Category labels, needed to merge spelling variants, are shared with the local model by default and with cloud models only if you turn that on. API keys and database credentials are never included in prompts.

---

## Databases

**New analysis → Database**, paste a SQLAlchemy URL and click Connect:

```
sqlite:///C:/data/shop.db
postgresql://user:password@localhost:5432/shop      # pip install psycopg2-binary
mysql+pymysql://user:password@localhost:3306/shop   # pip install pymysql
```

Pick one table, or several: joins are suggested from foreign keys and matching column names. You can also write your own query. Only a single read-only `SELECT` is accepted (checked with `sqlglot`). A sample SQLite database with customers, products and orders is included under **Samples**.

---

## How it works

```
                 ┌──────────── unsure ───────────┐
                 ▼                               │
 ingest → profile → understand ──► plan ──► validate ──► review ──► execute
                     ▲    │          ▲  ◄─invalid─┘         │answers      │
                     └ clarify       └────────────◄─────────┘             ▼
                                     ▲                                  checks
                                     └──────── revise ◄──── verify ◄──────┘
                                                              │approve
                                                    insights ◄ export
```

* **LangGraph `StateGraph`** with conditional edges and three loops (invalid plan, user answers, verifier revision). `interrupt()` pauses the graph for your input; the run resumes when you answer.
* **LLM proposes, code executes.** The LLM can only change whitelisted fields (`impute`, `encode`, `scale`, `outliers`, `role`, …) to whitelisted values. Unknown columns and fields are dropped; inconsistent plans are rejected by `validate_plan` and sent back.
* **No leakage by construction.** The full pipeline (`Cleaner → Featurizer → ColumnTransformer`) is fitted on the training rows only. Target encoding uses cross-fitting with fixed folds.
* **Reproducible.** `pipeline.joblib` transforms new raw files identically; `reproduce.py` rebuilds everything from `plan.json` without Data Mind. The test suite checks that the output is byte-identical.
* **Live UI.** Every agent step emits events over Server-Sent Events. The React Flow graph animates the active stage and edge, and any completed run can be replayed at 0.5×–4× speed.

### Project layout

```
data-mind/
├── backend/
│   ├── run.py                       # start the server
│   ├── datamind_transformers.py     # portable runtime shipped with every exported pipeline
│   ├── app/
│   │   ├── main.py                  # FastAPI: datasets, DB, chat, runs, SSE, insights, settings
│   │   ├── agent/                   # LangGraph graph, runner, LLM providers, prompts, intake chat
│   │   ├── engine/                  # ingest, profiler, plan schema, rules planner, executor, checks, exporter
│   │   ├── insights/                # insight engine + chat-to-chart
│   │   ├── db/                      # SQLAlchemy connector, join inference, read-only SQL guard
│   │   └── samples/                 # generated sample CSV and SQLite database
│   └── tests/                       # pytest: engine, insights, full agent run through the API
└── frontend/                        # React 19 + TypeScript + Tailwind 4 + React Flow + Framer Motion + Plotly
```

---

## Development

```bash
# backend with auto-reload
cd backend && python run.py --reload --no-browser

# frontend dev server (proxies /api to :8000)
cd frontend && npm install && npm run dev      # http://localhost:5173

# tests
cd backend && python -m pytest -q
```

## Limitations and ideas

* Paused runs live in memory; if the server restarts while a run waits for your answer, start it again.
* Ordinal encoding uses alphabetical order unless you override it.
* Ideas: SHAP explanations per feature, a model-training stage, time-series features, a persistent LangGraph checkpointer (SQLite), and scheduled refresh of database imports.

## License

MIT

## Developer
Developed by Dara Singh

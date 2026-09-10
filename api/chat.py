"""
The thin chat (SOW capability 7). A planner asks in English; the answer is checkable.

The rule that makes this trustworthy is the one it is easiest to break: **the model
never calculates**. It has four tools, each of which returns figures the engine
already wrote to `results/`. The model chooses a tool, the tool answers, the model
narrates that answer in two or three sentences, and the rows the tool returned are
shown underneath so anyone can check the sentence against the table. If a question
needs a number no tool provides, the model is instructed to say so rather than
estimate — and the instruction is tested.

Arguments are validated with Pydantic before any tool runs, so a hallucinated
storeroom or a negative `top_n` is a clean error, not a stack trace. The API key
comes from the environment and nowhere else; without it the endpoint says so.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from contracts.config import RunConfig
from engine.dead_money import CATEGORY_LABEL
from engine.positions import POSITIONS_FILE, STOREROOM_FILE

KEY_VAR = "ANTHROPIC_API_KEY"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def load_dotenv(path: Path | None = None) -> None:
    """
    Read KEY=value lines from a git-ignored .env into the environment, never
    overriding what is already set. Stdlib, because python-dotenv would be a new
    dependency for twelve lines. The file itself never enters the repo.
    """
    path = path or Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()


def _key() -> str:
    return os.environ.get(KEY_VAR, "") or os.environ.get("OPENROUTER_API_KEY", "")


def _provider() -> str:
    """OpenRouter keys start with sk-or-; anything else goes to Anthropic directly."""
    return "openrouter" if _key().startswith("sk-or-") else "anthropic"


def _model() -> str:
    if os.environ.get("CHAT_MODEL"):
        return os.environ["CHAT_MODEL"]
    return "anthropic/claude-sonnet-4.5" if _provider() == "openrouter" else "claude-sonnet-5"


MODEL = _model()

Storeroom = Literal["BAITHA", "CENTRAL", "REFINERY", "ROLLING", "SMELTER"]
Criticality = Literal["A", "B", "C"]
Category = Literal["obsolete_equipment", "duplicate", "never_used", "obsolete_idle", "excess"]


# ── tool arguments, validated ────────────────────────────────────────────────


class StockoutsArgs(BaseModel):
    storeroom: Storeroom | None = None
    criticality: Criticality | None = None
    top_n: int = Field(10, ge=1, le=50)


class DeadMoneyArgs(BaseModel):
    storeroom: Storeroom | None = None
    category: Category | None = None
    top_n: int = Field(10, ge=1, le=50)


class ItemArgs(BaseModel):
    material_id: str = Field(pattern=r"^M-\d{6}$")
    storeroom_id: Storeroom | None = None


class TransfersArgs(BaseModel):
    storeroom: Storeroom | None = None
    top_n: int = Field(10, ge=1, le=50)


TOOLS = {
    "get_stockouts": (
        StockoutsArgs,
        "Parts that are out of stock or below their safe level, most urgent first. "
        "Optionally one storeroom and/or one criticality (A stops the plant, B slows "
        "production, C somebody waits). Returns the count, the SAR to bring them back "
        "to level, and the top rows.",
    ),
    "get_dead_money": (
        DeadMoneyArgs,
        "Stock the engine has found to be dead money — obsolete, duplicate, never used, "
        "idle, or excess — valued at moving average and ranked by SAR. Optionally one "
        "storeroom and/or one category. Returns the total and the top rows.",
    ),
    "get_item": (
        ItemArgs,
        "Everything known about one part: on hand, our reorder point and fill-up "
        "level, the plant's old min/max, expected use, what to do, and the reason for "
        "the level. Needs the material id like M-016367; storeroom optional.",
    ),
    "get_transfers": (
        TransfersArgs,
        "Stock that could be moved between storerooms instead of bought: the same part "
        "spare in one store while another is below its level. Optionally one storeroom "
        "(as sender or receiver). Returns the count, SAR saved, and the top rows.",
    ),
}

# columns a row carries back to the screen; the drawer has the rest
ROW_COLUMNS = ["material_id", "storeroom_id", "description", "criticality", "on_hand",
               "uom", "reorder_point", "action", "order_now_qty", "cost_to_level_sar",
               "value_sar"]


def _clean(v):
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.date().isoformat()
    if hasattr(v, "tolist"):
        return v.tolist()
    return v


def _rows(frame: pd.DataFrame, cols: list[str]) -> list[dict]:
    have = [c for c in cols if c in frame.columns]
    return [{k: _clean(v) for k, v in r.items()} for r in frame[have].to_dict("records")]


# ── the tools: precomputed answers, filtered ─────────────────────────────────


def _positions(cfg: RunConfig) -> pd.DataFrame:
    return pd.read_parquet(cfg.results_dir / POSITIONS_FILE)


def get_stockouts(cfg: RunConfig, a: StockoutsArgs) -> dict:
    df = _positions(cfg)
    df = df[df["action"].isin(["order_now", "stocked_elsewhere"])]
    if a.storeroom:
        df = df[df["storeroom_id"] == a.storeroom]
    if a.criticality:
        df = df[df["criticality"] == a.criticality]
    return {
        "count": int(len(df)),
        "none_left": int((df["on_hand"] <= 0).sum()),
        "cost_to_level_sar": float(df["cost_to_level_sar"].sum()),
        "rows": _rows(df.head(a.top_n), ROW_COLUMNS),
        "scope": {"storeroom": a.storeroom or "all", "criticality": a.criticality or "all"},
    }


def get_dead_money(cfg: RunConfig, a: DeadMoneyArgs) -> dict:
    path = cfg.results_dir / "dead_money.parquet"
    if not path.exists():
        return {"error": "dead money has not been computed — run `python cli.py run`"}
    df = pd.read_parquet(path)
    if a.storeroom:
        df = df[df["storeroom_id"] == a.storeroom]
    if a.category:
        df = df[df["category"] == a.category]
    by_cat = df.groupby("category")["dead_value_sar"].sum()
    return {
        "count": int(len(df)),
        "dead_value_sar": float(df["dead_value_sar"].sum()),
        "by_category": {CATEGORY_LABEL.get(k, k): float(v) for k, v in by_cat.items()},
        "rows": _rows(df.head(a.top_n), ["material_id", "storeroom_id", "description",
                                           "criticality", "category_label", "dead_qty",
                                           "uom", "dead_value_sar", "reason"]),
        "scope": {"storeroom": a.storeroom or "all", "category": a.category or "all"},
    }


def get_item(cfg: RunConfig, a: ItemArgs) -> dict:
    df = _positions(cfg)
    hit = df[df["material_id"] == a.material_id]
    if a.storeroom_id:
        hit = hit[hit["storeroom_id"] == a.storeroom_id]
    if hit.empty:
        return {"error": f"no position for {a.material_id}"
                         + (f" in {a.storeroom_id}" if a.storeroom_id else "")}
    cols = ROW_COLUMNS + ["min_qty", "max_qty", "order_up_to", "service_level", "demand_class",
                          "forecast_6m", "last_issue_date", "lead_time_days", "reason",
                          "runs_out_date", "order_by_date", "shutdown_qty_per_event",
                          "next_shutdown_date", "manufacturer", "mpn"]
    return {"count": int(len(hit)), "rows": _rows(hit, cols)}


def get_transfers(cfg: RunConfig, a: TransfersArgs) -> dict:
    report = json.loads((cfg.results_dir / STOREROOM_FILE).read_text(encoding="utf-8"))
    moves = report.get("transfers", [])
    if a.storeroom:
        moves = [m for m in moves
                 if a.storeroom in (m["from_storeroom"], m["to_storeroom"])]
    return {
        "count": len(moves),
        "saved_sar": float(sum(m["value_sar"] for m in moves)),
        "rows": moves[: a.top_n],
        "scope": {"storeroom": a.storeroom or "all"},
    }


EXECUTORS = {
    "get_stockouts": get_stockouts,
    "get_dead_money": get_dead_money,
    "get_item": get_item,
    "get_transfers": get_transfers,
}


def run_tool(cfg: RunConfig, name: str, raw_args: dict) -> dict:
    """Validate, then answer from results/. Anything else is an error the model sees."""
    if name not in TOOLS:
        return {"error": f"unknown tool {name}"}
    schema = TOOLS[name][0]
    try:
        args = schema(**(raw_args or {}))
    except ValidationError as exc:
        return {"error": "bad arguments: " + "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())}
    return EXECUTORS[name](cfg, args)


def tool_specs() -> list[dict]:
    return [
        {"name": name, "description": desc, "input_schema": schema.model_json_schema()}
        for name, (schema, desc) in TOOLS.items()
    ]


# ── the model ────────────────────────────────────────────────────────────────

SYSTEM = """You are the planner's assistant for a spare-parts storeroom system at an
aluminium plant. You answer ONLY from the tools. Rules, in order of importance:
1. Never calculate, estimate, add up, or infer a number. Every figure in your answer
   must appear verbatim in a tool result. If the question needs a figure no tool
   gives, say plainly that you cannot answer that from the data you have, and say
   which tool comes closest.
2. Pick one tool per question (two only if the question genuinely has two parts).
3. Answer in two or three plain sentences, no bullet lists, no headings. Money in
   SAR millions to one decimal when above SAR 100,000, otherwise whole riyals.
   Name parts by description and id. The rows will be shown under your answer, so
   do not list them.
4. Criticality A means the plant stops without the part, B production slows, C
   somebody waits. "Dead money" means stock the engine found will never be used.
"""


def status() -> dict:
    return {"available": bool(_key()), "model": _model(), "provider": _provider(),
            "key_var": KEY_VAR, "tools": list(TOOLS)}


def _prior(history: list | None) -> list[dict]:
    """
    The last few exchanges, as plain user/assistant text, so a follow-up like "and
    in the smelter?" has something to follow. Only the narrated answers are carried,
    never the tool results — the model must call the tool again, not remember it.
    """
    out = []
    for h in (history or [])[-6:]:
        q, a = str(h.get("question", "")).strip()[:500], str(h.get("answer", "")).strip()[:1000]
        if q and a:
            out += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    return out


def answer(cfg: RunConfig, question: str, history: list | None = None) -> dict:
    """One round: the model picks a tool, the engine answers, the model narrates."""
    if not _key():
        return {"status": "unavailable",
                "detail": f"chat unavailable — set {KEY_VAR} in the environment"}
    if _provider() == "openrouter":
        return _answer_openrouter(cfg, question, history)
    import anthropic

    client = anthropic.Anthropic()
    messages = _prior(history) + [{"role": "user", "content": question}]
    first = client.messages.create(model=MODEL, max_tokens=600, system=SYSTEM,
                                   tools=tool_specs(), messages=messages)
    calls = [b for b in first.content if b.type == "tool_use"]
    if not calls:
        text = "".join(b.text for b in first.content if b.type == "text")
        return {"status": "ok", "tool": None, "args": None, "result": None, "answer": text,
                "rows": []}

    results, used = [], []
    for call in calls[:2]:
        out = run_tool(cfg, call.name, call.input)
        used.append({"tool": call.name, "args": call.input, "result": _trim(out)})
        results.append({"type": "tool_result", "tool_use_id": call.id,
                        "content": json.dumps(_trim(out), default=str)})
    messages += [{"role": "assistant", "content": first.content},
                 {"role": "user", "content": results}]
    second = client.messages.create(model=MODEL, max_tokens=400, system=SYSTEM,
                                    tools=tool_specs(), messages=messages)
    text = "".join(b.text for b in second.content if b.type == "text").strip()
    primary = used[0]
    return {
        "status": "ok",
        "tool": primary["tool"],
        "args": primary["args"],
        "result": primary["result"],
        "answer": text,
        "rows": (run_tool(cfg, primary["tool"], primary["args"]).get("rows") or []),
    }


# ── OpenRouter: the same four tools through the OpenAI-style tool-calling API ──


def _openrouter(payload: dict) -> dict:
    req = urllib.request.Request(
        OPENROUTER_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://github.com/YASHSALI2005/Ai_inventory",
                 "X-Title": "Inventory Intelligence POC"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"OpenRouter {exc.code}: {body}") from exc


def _answer_openrouter(cfg: RunConfig, question: str, history: list | None = None) -> dict:
    tools = [{"type": "function", "function": {
        "name": name, "description": desc, "parameters": schema.model_json_schema()}}
        for name, (schema, desc) in TOOLS.items()]
    messages = ([{"role": "system", "content": SYSTEM}] + _prior(history)
                + [{"role": "user", "content": question}])
    first = _openrouter({"model": _model(), "messages": messages, "tools": tools,
                         "tool_choice": "auto", "max_tokens": 600, "temperature": 0})
    msg = first["choices"][0]["message"]
    calls = msg.get("tool_calls") or []
    if not calls:
        return {"status": "ok", "tool": None, "args": None, "result": None,
                "answer": (msg.get("content") or "").strip(), "rows": []}

    used = []
    messages.append({"role": "assistant", "content": msg.get("content") or "",
                     "tool_calls": calls[:2]})
    for call in calls[:2]:
        name = call["function"]["name"]
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        out = run_tool(cfg, name, args)
        used.append({"tool": name, "args": args})
        messages.append({"role": "tool", "tool_call_id": call["id"],
                         "content": json.dumps(_trim(out), default=str)})
    second = _openrouter({"model": _model(), "messages": messages, "tools": tools,
                          "max_tokens": 400, "temperature": 0})
    text = (second["choices"][0]["message"].get("content") or "").strip()
    primary = used[0]
    full = run_tool(cfg, primary["tool"], primary["args"])
    return {"status": "ok", "tool": primary["tool"], "args": primary["args"],
            "result": _trim(full), "answer": text, "rows": full.get("rows") or []}


def _trim(out: dict) -> dict:
    """What the model sees: the figures and the first rows, not 25,000 of them."""
    t = dict(out)
    if "rows" in t:
        t["rows"] = t["rows"][:10]
    return t


def golden_questions_path() -> Path:
    return Path(__file__).resolve().parent.parent / "tests" / "golden_questions.json"

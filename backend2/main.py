import os
import sqlite3
import json
import urllib.error
import re
from typing import List
import requests

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = FastAPI(title="Oceanographic Data Assistant API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    query: str


ARGO_DB_PATH = os.environ.get(
    "ARGO_DB_PATH",
    os.path.join(os.path.dirname(__file__), "database", "argo_floats_new.db"),
)
MAX_ROWS = int(os.environ.get("SQL_MAX_ROWS", "200"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")

# Backward compatibility: if someone still sets GROK_* vars, keep supporting xAI.
GROK_API_KEY = os.environ.get("GROK_API_KEY", "").strip()
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-2-latest")
GROK_BASE_URL = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1/chat/completions")

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto").strip().lower()


def _is_sql_query(text: str) -> bool:
    normalized = text.strip().lower()
    sql_starts = (
        "select ",
        "with ",
        "pragma ",
        "insert ",
        "update ",
        "delete ",
        "create ",
        "alter ",
        "drop ",
    )
    return normalized.startswith(sql_starts)


def _escape_markdown_cell(value: object) -> str:
    if value is None:
        return "NULL"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _format_markdown_table(columns: List[str], rows: List[sqlite3.Row]) -> str:
    if not rows:
        return "Query executed successfully. No rows returned."

    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = [
        "| " + " | ".join(_escape_markdown_cell(row[col]) for col in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def _ensure_sectioned_markdown(text: str, default_title: str = "Answer") -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return f"## {default_title}\n\nNo content returned."
    if cleaned.startswith("## "):
        return cleaned
    return f"## {default_title}\n\n{cleaned}"


def _format_sql_response_local(sql_query: str, sql_output: str) -> str:
    summary = "Query executed successfully."
    rows_match = re.search(r"Rows returned:\s*(\d+)", sql_output)
    if rows_match:
        summary = f"Query executed successfully. Rows returned: {rows_match.group(1)}."
    return (
        "## Summary\n\n"
        f"{summary}\n\n"
        "## Executed SQL\n\n"
        "```sql\n"
        f"{sql_query}\n"
        "```\n\n"
        "## Data\n\n"
        f"{sql_output}"
    )


def _call_grok(messages: List[dict], temperature: float = 0.2) -> str:
    provider = LLM_PROVIDER
    if provider == "auto":
        if GROQ_API_KEY:
            provider = "groq"
        elif GROK_API_KEY:
            provider = "grok"
        else:
            return ""

    if provider == "groq":
        api_key = GROQ_API_KEY
        model = GROQ_MODEL
        base_url = GROQ_BASE_URL
    elif provider == "grok":
        api_key = GROK_API_KEY
        model = GROK_MODEL
        base_url = GROK_BASE_URL
    else:
        return ""

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    response = requests.post(
        base_url,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "BlueQuery/1.0",
        },
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _get_db_schema(conn: sqlite3.Connection) -> str:
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]
    schema_lines: List[str] = []
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table});")
        cols = [row[1] for row in cursor.fetchall()]
        schema_lines.append(f"{table}({', '.join(cols)})")
    return "\n".join(schema_lines)


def _nl_to_sql_with_grok(user_prompt: str, db_schema: str) -> str:
    if not (GROQ_API_KEY or GROK_API_KEY):
        return ""
    messages = [
        {
            "role": "system",
            "content": (
                "Convert the user request into a single SQLite SELECT query using only the provided schema. "
                "Output only SQL, no explanation, no markdown, no backticks. "
                "If impossible, output exactly: CANNOT_CONVERT"
            ),
        },
        {
            "role": "user",
            "content": f"Schema:\n{db_schema}\n\nRequest:\n{user_prompt}",
        },
    ]
    try:
        sql = _strip_code_fences(_call_grok(messages, temperature=0.0))
        if sql.upper() == "CANNOT_CONVERT":
            return ""
        return sql
    except (requests.RequestException, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError):
        return ""


def _answer_general_with_grok(user_prompt: str) -> str:
    if not (GROQ_API_KEY or GROK_API_KEY):
        return ""
    messages = [
        {
            "role": "system",
            "content": (
                "You are an oceanographic assistant for ARGO projects. "
                "Answer clearly in markdown with short sections. "
                "If the user asks a general concept question, answer directly without SQL."
            ),
        },
        {"role": "user", "content": user_prompt},
    ]
    try:
        return _call_grok(messages, temperature=0.3)
    except (requests.RequestException, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError):
        return ""


def _answer_general_local(user_prompt: str) -> str:
    prompt = user_prompt.strip().lower()
    if "project" in prompt and ("about" in prompt or "what is this" in prompt):
        return (
            "## About This Project\n\n"
            "This project is an ocean-data assistant for ARGO research. It combines:\n"
            "- A relational SQLite database of ARGO observations\n"
            "- Natural-language query handling for researchers\n"
            "- SQL-based data retrieval and formatted result summaries\n"
            "- A frontend chat/dashboard for exploration and analysis\n\n"
            "The goal is to let users ask oceanographic questions and get reliable, data-backed responses."
        )
    if "explain argo" in prompt or ("argo" in prompt and "explain" in prompt):
        return (
            "## ARGO In Simple Terms\n\n"
            "ARGO is a global ocean observing system made of autonomous profiling floats. "
            "These floats drift in the ocean, dive and rise on cycles, measure temperature/salinity "
            "(and sometimes biogeochemical parameters), and transmit data via satellite when they surface."
        )
    if "argo float" in prompt and ("what is" in prompt or "what's" in prompt):
        return (
            "## What Is an Argo Float?\n\n"
            "An Argo float is an autonomous ocean instrument that drifts at depth, "
            "then periodically dives and rises to measure seawater properties such as "
            "temperature and salinity. It sends profiles to satellites when it surfaces, "
            "helping scientists monitor ocean conditions and climate change."
        )
    return (
        "## General Answer\n\n"
        "I could not reach the external model right now, but your request is treated as a "
        "normal question (not SQL). Please retry once, or ask a data question with location/time "
        "details so I can run database-backed analysis."
    )


def _extract_lat_lon(text: str):
    cleaned = text.replace("°", " ").upper()
    # Matches patterns like "15 N, 90 E" or "15N 90E"
    m = re.search(
        r"(-?\d+(?:\.\d+)?)\s*([NS])?\s*[, ]+\s*(-?\d+(?:\.\d+)?)\s*([EW])?",
        cleaned,
    )
    if not m:
        return None
    lat = float(m.group(1))
    lon = float(m.group(3))
    lat_dir = m.group(2)
    lon_dir = m.group(4)
    if lat_dir == "S":
        lat = -abs(lat)
    if lat_dir == "N":
        lat = abs(lat)
    if lon_dir == "W":
        lon = -abs(lon)
    if lon_dir == "E":
        lon = abs(lon)
    return lat, lon


def _find_column_name(columns: List[str], candidates: List[str]) -> str:
    lookup = {c.lower(): c for c in columns}
    for name in candidates:
        if name.lower() in lookup:
            return lookup[name.lower()]
    return ""


def _nearest_float_sql_from_prompt(conn: sqlite3.Connection, user_prompt: str) -> str:
    p = user_prompt.lower()
    if "nearest" not in p or "float" not in p:
        return ""
    coords = _extract_lat_lon(user_prompt)
    if not coords:
        return ""
    lat, lon = coords

    c = conn.cursor()
    c.execute("PRAGMA table_info(traj_rel);")
    traj_cols = [row[1] for row in c.fetchall()]
    if not traj_cols:
        return ""

    lat_col = _find_column_name(traj_cols, ["latitude", "lat"])
    lon_col = _find_column_name(traj_cols, ["longitude", "lon", "long"])
    id_col = _find_column_name(traj_cols, ["platform_number", "platform", "float_id", "id"])
    juld_col = _find_column_name(traj_cols, ["juld", "date", "timestamp", "time"])

    if not lat_col or not lon_col:
        return ""

    select_cols = []
    if id_col:
        select_cols.append(f"{id_col} AS platform_number")
    select_cols.extend([f"{lat_col} AS latitude", f"{lon_col} AS longitude"])
    if juld_col:
        select_cols.append(f"{juld_col} AS juld")

    select_cols_sql = ", ".join(select_cols)
    dist_expr = (
        f"(({lat_col} - ({lat:.8f})) * ({lat_col} - ({lat:.8f})) + "
        f"({lon_col} - ({lon:.8f})) * ({lon_col} - ({lon:.8f})))"
    )
    return (
        f"SELECT {select_cols_sql}, {dist_expr} AS distance_sq "
        f"FROM traj_rel "
        f"WHERE {lat_col} IS NOT NULL AND {lon_col} IS NOT NULL "
        f"ORDER BY distance_sq ASC LIMIT 5;"
    )


def _refine_with_grok(sql_query: str, sql_output: str) -> str:
    if not (GROQ_API_KEY or GROK_API_KEY):
        return _format_sql_response_local(sql_query, sql_output)

    messages = [
            {
                "role": "system",
                "content": (
                    "You are a SQL result formatter for an ocean data assistant. "
                    "Output markdown with exactly these sections: "
                    "## Summary, ## Executed SQL, ## Data. "
                    "In Data section, include the SQL output exactly as provided. "
                    "Do not invent rows, values, or metrics. Keep all numbers unchanged."
                ),
            },
            {
                "role": "user",
                "content": f"SQL Query:\n{sql_query}\n\nSQL Output:\n{sql_output}",
            },
        ]

    try:
        refined = _call_grok(messages, temperature=0.2)
        return _ensure_sectioned_markdown(refined, "SQL Result") if refined else _format_sql_response_local(sql_query, sql_output)
    except (requests.RequestException, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError):
        return _format_sql_response_local(sql_query, sql_output)


@app.post("/query")
async def process_query(request: QueryRequest):
    user_query = request.query.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="Empty query")

    if not os.path.exists(ARGO_DB_PATH):
        raise HTTPException(
            status_code=500,
            detail=f"Database file not found at ARGO_DB_PATH={ARGO_DB_PATH}",
        )

    try:
        with sqlite3.connect(ARGO_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            sql_to_execute = user_query

            if not _is_sql_query(user_query):
                heuristic_sql = _nearest_float_sql_from_prompt(conn, user_query)
                if heuristic_sql:
                    sql_to_execute = heuristic_sql
                else:
                    schema = _get_db_schema(conn)
                    converted_sql = _nl_to_sql_with_grok(user_query, schema)
                    if not converted_sql:
                        general_answer = _answer_general_with_grok(user_query)
                        if general_answer:
                            return {
                                "query": user_query,
                                "result": _ensure_sectioned_markdown(general_answer, "Answer"),
                                "source": "grok_general",
                            }
                        return {
                            "query": user_query,
                            "result": _answer_general_local(user_query),
                            "source": "local_general_fallback",
                        }
                    if not _is_sql_query(converted_sql):
                        general_answer = _answer_general_with_grok(user_query)
                        if general_answer:
                            return {
                                "query": user_query,
                                "result": _ensure_sectioned_markdown(general_answer, "Answer"),
                                "source": "grok_general",
                            }
                        return {
                            "query": user_query,
                            "result": _answer_general_local(user_query),
                            "source": "local_general_fallback",
                        }
                    sql_to_execute = converted_sql

            cursor = conn.cursor()
            cursor.execute(sql_to_execute)

            if cursor.description:
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchmany(MAX_ROWS)
                result = _format_markdown_table(columns, rows)
                total_info = (
                    f"\n\nRows returned: {len(rows)}"
                    + (f" (capped at {MAX_ROWS})" if len(rows) == MAX_ROWS else "")
                )
                raw_result = result + total_info
                final_result = _refine_with_grok(sql_to_execute, raw_result)
                return {"query": user_query, "executed_sql": sql_to_execute, "result": final_result}

            conn.commit()
            affected = cursor.rowcount if cursor.rowcount is not None else 0
            return {
                "query": user_query,
                "executed_sql": sql_to_execute,
                "result": f"Statement executed successfully. Rows affected: {affected}.",
            }
    except sqlite3.Error as exc:
        return {"query": user_query, "result": f"SQL error: {exc}"}
    except Exception as exc:
        return {"query": user_query, "result": f"Backend error: {exc}"}


@app.get("/health")
async def health():
    active_provider = "none"
    if LLM_PROVIDER == "auto":
        if GROQ_API_KEY:
            active_provider = "groq"
        elif GROK_API_KEY:
            active_provider = "grok"
    elif LLM_PROVIDER in ("groq", "grok"):
        active_provider = LLM_PROVIDER

    return {
        "status": "ok",
        "db_exists": os.path.exists(ARGO_DB_PATH),
        "llm_configured": bool(GROQ_API_KEY or GROK_API_KEY),
        "llm_provider": active_provider,
        "llm_model": GROQ_MODEL if active_provider == "groq" else GROK_MODEL,
    }

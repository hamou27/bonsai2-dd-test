#!/usr/bin/env python3
"""Bonsai 2 27B FULL test for DD — all 10 Darija questions Cleo took.

Same yardstick as Cleo (understood / valid SQL / correct result) and the
same ground truths from test-cleo-real.py, plus the strict TVA direct
question (exempt invoice TVA must be 0, not 940,661.88 DZD).

Runs in GitHub Codespaces (free machine: 4 vCPU / 8 GB RAM, no GPU).
The model file is ~5.7 GB resident, so it fits in 8 GB with a small
KV cache (server: 1 slot, 2048 ctx) — unlike the first run on a 6 GB
machine, where the model could not stay in RAM and every token was
re-read from disk (prefill ~0.5 tok/s, decode 0.02-0.13 tok/s, Q1 timed
out twice at 30 min, zero SQL produced).

THINKING (corrected finding, 2026-11-15): Bonsai 2 thinks by default
(xhigh) and this fork IGNORES the `enable_thinking: false` API field,
and the GGUF chat template has NO `/no_think` support — so both Q1
runs on the weak machine spent 30 min generating a reasoning trace and
returned zero answer tokens. The `/no_think` suffix is still sent in
the prompt (harmless), but it is NOT verified to work. The 30-min
per-question allowance stands, with streaming early-stop as soon as
the SQL statement is complete. Results are saved incrementally after
every question so a partial run still reports.

Pass bar: >=8/10 correct + strict TVA pass + under ~10 s/question.
"""
import importlib.util
import json
import re
import sqlite3
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
HARNESS_PATH = ROOT / "test-cleo-real.py"
DB_PATH = ROOT / "dd-real-test.db"
SERVER_URL = "http://127.0.0.1:8899/v1/chat/completions"
OUT_JSON = ROOT / "results-bonsai2.json"
MAX_SECONDS_PER_Q = 1800

spec = importlib.util.spec_from_file_location("cleo_harness", HARNESS_PATH)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
QUESTIONS = harness.QUESTIONS
SCHEMA = harness.SCHEMA
judge_result = harness.judge_result
judge_understood = harness.judge_understood
re_execute = harness.re_execute

SCHEMA_SQL = "\n".join(
    line for line in SCHEMA.splitlines()
    if line.strip().upper().startswith("CREATE TABLE")
)

SYSTEM_PROMPT = (
    "You are an expert SQLite query generator. You are given a database "
    "schema and a question in Arabic (Algerian Darija). Output ONLY a single "
    "valid SQLite SELECT query that answers the question. No explanation, "
    "no markdown, no code fences. Use only the tables and columns in the "
    "schema. Do not invent columns or values. For totals use SUM."
)


def extract_sql(text):
    if not text:
        return None
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    text = re.sub(r"```(?:sql)?", "", text, flags=re.IGNORECASE)
    m = re.search(r"SELECT\b.*?(?:;|$)", text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    sql = m.group(0).strip()
    if sql.endswith(";"):
        sql = sql[:-1].strip()
    if ";" in sql:
        sql = sql.split(";")[0].strip()
    return sql


def sql_complete(text):
    if not text:
        return False
    t = text
    if "</think>" in t:
        t = t.split("</think>", 1)[1]
    t = re.sub(r"```(?:sql)?", "", t, flags=re.IGNORECASE)
    return bool(re.search(r"SELECT\b.*?;", t, flags=re.IGNORECASE | re.DOTALL))


def ask_sql_stream(question):
    payload = {
        "model": "bonsai-2-27b",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"Database schema:\n{SCHEMA_SQL}\n\nQuestion: {question} /no_think"},
        ],
        "temperature": 0,
        "max_tokens": 512,
        "enable_thinking": False,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    t0 = time.time()
    text = ""
    usage = None
    try:
        with requests.post(SERVER_URL, json=payload, stream=True,
                           timeout=MAX_SECONDS_PER_Q) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if time.time() - t0 > MAX_SECONDS_PER_Q:
                    return text, time.time() - t0, "TIMEOUT after 1800s", usage
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    text += delta.get("content", "") or ""
                    if sql_complete(text):
                        break
        return text, time.time() - t0, None, usage
    except Exception as e:
        return text, time.time() - t0, f"{type(e).__name__}: {e}", usage


def ask_direct(question):
    payload = {
        "model": "bonsai-2-27b",
        "messages": [
            {"role": "system",
             "content": "Answer with a single number only. No explanation."},
            {"role": "user", "content": question},
        ],
        "temperature": 0,
        "max_tokens": 64,
        "enable_thinking": False,
        "stream": False,
    }
    t0 = time.time()
    try:
        r = requests.post(SERVER_URL, json=payload, timeout=MAX_SECONDS_PER_Q)
        secs = time.time() - t0
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"], secs, None, data.get("usage")
    except Exception as e:
        return None, time.time() - t0, f"{type(e).__name__}: {e}", None


def save(results, n_u, n_s, n_r, total_secs, done, tva):
    with open(OUT_JSON, "w") as f:
        json.dump({
            "model": "Ternary-Bonsai-2-27B-PTQ1_0 (PrismML llama.cpp fork, CPU, /no_think)",
            "note": "Full 10-question Cleo yardstick, run in GitHub Codespaces "
                    "(4 vCPU / 8 GB RAM, no GPU). 30-min allowance per question "
                    "with streaming early-stop on SQL completion. Thinking cannot "
                    "be disabled on this fork (ignores enable_thinking; GGUF "
                    "template has no /no_think support) — see results markdown.",
            "partial": not done,
            "totals": {"understood": f"{n_u}/{len(results)}",
                       "sql_correct": f"{n_s}/{len(results)}",
                       "result_correct": f"{n_r}/{len(results)}",
                       "total_seconds": round(total_secs, 1),
                       "avg_seconds_per_question": round(total_secs / max(len(results), 1), 1)},
            "results": results,
            "strict_tva_test": tva,
        }, f, ensure_ascii=False, indent=2)


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.commit()
    print("DB rebuilt:", DB_PATH, flush=True)

    results = {}
    n_u = n_s = n_r = 0
    total_secs = 0.0
    for i, q in enumerate(QUESTIONS):
        raw, secs, err, usage = ask_sql_stream(q)
        total_secs += secs
        sql = extract_sql(raw) if raw else None
        rows = None
        if sql:
            try:
                rows = con.execute(sql).fetchall()
            except Exception as e:
                rows = None
                if not err:
                    err = f"SQL exec error: {e}"
        understood = judge_understood(i, sql)
        sql_ok, sql_err = re_execute(con, sql)
        result_ok = bool(rows is not None) and judge_result(i, rows)
        n_u += understood
        n_s += sql_ok
        n_r += result_ok
        results[q] = {
            "index": i + 1, "sql": sql, "raw": raw, "rows": rows, "error": err,
            "understood": understood, "sql_correct": sql_ok,
            "sql_error": sql_err, "result_correct": result_ok,
            "seconds": round(secs, 1), "usage": usage,
        }
        save(results, n_u, n_s, n_r, total_secs, False, None)
        print(f"Q{i+1}: {q}\n  UNDERSTOOD: {'YES' if understood else 'NO'} | "
              f"SQL_OK: {'YES' if sql_ok else 'NO'} | RESULT_OK: {'YES' if result_ok else 'NO'}\n"
              f"  SQL: {sql}\n  ROWS: {rows}\n  ERR: {err}\n  USAGE: {usage}\n  ({secs:.0f}s)\n---", flush=True)

    print(f"BONSAI2 DONE: understood {n_u}/10, sql_ok {n_s}/10, "
          f"result_ok {n_r}/10, total {total_secs:.0f}s, "
          f"avg {total_secs/len(QUESTIONS):.1f}s/q", flush=True)

    tva_q = ("The invoice F-201 is exempt from TVA (exempt = 1). "
             "Its amount before tax is 4,950,852.00 DZD. "
             "What must the correct TVA amount for this invoice be? "
             "Answer with a single number only. /no_think")
    raw, secs, err, usage = ask_direct(tva_q)
    tva_pass = False
    if raw:
        tva_pass = ("940661" not in raw.replace(",", "").replace(" ", "")
                    and any(n in ("0", "0.0", "0.00")
                            for n in re.findall(r"[\d,]+\.?\d*", raw.replace(",", ""))))
    tva = {"question": tva_q, "raw": raw, "seconds": round(secs, 1),
           "error": err, "pass": tva_pass, "usage": usage}
    print(f"STRICT TVA TEST: {'PASS' if tva_pass else 'FAIL'} "
          f"(raw={raw!r}, {secs:.0f}s, err={err})", flush=True)

    save(results, n_u, n_s, n_r, total_secs, True, tva)
    print("BONSAI2_TEST_DONE", flush=True)


if __name__ == "__main__":
    main()

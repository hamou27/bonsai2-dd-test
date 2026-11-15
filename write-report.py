#!/usr/bin/env python3
"""Turn results-bonsai2.json into a readable bonsai2-dd-test-results.md.

Run by run-test.sh after the harness finishes. Works on partial runs too
(missing questions are listed as not run).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IN_JSON = ROOT / "results-bonsai2.json"
OUT_MD = ROOT / "bonsai2-dd-test-results.md"

PASS_CORRECT = 8
PASS_SECONDS_PER_Q = 10


def verdict(data):
    totals = data.get("totals", {})
    rc = totals.get("result_correct", "0/0")
    try:
        n_correct = int(rc.split("/")[0])
        n_total = int(rc.split("/")[1])
    except Exception:
        n_correct, n_total = 0, 0
    tva = data.get("strict_tva_test") or {}
    tva_pass = bool(tva.get("pass"))
    avg = totals.get("avg_seconds_per_question")
    speed_ok = isinstance(avg, (int, float)) and avg < PASS_SECONDS_PER_Q
    passed = (n_correct >= PASS_CORRECT and tva_pass and speed_ok
              and n_total == 10 and not data.get("partial"))
    reasons = []
    if n_total < 10 or data.get("partial"):
        reasons.append(f"only {n_total}/10 questions attempted")
    if n_correct < PASS_CORRECT:
        reasons.append(f"correct {n_correct}/10 (need >={PASS_CORRECT})")
    if not tva_pass:
        reasons.append("strict TVA test did not pass")
    if not speed_ok:
        reasons.append(f"avg {avg}s/question (need <{PASS_SECONDS_PER_Q}s)")
    return passed, reasons, n_correct, n_total, tva_pass, avg, speed_ok


def main():
    if not IN_JSON.exists():
        raise SystemExit(f"missing {IN_JSON} — run the test first")
    data = json.loads(IN_JSON.read_text(encoding="utf-8"))
    passed, reasons, n_correct, n_total, tva_pass, avg, speed_ok = verdict(data)
    totals = data.get("totals", {})
    results = data.get("results", {}) or {}
    tva = data.get("strict_tva_test") or {}

    lines = []
    lines.append("# Bonsai 2 27B — DD test results (GitHub Codespaces, 4 vCPU / 8 GB RAM)")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if passed:
        lines.append("- **PASS: adopt as DD's SQL brain** — "
                     f"{n_correct}/10 correct, strict TVA passed, "
                     f"avg {avg}s/question.")
    else:
        lines.append("- **FAIL — do NOT adopt Bonsai 2 as DD's SQL brain on this machine.**")
        for r in reasons:
            lines.append(f"  - {r}")
    lines.append(f"- Scores: understood {totals.get('understood')}, "
                 f"valid SQL {totals.get('sql_correct')}, "
                 f"correct {totals.get('result_correct')}.")
    lines.append("- Cleo baseline to beat: understood 8/10, valid SQL 9/10, "
                 "correct 6/10.")
    lines.append("- Model: Ternary-Bonsai-2-27B-PTQ1_0 (PrismML llama.cpp fork, "
                 "CPU-only). The vendor's 98.2% retention figure is PrismML's "
                 "own claim, not verified by this test.")
    lines.append("")
    lines.append("## Per-question results")
    lines.append("")
    lines.append("| # | Question | SQL produced | Understood | Valid SQL | Correct | Seconds |")
    lines.append("|---|---|---|---|---|---|---|")
    for q, r in sorted(results.items(), key=lambda kv: kv[1].get("index", 0)):
        idx = r.get("index", "?")
        sql = (r.get("sql") or "none").replace("|", "\\|").replace("\n", " ")
        if len(sql) > 80:
            sql = sql[:77] + "..."
        err = r.get("error") or ""
        if err and not r.get("sql"):
            sql = f"none — {err}"
        lines.append(f"| {idx} | {q} | {sql} | "
                     f"{'YES' if r.get('understood') else 'NO'} | "
                     f"{'YES' if r.get('sql_correct') else 'NO'} | "
                     f"{'YES' if r.get('result_correct') else 'NO'} | "
                     f"{r.get('seconds', '?')} |")
    if n_total < 10:
        lines.append("")
        lines.append(f"Questions {n_total + 1}–10 were not run.")
    lines.append("")
    lines.append("## Strict TVA test (exempt invoice TVA must be 0, not 940,661.88 DZD)")
    lines.append("")
    if tva:
        lines.append(f"- Result: **{'PASS' if tva_pass else 'FAIL'}** "
                     f"(raw answer: {tva.get('raw')!r}, "
                     f"{tva.get('seconds')}s, error: {tva.get('error')})")
    else:
        lines.append("- NOT RUN")
    lines.append("")
    lines.append("## Speed")
    lines.append("")
    lines.append(f"- Total: {totals.get('total_seconds')}s for {n_total} question(s).")
    lines.append(f"- Average: {avg}s/question (DD promises <{PASS_SECONDS_PER_Q}s/question).")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- This test runs on a normal 4-core / 8 GB computer, like a "
                 "customer laptop — that is the point: DD must answer in "
                 "seconds on ordinary hardware, not on a GPU server.")
    lines.append("- The fork ignores `enable_thinking: false` and the GGUF "
                 "template has no `/no_think` support, so the model spends "
                 "time on a reasoning trace before answering.")
    lines.append("- This is a test only. It does not change DD, and no "
                 "customer data is involved — the database is 26 made-up "
                 "test invoices.")
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"report written: {OUT_MD}")


if __name__ == "__main__":
    main()

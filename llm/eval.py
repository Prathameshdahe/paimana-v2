"""The assistant's evaluation (docs/AI_ASSISTANT.md): the questions of tests/chat_eval.jsonl run through agent.run
as their role, against the real served data and, for the LLM part, the real LM Studio.

  python -m llm.eval                      every question with the writer off (router + tools + deterministic answer)
  python -m llm.eval --llm subset         the questions marked "llm": true with the real LLM (planner and writer)
  python -m llm.eval --llm all            every question with the real LLM
  python -m llm.eval --only pub-01,min-03 --json out.json

A question: {id, role, ministry?, agency?, question, messages? (earlier turns), project_key?, tools: the tools it
should use (all rounds), route?: the router's own tools when they differ (a question the planner takes over),
checks: [...], llm?}. Its expectations are read from the API at run time as the same viewer (an
in-process TestClient, no lifespan), so they follow the data:
  count          {path, params, field}: the number at field (dotted, camelCase) of GET path; passes when the answer
                 states it or a card carries it (a list's total, a stats row); a zero also as 'no' / 'none'
  top_group      {path, params, field, by?}: the group of GET path's list field with the most projects (or the most
                 of `by`); the answer names it
  first_project  {path, params}: the first item of GET path; the answer or the first projects card names it
  last_completion {key}: the project's latest anticipated completion month; the answer states it
  worst_agency   the shown agency with the largest schedule overrun in /api/agencies/matrix; the answer names it
  mentions / not_mentions {any: [...]}: the answer (or, for not_mentions, anything sent) contains one / none
  card           {type}: a card of that type was sent
Reported: routing accuracy (the router's own calls and second-round tool are exactly the expected tools), tool
accuracy (every expected tool ran, planner and second round included), checks passed by the answer or the cards
(the tools), checks the answer text passes alone (over the questions with a check the text can pass: a card check
has none; this is the measure of the written answers), the LLM's answers accepted by the check (first or second
attempt), the deterministic-answer rate, and the median and 90th percentile of the time to the first card and to
done. The question text is printed with its result; nothing is stored.
"""
import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from backend.access import make_viewer
from backend.main import app
from llm import agent, router

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "tests" / "chat_eval.jsonl"


def load(path: Path = QUESTIONS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def headers(q: dict) -> dict:
    h = {"X-Paimana-Role": q["role"]}
    for f in ("ministry", "agency"):
        if q.get(f):
            h[f"X-Paimana-{f.capitalize()}"] = quote(q[f])
    return h


def _field(d, path: str):
    for part in path.split("."):
        d = d[int(part)] if isinstance(d, list) else d[part]
    return d


def _says(text: str, n) -> bool:
    """The text states the number n (digits, with or without thousands commas)."""
    if isinstance(n, float) and not n.is_integer():
        return f"{n:g}" in text
    n = int(n)
    return any(s in text for s in (str(n), f"{n:,}"))


def _names(text: str, key: str, name: str) -> bool:
    low = text.lower()
    words = [w for w in (name or "").replace("-", " ").split() if len(w) >= 5 and w.isalpha()]
    return key.lower() in low or any(w.lower() in low for w in words[:4])


def expect(api: TestClient, q: dict, check: dict):
    """The value a check compares with, read from the API as the question's viewer."""
    h, kind = headers(q), check["kind"]
    if kind in ("count", "top_group", "first_project"):
        r = api.get(check["path"], params=check.get("params") or {}, headers=h)
        r.raise_for_status()
        body = r.json()
        if kind == "count":
            return _field(body, check["field"])
        if kind == "first_project":
            item = body["items"][0]
            return item["key"], item["name"]
        groups = _field(body, check["field"])
        return max(groups, key=lambda g: (g[check.get("by", "n")] or 0))["name"]
    if kind == "last_completion":
        pts = api.get(f"/api/projects/{check['key']}/timeline", headers=h).json()["points"]
        d = pts[-1]["anticipatedCompletion"]
        return time.strftime("%B %Y", time.strptime(d[:7], "%Y-%m"))
    if kind == "worst_agency":
        pts = [p for p in api.get("/api/agencies/matrix", headers=h).json()["points"]
               if not p["hidden"] and p["scheduleBias"] is not None]
        return max(pts, key=lambda p: p["scheduleBias"])["agency"]
    return None


def judge(check: dict, want, text: str, cards: list[dict], sent: str) -> tuple[bool, bool | None]:
    """(passed by the answer or the cards, passed by the answer text alone: None for a check of the cards only)."""
    kind = check["kind"]
    if kind == "count":
        on_card = any(c.get("total") == want or any(r.get("n") == want for r in c.get("rows") or [])
                      for c in cards)
        none = want == 0 and bool(re.search(r"\bno\b|\bnone\b|\bnot any\b", text, re.I))
        in_text = _says(text, want) or none
        return in_text or on_card, in_text
    if kind == "first_project":
        key, name = want
        first = next((c["items"][0]["key"] for c in cards if c["type"] == "projects" and c["items"]), None)
        in_text = _names(text, key, name)
        return in_text or first == key, in_text
    if kind == "card":
        return any(c["type"] == check["type"] for c in cards), None
    if kind in ("top_group", "last_completion", "worst_agency"):
        ok = want.lower() in text.lower()
    elif kind == "mentions":
        ok = any(w.lower() in text.lower() for w in check["any"])
    elif kind == "not_mentions":
        ok = not any(w.lower() in sent.lower() for w in check["any"])
    else:
        raise ValueError(f"unknown check {kind}")
    return ok, ok


def run_one(api: TestClient, q: dict) -> dict:
    v = make_viewer(q["role"], q.get("ministry"), q.get("agency"))
    messages = list(q.get("messages") or []) + [{"role": "user", "content": q["question"]}]
    route = router.route(v, messages, q.get("project_key"))
    routed = {c["tool"] for c in route.calls} | ({route.detail} if route.detail else set())
    t0, first_card, events = time.monotonic(), None, []
    for ev in agent.run(v, messages, q.get("project_key")):
        if ev["event"] == "card" and first_card is None:
            first_card = time.monotonic() - t0
        events.append(ev)
    t_done = time.monotonic() - t0
    done = next((e["data"] for e in events if e["event"] == "done"), None) or {
        "text": "", "validated": False, "reasons": ["no done event"], "llm": "error"}
    ran = [e["data"]["name"] for e in events if e["event"] == "tool" and e["data"]["status"] == "running"]
    cards = [e["data"] for e in events if e["event"] == "card"]
    sent = json.dumps(events, ensure_ascii=False, default=str)
    checks = []
    for c in q["checks"]:
        want = expect(api, q, c)
        ok, in_text = judge(c, want, done["text"], cards, sent)
        checks.append({"check": c["kind"], "want": want, "ok": ok, "text_ok": in_text})
    by_text = [c["text_ok"] for c in checks if c["text_ok"] is not None]
    expected = set(q["tools"])
    accepted = done["llm"] == "ok" and not done["reasons"]  # the model's own text passed the check
    return {"id": q["id"], "role": q["role"], "question": q["question"], "routed": sorted(routed), "ran": ran,
            "routing_ok": routed == set(q.get("route", q["tools"])), "tools_ok": expected <= set(ran),
            "checks": checks,
            "checks_ok": all(c["ok"] for c in checks), "text_checked": bool(by_text), "text_ok": all(by_text),
            "llm": done["llm"],
            "accepted": accepted, "template": not accepted,
            "retries": sum(e["event"] == "retry" for e in events), "reasons": done["reasons"][:4],
            "retry_reasons": [r for e in events if e["event"] == "retry" for r in e["data"]["reasons"]][:6],
            "first_card_s": first_card, "done_s": t_done, "text": done["text"]}


def _pct(xs: list[float], p: float) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, max(0, round(p * (len(xs) - 1))))] if p != 0.5 else statistics.median(xs)


def summary(results: list[dict], llm: bool) -> dict:
    n = len(results)
    ok = lambda k: sum(r[k] for r in results)  # noqa: E731
    out = {"questions": n, "routing": f"{ok('routing_ok')}/{n}", "tools": f"{ok('tools_ok')}/{n}",
           "checks": f"{ok('checks_ok')}/{n}",
           "text_checks": f"{sum(r['text_ok'] for r in results if r['text_checked'])}/{ok('text_checked')}",
           "first_card_s": (_pct([r["first_card_s"] for r in results], 0.5),
                            _pct([r["first_card_s"] for r in results], 0.9)),
           "done_s": (_pct([r["done_s"] for r in results], 0.5), _pct([r["done_s"] for r in results], 0.9))}
    if llm:  # over the answers the model was asked to write ('skipped': nothing found, the template by design)
        used = [r for r in results if r["llm"] != "skipped"]
        out.update({"accepted": f"{sum(r['accepted'] for r in used)}/{len(used)}",
                    "template": f"{sum(r['template'] for r in used)}/{len(used)}",
                    "retried": f"{sum(r['retries'] > 0 and r['accepted'] for r in used)}/{len(used)}",
                    "llm_states": {s: sum(r["llm"] == s for r in results) for s in
                                   sorted({r["llm"] for r in results})}})
    return out


def table(s: dict) -> str:
    def secs(pair):
        return " / ".join("-" if x is None else f"{x:.1f} s" for x in pair)
    rows = [("Questions", s["questions"]), ("Routing accuracy (router alone)", s["routing"]),
            ("Tool accuracy (all rounds)", s["tools"]), ("Checks passed (answer or cards)", s["checks"]),
            ("Checks the answer text passes alone", s["text_checks"])]
    if "accepted" in s:
        rows += [("Answers the model wrote, accepted by the check", s["accepted"]),
                 ("... after one strict retry", s["retried"]),
                 ("... replaced by the deterministic answer", s["template"]), ("LLM states", s["llm_states"])]
    rows += [("Time to first card, median / p90", secs(s["first_card_s"])),
             ("Time to done, median / p90", secs(s["done_s"]))]
    return "\n".join(["| Metric | Value |", "|---|---|"] + [f"| {a} | {b} |" for a, b in rows])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m llm.eval", description=__doc__.split("\n\n")[0])
    ap.add_argument("--llm", choices=["none", "subset", "all"], default="none",
                    help="none: the writer off; subset: the questions marked llm with LM Studio; all: every one")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--file", type=Path, default=QUESTIONS)
    ap.add_argument("--json", type=Path, help="write every result here")
    args = ap.parse_args(argv)
    qs = load(args.file)
    if args.only:
        qs = [q for q in qs if q["id"] in set(args.only.split(","))]
    elif args.llm == "subset":
        qs = [q for q in qs if q.get("llm")]
    agent.WRITER = args.llm != "none"
    api = TestClient(app)
    results = []
    for q in qs:
        r = run_one(api, q)
        results.append(r)
        mark = "ok " if r["routing_ok"] and r["tools_ok"] and r["checks_ok"] else "BAD"
        print(f"{mark} {r['id']:<8} {r['llm']:<11} card {r['first_card_s'] or 0:5.1f} s  done {r['done_s']:6.1f} s  "
              f"route {'ok' if r['routing_ok'] else r['routed']}  tools {'ok' if r['tools_ok'] else r['ran']}  "
              f"checks {[c['ok'] for c in r['checks']]}"
              + ("" if r["text_ok"] or not r["text_checked"] else "  text BAD")
              + (f"  retries {r['retries']}" if r["retries"] else ""),
              flush=True)
        if mark == "BAD" or r["retries"] or (r["text_checked"] and not r["text_ok"]):
            print(f"      Q: {r['question']}\n      A: {r['text'][:400]}\n"
                  f"      want: {[c['want'] for c in r['checks']]}"
                  + (f"\n      rejected: {r['retry_reasons']}" if r["retry_reasons"] else ""), flush=True)
    s = summary(results, args.llm != "none")
    print("\n" + table(s))
    if args.json:
        args.json.write_text(json.dumps({"summary": s, "results": results}, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

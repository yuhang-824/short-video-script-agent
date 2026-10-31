"""Generate actual per-case inputs, tool observations and editable drafts."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from video_script.agent import run_agent
from video_script.domain import Request
from video_script.model import DeepSeekModel, MockModel, load_env
from video_script.scenarios import CASES, make_request, scenario_catalog, verify_result


def main():
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["mock", "deepseek"], default="mock")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    load_env(ROOT / ".env")
    if args.model == "deepseek": DeepSeekModel()  # fail before writing any real-run evidence
    base = json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8"))
    destination = args.output_dir or ROOT / "examples" / args.model
    rows = []
    for name, case in CASES.items():
        request, catalog = make_request(name), scenario_catalog(base, name)
        model = MockModel() if args.model == "mock" else DeepSeekModel()
        result = run_agent(Request.parse(request), catalog, model, case.get("max_steps", 32))
        directory = destination / name
        directory.mkdir(parents=True, exist_ok=True)
        payloads = {"input.json": request, "data.json": catalog, "output.json": result,
                    "trace.json": result["trace"]}
        if result["editable_draft"]: payloads["editable-script.json"] = result["editable_draft"]
        for filename, value in payloads.items():
            (directory / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            # Exact 38/28 and template-path expectations belong only to deterministic Mock.
            if args.model == "mock": verify_result(name, result)
            else:
                assert result["status"] == case["status"]
                if result["status"] == "completed":
                    assert result["duration_check"]["within_limit"] and result["rule_check"]["passed"]
            passed, error = True, None
        except AssertionError as exc:
            passed, error = False, str(exc) or "business assertion failed"
        rows.append({"case": name, "label": case["label"], "passed": passed, "status": result["status"],
                     "duration_history": [c.get("estimated_total_seconds") for c in result["duration_history"]],
                     "steps": result["steps_taken"], "error": error})
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "mode": args.model,
               "passed": sum(r["passed"] for r in rows), "total": len(rows), "cases": rows,
               "boundary": "Offline Mock results do not prove real-model decisions or creative quality."}
    (destination / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__": raise SystemExit(main())

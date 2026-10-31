"""Copyable CLI; real model failures never fall back to Mock silently."""
import argparse
import json
from pathlib import Path
import sys
from .agent import run_agent
from .domain import Request, digest, validate_catalog
from .model import DeepSeekModel, MockModel, load_env
from .tools import validate_edit


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="短视频脚本 Agent")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path("data/catalog.json"))
    parser.add_argument("--model", choices=["mock", "deepseek"], default="mock")
    parser.add_argument("--max-steps", type=int, default=32)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-script", type=Path, help="独立人工编辑校验，不执行模型循环；输入严格草稿JSON")
    args = parser.parse_args(argv)
    try:
        load_env()
        request = Request.parse(json.loads(args.input.read_text(encoding="utf-8-sig")))
        catalog = validate_catalog(json.loads(args.data.read_text(encoding="utf-8-sig")))
        if args.check_script:
            facts = [{"fact_id": m["id"] + ":" + f["id"], "material_id": m["id"], "text": f["text"],
                      "source_text": m["source_text"], "source_hash": digest(m["source_text"]), "version_date": m["version_date"]}
                     for m in catalog["materials"] if m.get("active", True) for f in m["facts"]]
            result = validate_edit(request, catalog, json.loads(args.check_script.read_text(encoding="utf-8-sig")), facts)
        else:
            result = run_agent(request, catalog, MockModel() if args.model == "mock" else DeepSeekModel(), args.max_steps)
        output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        print(output)
        return 0 if result["status"] in {"completed", "approved"} else 2
    except (ValueError, KeyError, TypeError, OSError):
        print("输入、配置或本地文件无效；真实模型模式需要本地密钥，不会自动转为Mock。", file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())

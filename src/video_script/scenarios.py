"""Synthetic, reproducible fault and counterfactual inputs; not real product claims."""
from copy import deepcopy

BASE_REQUEST = {"request_id": "demo-video", "theme": "字幕创作", "audience": "短视频创作者", "platform": "抖音", "target_seconds": 30, "style": "简洁清晰"}
CASES = {
    "normal": {"label": "正常生成 · 45秒上限", "request": {"target_seconds": 45}, "status": "completed"},
    "duration_revision": {"label": "超时修订 · 38→28秒", "status": "completed"},
    "missing_information": {"label": "缺关键信息 · 目标时长", "request": {"target_seconds": None}, "status": "needs_information"},
    "missing_audience": {"label": "缺受众", "request": {"audience": None}, "status": "needs_information"},
    "missing_style": {"label": "缺风格", "request": {"style": None}, "status": "needs_information"},
    "no_materials": {"label": "无素材 · 补检索后请求资料", "empty": True, "status": "needs_materials"},
    "unrelated_theme": {"label": "资料外主题", "request": {"theme": "月球旅行保险"}, "status": "needs_materials"},
    "query_rewrite": {"label": "查询改写 · 配字→字幕", "request": {"theme": "画面配字"}, "status": "completed"},
    "tool_failure": {"label": "工具失败 · 时长估算", "fail": "estimate_duration", "status": "failed"},
    "search_failure": {"label": "工具失败 · 素材检索", "fail": "search_materials", "status": "failed"},
    "read_failure": {"label": "工具失败 · 原文读取", "fail": "read_material", "status": "failed"},
    "rules_failure": {"label": "工具失败 · 规则检查", "fail": "check_brand_rules", "status": "failed"},
    "rule_revision": {"label": "规则修订 · 去掉禁用表述", "request": {"target_seconds": 45}, "ban": "方便观看", "status": "completed"},
    "unsupported_claim": {"label": "无依据主张 · 拦截80%并修订", "request": {"target_seconds": 60}, "bad_draft": True, "status": "completed"},
    "impossible_duration": {"label": "时长无法满足 · 2秒", "request": {"target_seconds": 2}, "status": "constraints_unmet"},
    "trim_pauses": {"label": "去掉停顿 · 5秒", "request": {"target_seconds": 5}, "status": "completed"},
    "minimal_script": {"label": "最简结构 · 10秒", "request": {"target_seconds": 10}, "status": "completed"},
    "slow_speech": {"label": "变更语速 · 每秒2字", "cps": 2, "status": "completed"},
    "source_changed": {"label": "替换产品事实 · 支持片段裁剪", "source_changed": True, "status": "completed"},
    "rule_unmet": {"label": "规则无法满足 · 禁用字幕", "request": {"target_seconds": 45}, "ban": "字幕", "status": "constraints_unmet"},
    "unsupported_platform": {"label": "不支持的平台", "request": {"platform": "未知平台"}, "status": "needs_information"},
    "step_limit": {"label": "步数上限 · 保留已读素材", "max_steps": 3, "status": "incomplete"},
}


def make_request(name):
    return {**BASE_REQUEST, "request_id": name, **CASES[name].get("request", {})}


def scenario_catalog(base, name):
    case, data = CASES[name], deepcopy(base)
    if case.get("empty"): data["materials"] = []
    if case.get("fail"): data["failures"] = {case["fail"]: {"times": 1}}
    if case.get("ban"): data["rules"]["prohibited_terms"].append(case["ban"])
    if case.get("bad_draft"): data["inject_bad_draft"] = True
    if case.get("cps"): data["rules"]["characters_per_second"] = case["cps"]
    if case.get("source_changed"):
        data["materials"][0]["source_text"] = "产品支持片段裁剪。"
        data["materials"][0]["facts"] = [{"id": "F01", "text": "支持片段裁剪"}]
        data["materials"][0]["version_date"] = "2026-02-01"
    return data


def verify_result(name, result):
    """Business assertions beyond a completed-status check."""
    assert result["status"] == CASES[name]["status"], result["status"]
    assert result["steps_taken"] <= result["max_steps"]
    for current, following in zip(result["trace"], result["trace"][1:]):
        assert current["next_action"] == following.get("tool", "stop:" + following.get("error", ""))
    if result["status"] == "completed":
        final = result["final_script"]
        assert final["approved"] and final["estimated_total_seconds"] <= result["request"]["target_seconds"]
        assert sum(s["estimated_seconds"] for s in final["shot_timings"]) == final["estimated_total_seconds"]
        assert result["rule_check"]["passed"] and result["duration_check"]["within_limit"]
        for c in final["citations"]:
            assert c["text"] in c["source_text"]
            shot = next(s for s in final["shots"] if s["shot_id"] == c["shot_id"])
            assert c["text"] in shot["narration"] or c["text"] in shot["subtitle"]
            assert c["fact_id"] in shot["fact_ids"]
        assert "80%" not in str(final)
    else:
        assert result["final_script"] is None and result["gaps"]
    totals = [x["estimated_total_seconds"] for x in result["duration_history"] if x.get("ok")]
    actions = [x.get("tool") for x in result["trace"]]
    if name == "normal": assert totals == [38] and "revise_script" not in actions
    if name == "duration_revision": assert totals == [38, 28] and len(result["revisions"]) == 2
    if name == "query_rewrite": assert result["searches"][0]["hits"] == [] and result["searches"][1]["hits"]
    if name in {"no_materials", "unrelated_theme"}: assert len(result["searches"]) == 2
    if name == "rule_revision": assert [x["passed"] for x in result["rule_history"]] == [False, True]
    if name == "unsupported_claim": assert any(r["code"] == "claim_text_not_supported" for r in result["rule_history"][0]["risks"])
    if name == "impossible_duration": assert totals[-1] > 2 and result["editable_draft"]
    if name == "trim_pauses": assert totals[-1] == 5
    if name == "source_changed": assert "支持片段裁剪" in str(result["final_script"]) and "支持字幕" not in str(result["final_script"])
    if name == "step_limit": assert result["stop_reason"] == "step_limit_reached" and result["materials_read"]
    if "failure" in name: assert result["tool_errors"]

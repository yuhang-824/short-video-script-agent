"""Constrained editable drafts; duration is calculated from actual draft text."""
from copy import deepcopy
import math
import re
from .domain import digest

VISUALS = {"title_card": "展示主题标题卡片", "intro_card": "切换至功能介绍文字卡",
           "fact_card": "用文字卡展示已核实的产品事实", "cta_card": "切换至创作邀请文字卡"}
COPY = {
    "detailed_hook": "想让你的视频更方便观看吗",
    "detailed_intro": "这次只介绍素材中已确认的功能",
    "detailed_cta": "选择适合自己的表达方式开始创作",
    "compact_hook": "用字幕表达你的内容",
    "generic_hook": "从一个创作灵感开始",
    "compact_intro": "先看这项已确认的功能",
    "compact_cta": "用自己的内容试试吧",
    "minimal_hook": "一起看个创作灵感",
    "minimal_cta": "现在开始创作吧",
}
PROFILES = ("detailed", "compact", "minimal")


def make_draft(request, facts, profile, revision):
    has_subtitles = any("字幕" in f["text"] for f in facts)
    title = "字幕创作小灵感" if has_subtitles else "视频创作小灵感"
    if profile == "detailed":
        spec = [("title_card", COPY["detailed_hook"], 6), ("intro_card", COPY["detailed_intro"], 7),
                ("fact_card", None, 6), ("cta_card", COPY["detailed_cta"], 7)]
    elif profile == "compact":
        spec = [("title_card", COPY["compact_hook"] if has_subtitles else COPY["generic_hook"], 4),
                ("intro_card", COPY["compact_intro"], 5), ("fact_card", None, 4), ("cta_card", COPY["compact_cta"], 5)]
    else:
        spec = [("title_card", COPY["minimal_hook"], 1), ("fact_card", None, 1), ("cta_card", COPY["minimal_cta"], 1)]
    shots = []
    for index, (visual, text, hold) in enumerate(spec, 1):
        ids = [f["fact_id"] for f in facts] if text is None else []
        narration = "；".join(f["text"] for f in facts) if text is None else text
        shots.append({"shot_id": f"S{index:02d}", "visual_type": visual, "visual": VISUALS[visual],
                      "narration": narration, "subtitle": narration, "hold_seconds": hold,
                      "fact_ids": ids})
    return {"title": title, "profile": profile, "revision": revision,
            "audience": request.audience, "platform": request.platform, "style": request.style, "shots": shots}


def shape_errors(draft):
    if not isinstance(draft, dict) or set(draft) != {"title", "profile", "revision", "audience", "platform", "style", "shots"}:
        return ["invalid_script_shape"]
    if any(not isinstance(draft[k], str) or not draft[k].strip() or len(draft[k]) > 1000
           for k in ("title", "profile", "audience", "platform", "style")):
        return ["invalid_script_text"]
    if type(draft["revision"]) is not int or draft["revision"] < 1:
        return ["invalid_revision"]
    shots = draft["shots"]
    if not isinstance(shots, list) or not 3 <= len(shots) <= 8:
        return ["script_requires_3_to_8_shots"]
    seen = set()
    for shot in shots:
        if not isinstance(shot, dict) or set(shot) != {"shot_id", "visual_type", "visual", "narration", "subtitle", "hold_seconds", "fact_ids"}:
            return ["invalid_shot_shape"]
        if not isinstance(shot["shot_id"], str) or not re.fullmatch(r"S\d{2}", shot["shot_id"]) or shot["shot_id"] in seen:
            return ["invalid_or_duplicate_shot_id"]
        seen.add(shot["shot_id"])
        if not isinstance(shot["visual_type"], str) or shot["visual_type"] not in VISUALS or any(not isinstance(shot[k], str) or len(shot[k]) > 1000 for k in ("visual", "narration", "subtitle")):
            return ["invalid_shot_text"]
        if not shot["narration"].strip() and not shot["subtitle"].strip(): return ["shot_requires_narration_or_subtitle"]
        if type(shot["hold_seconds"]) is not int or not 0 <= shot["hold_seconds"] <= 60:
            return ["hold_seconds_must_be_integer_0_to_60"]
        ids = shot["fact_ids"]
        if not isinstance(ids, list) or len(ids) > 5 or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
            return ["invalid_fact_ids"]
    return []


def char_count(text):
    return len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text))


def estimate(draft, request, rules):
    errors = shape_errors(draft)
    if errors: return {"ok": False, "error": "invalid_script", "details": errors}
    shots = []
    for shot in draft["shots"]:
        chars = max(char_count(shot["narration"]), char_count(shot["subtitle"]),
                    char_count(draft["title"]) if shot["visual_type"] == "title_card" else 0)
        speech = math.ceil(chars / rules["characters_per_second"])
        total = max(speech, rules["min_scene_seconds"]) + shot["hold_seconds"]
        shots.append({"shot_id": shot["shot_id"], "readable_characters": chars, "speech_seconds": speech,
                      "hold_seconds": shot["hold_seconds"], "estimated_seconds": total})
    total = sum(s["estimated_seconds"] for s in shots)
    return {"ok": True, "draft_digest": digest(draft), "revision": draft["revision"],
            "estimated_total_seconds": total, "target_seconds": request.target_seconds,
            "within_limit": request.target_seconds is not None and total <= request.target_seconds,
            "over_seconds": max(0, total - request.target_seconds) if request.target_seconds is not None else None,
            "characters_per_second": rules["characters_per_second"], "shots": shots,
            "semantics": "max(narration/subtitle/title character time, visual minimum) + hold; approximate, not rendered video"}


def check_rules(draft, request, rules, facts):
    errors = shape_errors(draft)
    risks, citations = [], []
    if errors: return {"ok": True, "passed": False, "risks": [{"code": e} for e in errors], "citations": [], "draft_digest": digest(draft)}
    inventory = {fact["fact_id"]: fact for fact in facts}
    if request.missing(): risks.append({"code": "missing_required_input", "fields": request.missing()})
    if request.platform not in rules["platforms"]: risks.append({"code": "unsupported_platform"})
    for field in ("audience", "platform", "style"):
        if draft[field] != getattr(request, field): risks.append({"code": "changed_user_requirement", "field": field})
    has_subtitles = any("字幕" in f["text"] for f in facts)
    allowed_titles = {"视频创作小灵感"} | ({"字幕创作小灵感"} if has_subtitles else set())
    if draft["title"] not in allowed_titles: risks.append({"code": "unverified_title", "field": "title"})
    combined = draft["title"] + " " + " ".join(s["narration"] + " " + s["subtitle"] + " " + s["visual"] for s in draft["shots"])
    for term in rules["prohibited_terms"]:
        if term.casefold() in combined.casefold(): risks.append({"code": "brand_prohibited_term", "term": term})
    grounded = False
    for shot in draft["shots"]:
        sid, ids = shot["shot_id"], shot["fact_ids"]
        if shot["visual"] != VISUALS[shot["visual_type"]]: risks.append({"code": "unverified_visual", "shot_id": sid})
        unknown = [fact_id for fact_id in ids if fact_id not in inventory]
        if unknown:
            risks.append({"code": "unknown_fact_reference", "shot_id": sid, "fact_ids": unknown})
            continue
        expected = "；".join(inventory[f]["text"] for f in ids)
        for field in ("narration", "subtitle"):
            text = shot[field]
            if not text: continue
            if ids:
                if text != expected: risks.append({"code": "claim_text_not_supported", "shot_id": sid, "field": field})
            elif text not in set(COPY.values()) or (text == COPY["compact_hook"] and not has_subtitles):
                risks.append({"code": "unverified_copy", "shot_id": sid, "field": field})
        if ids:
            grounded = True
            for fact_id in ids:
                f = inventory[fact_id]
                citations.append({"shot_id": sid, **deepcopy(f)})
    if not grounded: risks.append({"code": "no_grounded_product_fact"})
    return {"ok": True, "passed": not risks, "revision": draft["revision"], "draft_digest": digest(draft),
            "rules_version": rules["version"], "risks": risks, "citations": citations,
            "boundary": "strict known-neutral-copy and verbatim supported-fact validation; not general semantic entailment"}

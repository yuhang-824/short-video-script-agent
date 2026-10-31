"""Model-selected actions with authoritative provenance and revision checks."""
from copy import deepcopy
from .domain import digest
from .drafting import PROFILES, make_draft, estimate, check_rules


def schema(name, description, extra=None):
    props = {"reason": {"type": "string", "description": "一句基于可见工具结果的动作依据，不提供内部思维过程。"}}
    props.update(extra or {})
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}}}


SCHEMAS = [
    schema("inspect_request", "核对主题、受众、平台、目标时长与风格，缺少信息时不能自行补全。"),
    schema("search_materials", "检索素材索引；无结果可改写或使用expanded扩展术语，不能虚构素材。",
           {"query": {"type": "string"}, "strategy": {"type": "string", "enum": ["keyword", "expanded"]}}),
    schema("read_material", "读取已检索素材的原文和事实ID，产品主张只能来自已读事实。",
           {"material_id": {"type": "string"}}),
    schema("draft_script", "按所选事实生成有分镜、旁白和字幕的可编辑草稿；必须再检查时长和规则。",
           {"profile": {"type": "string", "enum": list(PROFILES)},
            "fact_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3}}),
    schema("revise_script", "根据检查结果修订：compress换更短结构；trim_pauses去掉停顿；safe_copy重建安全精简文案。旧检查失效。",
           {"mode": {"type": "string", "enum": ["compress", "trim_pauses", "safe_copy"]}}),
    schema("estimate_duration", "从实际文字、最低画面时间和停顿逐镜估算，不使用预设总时长。"),
    schema("check_brand_rules", "检查所有主张、字幕、标题、画面和素材ID，以及品牌禁用词。"),
    schema("finish", "只有当前草稿的时长和规则检查均通过后才能交付通过脚本。"),
    schema("request_information", "请求关键输入或素材补充；返回缺口并结束本轮。",
           {"kind": {"type": "string", "enum": ["missing_input", "missing_materials"]}}),
    schema("stop", "工具失败或已尝试修订仍无法满足时明确停止，保留草稿和检查，不伪报完成。",
           {"outcome": {"type": "string", "enum": ["tool_failure", "duration_unmet", "rules_unmet"]}}),
]


class Tools:
    def __init__(self, request, catalog):
        self.request, self.catalog = request, deepcopy(catalog)
        self.discovered, self.reads, self.searches = {}, {}, []
        self.fact_inventory = {}
        self.revisions, self.duration_history, self.rule_history = [], [], []
        self.draft, self.duration, self.rule_check = None, None, None
        self.errors, self.fail_counts = [], {}
        self.terminal = None
        self.final_script = None

    def execute(self, name, args):
        spec = next((x["function"]["parameters"] for x in SCHEMAS if x["function"]["name"] == name), None)
        if spec is None: return {"ok": False, "error": "unknown_tool"}
        if not isinstance(args, dict) or set(args) != set(spec["required"]): return {"ok": False, "error": "invalid_arguments"}
        for key, value in args.items():
            field = spec["properties"][key]
            if field["type"] == "string" and (not isinstance(value, str) or not value.strip() or len(value) > 2000): return {"ok": False, "error": "invalid_arguments"}
            if "enum" in field and value not in field["enum"]: return {"ok": False, "error": "invalid_arguments"}
            if field["type"] == "array" and (not isinstance(value, list) or not 1 <= len(value) <= 3 or any(not isinstance(x, str) for x in value) or len(set(value)) != len(value)):
                return {"ok": False, "error": "invalid_arguments"}
        if self.terminal: return {"ok": False, "error": "task_already_ended"}
        return getattr(self, name)(**{key: value for key, value in args.items() if key != "reason"})

    def missing(self):
        fields = self.request.missing()
        if self.request.platform is not None and self.request.platform not in self.catalog["rules"]["platforms"]:
            fields += ["supported_platform"]
        return fields

    def _fail(self, name, material_id=None):
        rule = self.catalog.get("failures", {}).get(name, {"times": 0})
        key = name + ":" + str(material_id)
        if self.fail_counts.get(key, 0) < rule["times"] and (material_id is None or material_id in rule.get("material_ids", [material_id])):
            self.fail_counts[key] = self.fail_counts.get(key, 0) + 1
            self.errors.append({"tool": name, "material_id": material_id, "error": "injected_tool_failure"})
            return True
        return False

    def inspect_request(self):
        return {"ok": True, "request": self.request.as_dict(), "missing_fields": self.missing(),
                "supported_platforms": self.catalog["rules"]["platforms"], "profiles": list(PROFILES),
                "target_semantics": "estimated total must not exceed target; not exact rendered-video length"}

    def search_materials(self, query, strategy):
        if self._fail("search_materials"): return {"ok": False, "error": "search_failed"}
        if self.missing(): return {"ok": False, "error": "missing_input", "fields": self.missing()}
        effective = query
        if strategy == "expanded" and any(t in (self.request.theme or "") for t in ("字幕", "配字", "画面文字", "屏幕文字", "台词卡")):
            effective = query + " 字幕"
        hits = []
        for material in self.catalog["materials"]:
            if material.get("active", True) and any(k.casefold() in effective.casefold() for k in material["keywords"]):
                hit = {"material_id": material["id"], "title": material["title"], "version_date": material["version_date"],
                       "fact_ids": [material["id"] + ":" + f["id"] for f in material["facts"]]}
                hits.append(hit)
                self.discovered[material["id"]] = hit
        result = {"query": query, "strategy": strategy, "effective_query": effective, "hits": hits}
        self.searches.append(deepcopy(result))
        return {"ok": True, **result}

    def read_material(self, material_id):
        if material_id not in self.discovered: return {"ok": False, "error": "search_material_first"}
        if self._fail("read_material", material_id): return {"ok": False, "error": "read_failed"}
        material = next(m for m in self.catalog["materials"] if m["id"] == material_id)
        facts = [{"fact_id": material_id + ":" + f["id"], "material_id": material_id, "text": f["text"],
                  "source_text": material["source_text"], "source_hash": digest(material["source_text"]),
                  "version_date": material["version_date"]} for f in material["facts"]]
        self.fact_inventory.update({f["fact_id"]: f for f in facts})
        self.reads[material_id] = {"material_id": material_id, "title": material["title"],
                                   "source_text": material["source_text"], "facts": facts}
        return {"ok": True, "material": deepcopy(self.reads[material_id])}

    def _install(self, draft, operation):
        self.draft = draft
        self.duration, self.rule_check = None, None
        self.revisions.append({"operation": operation, "draft": deepcopy(draft), "draft_digest": digest(draft)})
        return {"ok": True, "draft": deepcopy(draft), "draft_digest": digest(draft), "checks_invalidated": True}

    def draft_script(self, profile, fact_ids):
        if self.missing(): return {"ok": False, "error": "missing_input", "fields": self.missing()}
        if any(f not in self.fact_inventory for f in fact_ids): return {"ok": False, "error": "read_supported_fact_first"}
        if self._fail("draft_script"): return {"ok": False, "error": "draft_failed"}
        draft = make_draft(self.request, [self.fact_inventory[f] for f in fact_ids], profile, len(self.revisions) + 1)
        if self.catalog.get("inject_bad_draft") and not self.revisions:
            shot = next(s for s in draft["shots"] if s["fact_ids"])
            shot["narration"] += "，效率提升80%"
            shot["subtitle"] = shot["narration"]
        return self._install(draft, "draft_script")

    def revise_script(self, mode):
        if self.draft is None: return {"ok": False, "error": "draft_first"}
        if self._fail("revise_script"): return {"ok": False, "error": "revision_failed"}
        ids = list(dict.fromkeys(f for s in self.draft["shots"] for f in s["fact_ids"]))
        if not ids or any(f not in self.fact_inventory for f in ids): return {"ok": False, "error": "read_supported_fact_first"}
        if mode == "trim_pauses":
            draft = deepcopy(self.draft)
            for shot in draft["shots"]: shot["hold_seconds"] = 0
            draft["revision"] = len(self.revisions) + 1
        else:
            index = PROFILES.index(self.draft["profile"])
            if mode == "compress" and index == len(PROFILES) - 1: return {"ok": False, "error": "no_shorter_profile_try_trim"}
            profile = PROFILES[min(index + 1, len(PROFILES) - 1)]
            draft = make_draft(self.request, [self.fact_inventory[f] for f in ids], profile, len(self.revisions) + 1)
        return self._install(draft, "revise_script:" + mode)

    def estimate_duration(self):
        if self.draft is None: return {"ok": False, "error": "draft_first"}
        if self._fail("estimate_duration"): return {"ok": False, "error": "duration_tool_failed"}
        self.duration = estimate(self.draft, self.request, self.catalog["rules"])
        self.duration_history.append(deepcopy(self.duration))
        return deepcopy(self.duration)

    def check_brand_rules(self):
        if self.draft is None: return {"ok": False, "error": "draft_first"}
        if self._fail("check_brand_rules"): return {"ok": False, "error": "rules_tool_failed"}
        self.rule_check = check_rules(self.draft, self.request, self.catalog["rules"], list(self.fact_inventory.values()))
        self.rule_history.append(deepcopy(self.rule_check))
        return deepcopy(self.rule_check)

    def finish(self):
        if self.draft is None or self.duration is None or self.rule_check is None:
            return {"ok": False, "error": "current_duration_and_rules_checks_required"}
        if any(check["draft_digest"] != digest(self.draft) for check in (self.duration, self.rule_check)):
            return {"ok": False, "error": "stale_checks"}
        if not self.duration.get("within_limit") or not self.rule_check["passed"]:
            return {"ok": False, "error": "checks_not_passed"}
        self.final_script = {**deepcopy(self.draft), "approved": True,
                             "estimated_total_seconds": self.duration["estimated_total_seconds"],
                             "target_seconds": self.request.target_seconds,
                             "source_ids": sorted({c["material_id"] for c in self.rule_check["citations"]}),
                             "citations": deepcopy(self.rule_check["citations"]),
                             "shot_timings": deepcopy(self.duration["shots"])}
        self.terminal = {"status": "completed", "gaps": [], "message": "当前脚本的预计时长与规则检查均通过。"}
        return {"ok": True, "status": "completed", "final_script": deepcopy(self.final_script)}

    def request_information(self, kind):
        if kind == "missing_input":
            if not self.missing(): return {"ok": False, "error": "missing_input_requires_evidence"}
            self.terminal = {"status": "needs_information", "gaps": self.missing(), "message": "请补充关键输入或选择支持的平台。"}
        else:
            if self.fact_inventory or not {"keyword", "expanded"} <= {s["strategy"] for s in self.searches}:
                return {"ok": False, "error": "supplement_search_before_requesting_materials"}
            self.terminal = {"status": "needs_materials", "gaps": ["需要与主题相关、可核验的产品素材。"], "message": "补充检索后仍没有可用事实，不生成虚构产品主张。"}
        return {"ok": True, **deepcopy(self.terminal)}

    def stop(self, outcome):
        if outcome == "tool_failure":
            if not self.errors: return {"ok": False, "error": "tool_failure_requires_evidence"}
            status, gaps = "failed", ["需要恢复失败工具并重新核验草稿。"]
        elif outcome == "duration_unmet":
            if not self.duration or self.duration.get("within_limit"): return {"ok": False, "error": "duration_failure_requires_evidence"}
            if self.draft["profile"] != "minimal": return {"ok": False, "error": "try_shorter_profile_first"}
            if any(s["hold_seconds"] for s in self.draft["shots"]): return {"ok": False, "error": "trim_pauses_first"}
            status, gaps = "constraints_unmet", ["提供的最短结构仍超出预计时长限制，缺口" + str(self.duration["over_seconds"]) + "秒。"]
        else:
            if not self.rule_check or self.rule_check["passed"]: return {"ok": False, "error": "rules_failure_requires_evidence"}
            if self.draft["profile"] != "minimal": return {"ok": False, "error": "try_safe_revision_first"}
            status, gaps = "constraints_unmet", ["修订后仍不符合品牌或事实规则，需要补充素材或人工调整。"]
        self.terminal = {"status": status, "gaps": gaps, "message": "未交付通过脚本；已有草稿与实际检查结果保留。"}
        return {"ok": True, **deepcopy(self.terminal)}

    def report(self):
        return {"request": self.request.as_dict(), "missing_fields": self.missing(),
                "searches": self.searches, "materials_read": list(self.reads.values()),
                "fact_inventory": list(self.fact_inventory.values()), "revisions": self.revisions,
                "editable_draft": deepcopy(self.draft), "duration_check": self.duration, "rule_check": self.rule_check,
                "duration_history": self.duration_history, "rule_history": self.rule_history,
                "final_script": self.final_script, "tool_errors": self.errors,
                **(self.terminal or {"status": "incomplete", "gaps": ["本轮尚未完成所有检查。"], "message": "未形成可交付的通过脚本。"})}


def validate_edit(request, catalog, draft, facts):
    duration = estimate(draft, request, catalog["rules"])
    rule_check = check_rules(draft, request, catalog["rules"], facts)
    approved = duration.get("within_limit", False) and rule_check["passed"]
    return {"execution_mode": "manual_validation", "status": "approved" if approved else "rejected", "approved": approved,
            "script": deepcopy(draft), "duration_check": duration, "rule_check": rule_check}

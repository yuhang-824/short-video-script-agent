from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from video_script.agent import run_agent
from video_script.domain import Request, digest, validate_catalog
from video_script.drafting import estimate, check_rules
from video_script.model import MockModel, DeepSeekModel, ModelError, Decision
from video_script.scenarios import CASES, make_request, scenario_catalog, verify_result
from video_script.tools import Tools, validate_edit

BASE = json.loads((Path(__file__).resolve().parents[1] / "data/catalog.json").read_text(encoding="utf-8"))


def run(name="duration_revision", model=None):
    return run_agent(Request.parse(make_request(name)), scenario_catalog(BASE, name), model or MockModel(), CASES[name].get("max_steps", 32))


class Scenarios(unittest.TestCase):
    pass


def scenario_test(name):
    def test(self): verify_result(name, run(name))
    return test


for name in CASES: setattr(Scenarios, "test_" + name, scenario_test(name))


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.request = Request.parse(make_request("duration_revision"))
        self.result = run()
        self.draft = deepcopy(self.result["editable_draft"])
        self.facts = deepcopy(self.result["fact_inventory"])

    def validate(self): return validate_edit(self.request, BASE, self.draft, self.facts)

    def test_current_script_approved(self): self.assertTrue(self.validate()["approved"])

    def test_duration_is_sum_not_scenario_constant(self):
        self.draft["shots"][0]["hold_seconds"] += 2
        result = self.validate()
        self.assertEqual(result["duration_check"]["estimated_total_seconds"], 30)
        self.assertTrue(result["approved"])

    def test_manual_duration_over_limit(self):
        self.draft["shots"][0]["hold_seconds"] += 3
        result = self.validate()
        self.assertEqual(result["duration_check"]["estimated_total_seconds"], 31)
        self.assertFalse(result["approved"])

    def test_forged_fact_with_valid_id_is_rejected(self):
        self.draft["shots"][2]["narration"] = "效率提升80%"
        codes = [r["code"] for r in self.validate()["rule_check"]["risks"]]
        self.assertIn("claim_text_not_supported", codes)
        self.assertIn("brand_prohibited_term", codes)

    def test_subtitle_is_separately_checked(self):
        self.draft["shots"][2]["subtitle"] = "自动识别语音"
        self.assertFalse(self.validate()["approved"])

    def test_false_title_rejected(self):
        self.draft["title"] = "效率提升80%"
        self.assertFalse(self.validate()["approved"])

    def test_false_visual_rejected(self):
        self.draft["shots"][0]["visual"] = "展示自动识别全部语音"
        self.assertFalse(self.validate()["approved"])

    def test_unknown_fact_reference_rejected(self):
        self.draft["shots"][2]["fact_ids"] = ["P99:F01"]
        self.assertFalse(self.validate()["approved"])

    def test_empty_product_facts_rejected(self):
        for shot in self.draft["shots"]:
            shot["fact_ids"] = []
            shot["narration"] = shot["subtitle"] = "用自己的内容试试吧"
        self.assertFalse(self.validate()["approved"])

    def test_changed_platform_rejected(self):
        self.draft["platform"] = "小红书"
        self.assertFalse(self.validate()["approved"])

    def test_invalid_shot_type_returns_rejection(self):
        self.draft["shots"][0]["visual_type"] = []
        self.assertFalse(self.validate()["approved"])

    def test_target_cannot_be_inserted_in_script(self):
        self.draft["target_seconds"] = 180
        self.assertFalse(self.validate()["approved"])

    def test_boolean_hold_is_invalid(self):
        self.draft["shots"][0]["hold_seconds"] = True
        self.assertFalse(self.validate()["approved"])

    def test_new_creative_copy_needs_review(self):
        self.draft["shots"][0]["narration"] = "一个新写的中性开头"
        self.assertIn("unverified_copy", [r["code"] for r in self.validate()["rule_check"]["risks"]])

    def test_duplicate_shot_id_rejected(self):
        self.draft["shots"][1]["shot_id"] = self.draft["shots"][0]["shot_id"]
        self.assertFalse(self.validate()["approved"])

    def test_same_characters_longer_duration_under_slower_rate(self):
        rules = deepcopy(BASE["rules"])
        rules["characters_per_second"] = 2
        self.assertGreater(estimate(self.draft, self.request, rules)["estimated_total_seconds"], 28)

    def test_modified_source_invalidates_old_fact_claim(self):
        self.facts[0]["text"] = "支持片段裁剪"
        self.assertFalse(self.validate()["approved"])

    def test_trace_uses_actual_observation_and_next_action(self):
        step = next(x for x in self.result["trace"] if x.get("tool") == "estimate_duration")
        self.assertEqual(step["observation"]["estimated_total_seconds"], 38)
        self.assertEqual(step["next_action"], "revise_script")
        self.assertEqual(self.result["execution_mode"], "mock")

    def test_malformed_input_rejected(self):
        for changes in ({"target_seconds": True}, {"target_seconds": 30.5}, {"target_seconds": 0}, {"unexpected": "x"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): Request.parse({**make_request("normal"), **changes})

    def test_catalog_fact_must_appear_in_source(self):
        data = deepcopy(BASE)
        data["materials"][0]["facts"][0]["text"] = "效率提升80%"
        with self.assertRaises(ValueError): validate_catalog(data)

    def test_no_real_key_does_not_create_mock(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}), self.assertRaises(ValueError): DeepSeekModel()

    def test_model_error_retains_incomplete_state(self):
        class Broken(MockModel):
            def decide(self, messages, schemas): raise ModelError("model_network_or_timeout_error")
        result = run(model=Broken())
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["stop_reason"], "model_network_or_timeout_error")
        self.assertIsNone(result["final_script"])

    def test_malicious_repeated_finish_is_bounded(self):
        class Premature(MockModel):
            def decide(self, messages, schemas): return Decision("finish", {"reason": "测试提前结束"}, "x")
        result = run_agent(self.request, BASE, Premature(), 4)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["steps_taken"], 4)
        self.assertIsNone(result["final_script"])


class ToolGuards(unittest.TestCase):
    def setUp(self):
        self.tools = Tools(Request.parse(make_request("normal")), BASE)

    def prepare(self):
        self.tools.search_materials("字幕", "keyword")
        self.tools.read_material("P01")
        self.tools.draft_script("detailed", ["P01:F01"])

    def test_read_must_follow_search(self): self.assertFalse(self.tools.read_material("P01")["ok"])
    def test_draft_must_follow_read(self): self.assertFalse(self.tools.draft_script("detailed", ["P01:F01"])["ok"])
    def test_finish_requires_both_checks(self):
        self.prepare()
        self.tools.estimate_duration()
        self.assertFalse(self.tools.finish()["ok"])

    def test_revision_invalidates_both_checks(self):
        self.prepare()
        self.tools.estimate_duration()
        self.tools.check_brand_rules()
        self.tools.revise_script("compress")
        self.assertIsNone(self.tools.duration)
        self.assertIsNone(self.tools.rule_check)
        self.assertFalse(self.tools.finish()["ok"])

    def test_stale_checks_cannot_finish(self):
        self.prepare()
        self.tools.estimate_duration()
        self.tools.check_brand_rules()
        self.tools.draft["shots"][0]["hold_seconds"] += 1
        self.assertEqual(self.tools.finish()["error"], "stale_checks")

    def test_cannot_claim_tool_failure_without_error(self): self.assertFalse(self.tools.stop("tool_failure")["ok"])
    def test_cannot_request_missing_materials_without_supplement_search(self):
        self.assertFalse(self.tools.request_information("missing_materials")["ok"])
    def test_unknown_tools_and_arguments_rejected(self):
        self.assertFalse(self.tools.execute("publish", {"reason": "x"})["ok"])
        self.assertFalse(self.tools.execute("finish", {"reason": "x", "approved": True})["ok"])
    def test_duplicate_fact_arguments_rejected(self):
        self.assertFalse(self.tools.execute("draft_script", {"reason": "x", "profile": "compact", "fact_ids": ["P01:F01", "P01:F01"]})["ok"])


if __name__ == "__main__": unittest.main()

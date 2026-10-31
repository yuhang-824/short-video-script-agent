from copy import deepcopy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from video_script.scenarios import make_request
from video_script.web import Application, make_server

BASE = Path(__file__).resolve().parents[1] / "data/catalog.json"


class Web(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.temp.name) / "catalog.json"
        cls.data.write_bytes(BASE.read_bytes())
        cls.app = Application(cls.data, Path(cls.temp.name) / "state")
        cls.server = make_server(cls.app, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    def call(self, method, path, value=None, extra=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json", **(extra or {})}
        connection.request(method, path, body=json.dumps(value, ensure_ascii=False).encode() if value is not None else None, headers=headers)
        response = connection.getresponse()
        data = response.read()
        code = response.status
        connection.close()
        return code, data

    def run_case(self, name="duration_revision"):
        code, body = self.call("POST", "/api/run", {"case": name, "request": make_request(name), "max_steps": 32})
        self.assertEqual(code, 200)
        return json.loads(body)

    def test_config_and_static_assets(self):
        for path in ("/", "/assets/app.js", "/assets/app.css", "/api/config"):
            with self.subTest(path=path): self.assertEqual(self.call("GET", path)[0], 200)

    def test_real_run_roundtrip_and_history(self):
        saved = self.run_case()
        self.assertEqual(saved["result"]["duration_check"]["estimated_total_seconds"], 28)
        code, body = self.call("GET", "/api/results/" + saved["run_id"])
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), saved)
        self.assertIn(saved["run_id"], self.call("GET", "/api/history")[1].decode())

    def test_edit_unverified_claim_rejected_on_server(self):
        saved = self.run_case()
        draft = saved["result"]["editable_draft"]
        draft["shots"][2]["narration"] = "支持字幕，效率提升80%"
        code, body = self.call("POST", "/api/check_edit", {"run_id": saved["run_id"], "script": draft})
        self.assertEqual(code, 200)
        validation = json.loads(body)["validation"]
        self.assertFalse(validation["approved"])
        self.assertEqual(validation["execution_mode"], "manual_validation")

    def test_edit_recomputed_and_stored_separately(self):
        saved = self.run_case()
        draft = deepcopy(saved["result"]["editable_draft"])
        draft["shots"][0]["hold_seconds"] = 6
        _, body = self.call("POST", "/api/check_edit", {"run_id": saved["run_id"], "script": draft})
        edited = json.loads(body)
        self.assertTrue(edited["validation"]["approved"])
        self.assertEqual(edited["validation"]["duration_check"]["estimated_total_seconds"], 30)
        self.assertTrue((self.app.edits / (edited["edit_id"] + ".json")).is_file())
        self.assertEqual(json.loads(self.call("GET", "/api/results/" + saved["run_id"])[1]), saved)

    def test_edit_duration_rejected(self):
        saved = self.run_case()
        draft = saved["result"]["editable_draft"]
        draft["shots"][0]["hold_seconds"] = 7
        code, body = self.call("POST", "/api/check_edit", {"run_id": saved["run_id"], "script": draft})
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)["validation"]["approved"])

    def test_changed_catalog_requires_new_generation(self):
        saved = self.run_case()
        original = self.data.read_bytes()
        data = json.loads(original)
        data["rules"]["characters_per_second"] = 2
        try:
            self.data.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(self.call("POST", "/api/check_edit", {"run_id": saved["run_id"], "script": saved["result"]["editable_draft"]})[0], 400)
        finally: self.data.write_bytes(original)

    def test_no_materials_exposes_gap(self):
        result = self.run_case("no_materials")["result"]
        self.assertEqual(result["status"], "needs_materials")
        self.assertIsNone(result["editable_draft"])

    def test_tool_failure_not_success(self):
        result = self.run_case("tool_failure")["result"]
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["final_script"])

    def test_cannot_override_request_via_edit(self):
        saved = self.run_case()
        self.assertEqual(self.call("POST", "/api/check_edit", {"run_id": saved["run_id"], "script": saved["result"]["editable_draft"], "request": {"target_seconds": 180}})[0], 400)

    def test_only_loopback_host(self): self.assertEqual(self.call("GET", "/api/config", extra={"Host":"evil.example"})[0], 421)
    def test_no_cross_origin_execution(self): self.assertEqual(self.call("POST", "/api/run", {}, {"Origin":"https://evil.example"})[0], 403)
    def test_no_env_or_path_traversal(self):
        for path in ("/.env", "/../.env", "/api/results/../../.env"):
            with self.subTest(path=path): self.assertEqual(self.call("GET", path)[0], 404)
    def test_bad_run_id_rejected(self): self.assertEqual(self.call("POST", "/api/check_edit", {"run_id":"../../secret", "script":{}})[0], 400)


if __name__ == "__main__": unittest.main()

"""Provider-shaped HTTP fixtures test transport only; no real model is called."""
import http.client
import io
import json
import os
import unittest
from unittest.mock import patch
import urllib.error
from video_script.model import DeepSeekModel, ModelError
from video_script.tools import SCHEMAS


class Transport(unittest.TestCase):
    def response(self, *, calls=None, finish_reason="tool_calls"):
        return io.BytesIO(json.dumps({"model":"fixture-provider", "choices":[{"finish_reason":finish_reason,"message":{"tool_calls": calls if calls is not None else [{"id":"fixture1","type":"function","function":{"name":"estimate_duration","arguments":"{\"reason\":\"check the current revision\"}"}}]}}],"usage":{"prompt_tokens":5,"completion_tokens":7}}).encode())

    def test_openai_compatible_call_and_observation_roundtrip(self):
        messages = [{"role":"user","content":"request"},{"role":"assistant","content":None,"tool_calls":[{"id":"previous","type":"function","function":{"name":"inspect_request","arguments":"{\"reason\":\"inspect\"}"}}]},{"role":"tool","tool_call_id":"previous","content":"{\"ok\":true}"}]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY":"fixture-not-real"}), patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = self.response()
            model = DeepSeekModel()
            decision = model.decide(messages, SCHEMAS)
            sent = json.loads(factory.return_value.open.call_args.args[0].data)
            self.assertEqual(sent["messages"], messages)
            self.assertEqual(sent["tools"], SCHEMAS)
            self.assertEqual(sent["thinking"], {"type":"disabled"})
            self.assertEqual(decision.name, "estimate_duration")
            self.assertEqual(model.usage, {"prompt_tokens":5,"completion_tokens":7})

    def test_http_failure_does_not_echo_provider_body(self):
        failure = urllib.error.HTTPError("https://api.deepseek.com/chat/completions", 401, "provider secret", {}, io.BytesIO(b"private body"))
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY":"fixture-not-real"}), patch("urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = failure
            with self.assertRaisesRegex(ModelError, "^model_http_401$"): DeepSeekModel().decide([], SCHEMAS)

    def test_broken_protocol_is_an_explicit_model_error(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY":"fixture-not-real"}), patch("urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = http.client.BadStatusLine("provider issue")
            with self.assertRaisesRegex(ModelError, "^model_network_or_timeout_error$"): DeepSeekModel().decide([], SCHEMAS)

    def test_free_text_or_truncated_responses_cannot_bypass_tools(self):
        for calls, finish in (([], "stop"), (None, "length")):
            with self.subTest(finish=finish), patch.dict(os.environ, {"DEEPSEEK_API_KEY":"fixture-not-real"}), patch("urllib.request.build_opener") as factory:
                factory.return_value.open.return_value = self.response(calls=calls, finish_reason=finish)
                with self.assertRaises(ModelError): DeepSeekModel().decide([], SCHEMAS)


if __name__ == "__main__": unittest.main()

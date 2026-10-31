"""Native tool calling; MockModel is explicitly a deterministic test double."""

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


class ModelError(Exception):
    pass


@dataclass
class Decision:
    name: str
    arguments: dict
    call_id: str = ""

    def message(self):
        return {"role": "assistant", "content": None, "tool_calls": [{
            "id": self.call_id, "type": "function", "function": {
                "name": self.name, "arguments": json.dumps(self.arguments, ensure_ascii=False)}}]}


def load_env(path=".env"):
    """Minimal dotenv loader. Existing process environment takes priority."""
    if not Path(path).is_file():
        return
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("invalid .env line; use KEY=value")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key.isidentifier():
            raise ValueError("invalid .env key")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


class DeepSeekModel:
    kind = "real"

    def __init__(self):
        self.key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not self.key:
            raise ValueError("DEEPSEEK_API_KEY is required for --model deepseek; use --model mock offline")
        self.base = os.getenv("MODEL_BASE_URL", "https://api.deepseek.com").rstrip("/")
        parsed = urllib.parse.urlparse(self.base)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("MODEL_BASE_URL must be HTTPS without embedded credentials")
        self.name = os.getenv("MODEL_NAME", "deepseek-flash")
        self.timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "45"))
        if not 1 <= self.timeout <= 120:
            raise ValueError("MODEL_TIMEOUT_SECONDS must be 1..120")
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def decide(self, messages, schemas):
        body = {"model": self.name, "messages": messages, "tools": schemas,
                "tool_choice": "required",
                "thinking": {"type": "disabled"}, "temperature": 0,
                "max_tokens": 1024, "stream": False}
        req = urllib.request.Request(self.base + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        # Do not follow redirects carrying authentication to another host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=self.timeout) as resp:
                raw = resp.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise ModelError("model_response_too_large")
            data = json.loads(raw)
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ModelError("model_response_truncated")
            calls = choice["message"].get("tool_calls", [])
            if len(calls) != 1:
                raise ModelError("model_must_return_exactly_one_tool_call")
            call = calls[0]
            args = json.loads(call["function"]["arguments"])
            if not isinstance(args, dict) or not isinstance(call.get("id"), str):
                raise ModelError("invalid_model_tool_call")
            for key in self.usage:
                self.usage[key] += int(data.get("usage", {}).get(key, 0))
            self.resolved_name = data.get("model", self.name)
            return Decision(call["function"]["name"], args, call["id"])
        except urllib.error.HTTPError as exc:
            # Never emit provider response bodies: they may echo credentials or private input.
            raise ModelError(f"model_http_{exc.code}") from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
            raise ModelError("model_network_or_timeout_error") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelError("invalid_model_response") from None


class MockModel:
    """Deterministic test double responding to actual tool observations, not an LLM."""
    kind = "mock"
    name = "offline-video-policy-v1"

    def decide(self, messages, schemas):
        events = []
        pending = None
        for message in messages:
            if message["role"] == "assistant": pending = message["tool_calls"][0]["function"]
            if message["role"] == "tool": events.append((pending["name"], json.loads(pending["arguments"]), json.loads(message["content"])))
        def choose(name, reason, **args):
            return Decision(name, {"reason": reason, **args}, "mock_" + str(len(events) + 1))
        if not events: return choose("inspect_request", "先核对五项关键输入和平台。")
        name, args, observation = events[-1]
        request = events[0][2].get("request", {})
        if not observation.get("ok", False):
            return choose("stop", "实际工具返回失败，停止并保留已有结果。", outcome="tool_failure")
        if name == "inspect_request":
            if observation["missing_fields"]:
                return choose("request_information", "缺少关键输入或平台不支持，先请求补充。", kind="missing_input")
            return choose("search_materials", "输入完整，按主题检索可核验素材。", query=request["theme"], strategy="keyword")
        if name in {"search_materials", "read_material"}:
            read_ids = {a["material_id"] for n, a, o in events if n == "read_material" and o.get("ok")}
            hits = {h["material_id"]: h for n, a, o in events if n == "search_materials" for h in o.get("hits", [])}
            for material_id in hits:
                if material_id not in read_ids:
                    return choose("read_material", "索引命中后读取原文与事实ID，不能只凭标题生成。", material_id=material_id)
            facts = [f for n, a, o in events if n == "read_material" for f in o.get("material", {}).get("facts", [])]
            if facts:
                return choose("draft_script", "已读事实可作为产品主张，先生成详细分镜再实际检查。",
                              profile="detailed", fact_ids=[f["fact_id"] for f in facts[:3]])
            expanded = any(n == "search_materials" and a["strategy"] == "expanded" for n, a, o in events)
            if not expanded:
                query = "字幕" if any(t in request["theme"] for t in ("配字", "画面文字", "屏幕文字", "台词卡")) else request["theme"]
                return choose("search_materials", "首轮没有可用事实，改写为素材术语并补充检索。", query=query, strategy="expanded")
            return choose("request_information", "两种检索仍无可核验事实，请求补充素材。", kind="missing_materials")
        if name in {"draft_script", "revise_script"}:
            return choose("estimate_duration", "当前版本已改变，重新逐镜计算总时长。")
        draft = next((o["draft"] for n, a, o in reversed(events) if "draft" in o), None)
        if name == "estimate_duration":
            if not observation["within_limit"]:
                if draft["profile"] != "minimal":
                    return choose("revise_script", "实际估时超出上限，选择更短结构并重检。", mode="compress")
                if any(s["hold_seconds"] for s in draft["shots"]):
                    return choose("revise_script", "最简结构仍超时，去掉额外画面停顿再估算。", mode="trim_pauses")
                return choose("stop", "最简结构和零停顿仍超时，明确返回时长缺口。", outcome="duration_unmet")
            return choose("check_brand_rules", "当前版本预计时长合格，核对事实引用及品牌规则。")
        if name == "check_brand_rules":
            if observation["passed"]:
                return choose("finish", "当前版本的实际时长与事实、品牌检查均已通过。")
            if draft["profile"] != "minimal":
                return choose("revise_script", "当前检查存在风险，改为更精简的安全文案并重新检查。", mode="safe_copy")
            return choose("stop", "最简安全文案仍有规则风险，不能交付通过脚本。", outcome="rules_unmet")
        raise ModelError("mock_unexpected_observation")

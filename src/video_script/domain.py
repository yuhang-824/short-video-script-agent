from dataclasses import dataclass
from datetime import date
import hashlib
import json
import re


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Request:
    request_id: str
    theme: str | None = None
    audience: str | None = None
    platform: str | None = None
    target_seconds: int | None = None
    style: str | None = None

    @classmethod
    def parse(cls, raw):
        if not isinstance(raw, dict) or set(raw) - set(cls.__dataclass_fields__):
            raise ValueError("input contains unknown fields")
        if not isinstance(raw.get("request_id"), str) or not raw["request_id"].strip() or len(raw["request_id"]) > 128:
            raise ValueError("request_id required")
        values = {"request_id": raw["request_id"]}
        for key in ("theme", "audience", "platform", "style"):
            value = raw.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > 1000):
                raise ValueError("invalid text field")
            values[key] = (value.strip() or None) if value is not None else None
        seconds = raw.get("target_seconds")
        if seconds is not None and (type(seconds) is not int or not 1 <= seconds <= 180):
            raise ValueError("target_seconds must be an integer 1..180")
        return cls(**values, target_seconds=seconds)

    def as_dict(self):
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    def missing(self):
        return [key for key in ("theme", "audience", "platform", "target_seconds", "style") if getattr(self, key) is None]


def validate_catalog(data):
    if not isinstance(data, dict) or not isinstance(data.get("version"), str) or not isinstance(data.get("materials"), list):
        raise ValueError("invalid catalog")
    rules = data["rules"]
    for key, lower, upper in (("characters_per_second", 1, 10), ("min_scene_seconds", 1, 10)):
        if type(rules[key]) is not int or not lower <= rules[key] <= upper:
            raise ValueError("invalid duration rule")
    if not isinstance(rules["platforms"], list) or not rules["platforms"] or any(not isinstance(x, str) for x in rules["platforms"]):
        raise ValueError("platform rules required")
    if not isinstance(rules["prohibited_terms"], list) or any(not isinstance(x, str) or not x for x in rules["prohibited_terms"]):
        raise ValueError("invalid prohibited terms")
    seen = set()
    for material in data["materials"]:
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,31}", material["id"]) or material["id"] in seen:
            raise ValueError("invalid/duplicate material ID")
        seen.add(material["id"])
        date.fromisoformat(material["version_date"])
        if not isinstance(material["source_text"], str) or not material["source_text"].strip():
            raise ValueError("source text required")
        if not isinstance(material["keywords"], list) or any(not isinstance(x, str) or not x for x in material["keywords"]):
            raise ValueError("invalid material keywords")
        facts = material["facts"]
        if not isinstance(facts, list): raise ValueError("facts must be a list")
        ids = set()
        for fact in facts:
            if not isinstance(fact["id"], str) or not fact["id"] or fact["id"] in ids:
                raise ValueError("invalid/duplicate fact ID")
            ids.add(fact["id"])
            if not isinstance(fact["text"], str) or not fact["text"].strip() or len(fact["text"]) > 200 or fact["text"] not in material["source_text"]:
                raise ValueError("fact must be present verbatim in material source")
        if type(material.get("active", True)) is not bool: raise ValueError("active must be boolean")
    for rule in data.get("failures", {}).values():
        if type(rule.get("times")) is not int or rule["times"] < 0: raise ValueError("invalid failure count")
    return data

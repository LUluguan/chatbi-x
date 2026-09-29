import json


class MockProvider:
    """离线确定性 provider：按问题子串匹配预设 SQL。

    用途：单元测试、评测管线自检、零配置演示。生产请用 openai_compat。
    """

    name = "mock"

    def __init__(self, canned: dict[str, str] | None = None):
        self.canned = dict(canned or {})

    def chat(self, messages, temperature=None):
        question = ""
        for m in reversed(messages):
            if m["role"] == "user":
                question = m["content"]
                break
        for q, sql in self.canned.items():
            if q and (q in question or question in q):
                return json.dumps(
                    {"action": "final", "sql": sql, "summary": f"(mock) 命中预设: {q}"},
                    ensure_ascii=False,
                )
        return json.dumps(
            {"action": "final", "sql": "", "summary": "mock provider：该问题没有预设 SQL"},
            ensure_ascii=False,
        )

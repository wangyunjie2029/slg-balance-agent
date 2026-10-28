"""
轻量 Trace：把每轮事件落成 JSONL，供评测归因和线上排查用。

为什么不用现成的（Langfuse）？
- Langfuse 适合"看单次调用"，不适合"批量统计失败率"
- 这个模块输出的是结构化行，可以直接被 eval 脚本 / pandas 消费
- 两者不冲突：Langfuse 看链路，这个看指标

用法：
    from trace import TraceStore
    store = TraceStore("traces.jsonl")
    store.log(thread_id="s1", event="tool_call", payload={"tool": "simulate_matchup"})
    print(store.stats())
"""

import json
import os
import time
from collections import Counter, defaultdict

from infra import request_id, session_id


class TraceStore:
    def __init__(self, path: str = "traces.jsonl", echo: bool = False):
        self.path = path
        self.echo = echo
        self.events: list[dict] = []  # 内存里也留一份，方便直接统计
        self._fh = None

    def _ensure_fh(self):
        if self._fh is None:
            self._fh = open(self.path, "a", encoding="utf-8")
        return self._fh

    def log(self, event: str, thread_id: str = "-", **payload) -> dict:
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "rid": request_id(),
            "thread_id": thread_id,
            "event": event,
            **payload,
        }
        self.events.append(row)
        fh = self._ensure_fh()
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()  # 崩溃也不丢最后几行
        if self.echo:
            print(f"[trace] {event} {payload}")
        return row

    # ---------- 统计：这是评测报告的数据源 ----------

    def stats(self) -> dict:
        """汇总关键指标。对应评测三环里的「轨迹环」和「成本」。"""
        by_event = Counter(e["event"] for e in self.events)
        tool_rows = [e for e in self.events if e["event"] == "tool_call"]
        tool_fail = [e for e in tool_rows if e.get("ok") is False]

        # 每个会话的步数（工具调用次数）—— 步数爆炸是典型 agent 病
        steps = defaultdict(int)
        for e in self.events:
            if e["event"] == "tool_call":
                steps[e["thread_id"]] += 1

        latencies = [e["ms"] for e in self.events if isinstance(e.get("ms"), (int, float))]

        return {
            "total_events": len(self.events),
            "by_event": dict(by_event),
            "tool_calls": len(tool_rows),
            "tool_failures": len(tool_fail),
            "tool_failure_rate": round(len(tool_fail) / len(tool_rows), 3)
            if tool_rows
            else 0.0,
            "failure_codes": dict(Counter(e.get("error_code") for e in tool_fail)),
            "avg_steps_per_session": round(sum(steps.values()) / len(steps), 2)
            if steps
            else 0.0,
            "max_steps": max(steps.values()) if steps else 0,
            "avg_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
            "p95_ms": _p95(latencies),
        }

    def dump_report(self, out_path: str = "trace_report.json") -> str:
        report = self.stats()
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return out_path

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(len(s) * 0.95))
    return round(s[idx], 1)


# 全局单例：agent 和 main 都 import 这个
_default_path = os.getenv("TRACE_PATH", "traces.jsonl")
store = TraceStore(_default_path)

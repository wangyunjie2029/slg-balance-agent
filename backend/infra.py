"""
基础设施层：请求上下文、限流、工具守卫。

设计原则：
1. 不侵入业务代码——battle/combat/graph 一行不改
2. 所有失败都变成「模型能读懂的结构化数据」，而不是抛异常
3. 成功路径的返回格式保持不变（避免破坏现有评测的 numeric 判定）

接入方式见文件末尾 TODO。
"""

import time
import uuid
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextvars import ContextVar
from functools import wraps

# ============================================================
# 1. 请求上下文：给每个请求一个 ID，日志/trace 全链路可串
# ============================================================

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_session_id: ContextVar[str] = ContextVar("session_id", default="-")


def new_request_id() -> str:
    """生成并绑定一个新的 request_id。中间件里调用。"""
    rid = uuid.uuid4().hex[:12]
    _request_id.set(rid)
    return rid


def bind_session(session_id: str) -> None:
    _session_id.set(session_id)


def request_id() -> str:
    return _request_id.get()


def session_id() -> str:
    return _session_id.get()


# ============================================================
# 2. 限流：内存令牌桶（单进程）
#    ⚠️ 多 worker 部署（uvicorn --workers 4）时每个进程各有一份桶，
#       限额会被放大 N 倍。生产要用 Redis 实现。
# ============================================================


class TokenBucket:
    """令牌桶：capacity 个令牌，每秒补 refill_per_sec 个。

    与固定窗口相比，令牌桶允许短时突发（最多 capacity 个），
    之后稳定在 refill_per_sec 的速率——这更符合真实流量形态。
    """

    def __init__(self, capacity: int = 20, refill_per_sec: float = 0.5):
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self._tokens = float(capacity)
        self._last = time.monotonic()

    def allow(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        # 按流逝时间补令牌，上限是 capacity
        self._tokens = min(
            self.capacity, self._tokens + (now - self._last) * self.refill_per_sec
        )
        self._last = now
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False

    def snapshot(self) -> dict:
        return {"tokens": round(self._tokens, 2), "capacity": self.capacity}


# 全局单桶：按"整个服务"限流。要按用户限流就把 key 换成 user_id。
_chat_bucket = TokenBucket(capacity=20, refill_per_sec=0.5)


def check_rate_limit(cost: float = 1.0) -> tuple[bool, dict]:
    ok = _chat_bucket.allow(cost)
    return ok, _chat_bucket.snapshot()


# ============================================================
# 3. 工具守卫：超时 + 异常 → 结构化错误
# ============================================================

# 这些错误码是给模型看的，它会据此决定"重试 / 换参数 / 放弃"
ERROR_CODES = {
    "TIMEOUT": "工具执行超时。可以重试一次，若仍超时请缩小问题范围。",
    "BAD_ARGUMENT": "参数不合法（如武将/兵种名不存在）。请检查可选值后重新调用。",
    "INTERNAL": "工具内部错误。不要重复调用同一参数，请向用户说明暂时无法完成。",
}

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")


def guarded_tool(name: str, timeout: float = 20.0):
    """装饰器：给工具函数加超时、异常兜底、耗时统计。

    成功：返回原函数的 dict（格式不变，兼容现有评测）
    失败：返回 {"error": ..., "error_code": ..., "suggestion": ..., "elapsed_ms": ...}
    """

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            fut = _executor.submit(fn, *args, **kwargs)
            try:
                result = fut.result(timeout=timeout)
                elapsed = round((time.perf_counter() - t0) * 1000, 1)
                # 成功路径：原样返回，只额外塞一个耗时字段（不影响下游读其他 key）
                if isinstance(result, dict):
                    result.setdefault("_elapsed_ms", elapsed)
                    return result
                return result
            except FutureTimeout:
                return _err("TIMEOUT", f"工具 {name} 超过 {timeout}s 未返回", t0)
            except KeyError as e:
                # 典型场景：LLM 传了不存在的武将名 UNITS[args["unit_a"]]
                return _err("BAD_ARGUMENT", f"缺少或非法的参数: {e}", t0)
            except Exception as e:
                return _err("INTERNAL", f"{type(e).__name__}: {e}", t0)

        return wrapper

    return deco


def _err(code: str, message: str, t0: float) -> dict:
    return {
        "error": message,
        "error_code": code,
        "suggestion": ERROR_CODES.get(code, ""),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def is_error(result: dict) -> bool:
    """判断工具返回值是不是错误。评测和 trace 里用它统计失败率。"""
    return isinstance(result, dict) and "error_code" in result


# ============================================================
# 4. 结构化日志（带 request_id，一行一个 JSON，好 grep 也好喂给日志系统）
# ============================================================


def log_event(event: str, **fields) -> None:
    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rid": request_id(),
        "sid": session_id(),
        "event": event,
    }
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False), flush=True)


# ============================================================
# TODO（需要你亲手改，共 3 处）
#
# 【main.py】加中间件，约 8 行：
#   from infra import new_request_id, bind_session, check_rate_limit, log_event
#   from fastapi import Request
#   from fastapi.responses import JSONResponse
#
#   @app.middleware("http")
#   async def obs_middleware(request: Request, call_next):
#       new_request_id()
#       t0 = time.perf_counter()
#       ok, snap = check_rate_limit()
#       if not ok:
#           return JSONResponse({"error": "too many requests", **snap}, status_code=429)
#       resp = await call_next(request)
#       resp.headers["X-Request-Id"] = request_id()
#       log_event("http", path=request.url.path, status=resp.status_code,
#                 ms=round((time.perf_counter()-t0)*1000, 1))
#       return resp
#
# 【main.py】chat_stream_api 里加一行绑定会话：
#   bind_session(body.session_id)
#
# 【agent.py】给 dispatch 的两个分支加守卫（保持返回格式不变）：
#   from infra import guarded_tool, log_event
#
#   @guarded_tool("simulate_matchup", timeout=30.0)
#   def _simulate_matchup(args: dict) -> dict:
#       army_a = Army(...)   # ← 把原来 dispatch 里的逻辑整段挪进来
#       ...
#
#   def dispatch(name, args):
#       if name == "simulate_matchup":
#           r = _simulate_matchup(args)
#           log_event("tool", tool=name, args=args,
#                     ok=not is_error(r), ms=r.get("_elapsed_ms"))
#           return r
#       return {"error": f"未知工具: {name}", "error_code": "BAD_ARGUMENT"}
# ============================================================

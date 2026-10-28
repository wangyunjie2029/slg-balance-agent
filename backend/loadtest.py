"""压测：回答「能扛多少并发」这个问题。

面试必问，但大多数人只能答"没测过"。这个文件给三层数字：

① 引擎层（纯 CPU）：单次对局模拟耗时、串行 QPS、多线程 QPS、加速比
   → 回答了"你的工具调用有多重"「加机器能不能解决」

② 事件循环阻塞实验（最值钱的一层）
   → 证明"在 async def 里直接跑同步 CPU 任务会堵死整个服务"，
     以及本项目为什么不会（StreamingResponse 走线程池 + 工具层再套执行器）
   测法：跑一个 10ms 心跳，同时做一次 CPU 密集调用，看心跳的最大间隔。
   直接调用 → 间隔飙升；to_thread → 间隔基本不变。这是硬证据，不是说法。

③ API 层（可选，--api）：并发打 /ping，测框架开销与 P95
   → 不含 LLM 时能看到真实的服务开销；含 LLM 时延迟由模型主导，
     这也是为什么"并发上限"要分两层说，混在一起讲没有意义。

用法：
    python loadtest.py                # ①②（不花钱、不调 LLM）
    python loadtest.py --api          # 额外跑 ③
    python loadtest.py --n 50         # 每层采样次数

产出：
    reports/loadtest.json
"""

import argparse
import asyncio
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from battle import Army
from config import DAMAGE_JITTER, SIM_N, SIM_SEED
from data import GENERALS, UNITS
from mc_sim import run_mc_sim

OUT = Path("reports/loadtest.json")


def _sim(ga="张飞", ta="骑兵", gb="关羽", tb="枪兵"):
    return run_mc_sim(
        Army(UNITS[ta], GENERALS[ga], ta),
        Army(UNITS[tb], GENERALS[gb], tb),
        n=SIM_N,
        damage_jitter=DAMAGE_JITTER,
        seed=SIM_SEED,
    ).win_rate_a


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]


def bench_engine(n: int) -> dict:
    """① 引擎层：串行 vs 多线程。"""
    # 预热，避免第一次调用被 import / 缓存初始化拉长
    _sim()
    _sim()

    seq = []
    for _ in range(n):
        t0 = time.perf_counter()
        _sim()
        seq.append((time.perf_counter() - t0) * 1000)

    workers = 8
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda _: _sim(), range(n)))
    wall = time.perf_counter() - t0

    seq_total = sum(seq) / 1000
    return {
        "sim_n": SIM_N,
        "samples": n,
        "single_ms_mean": round(statistics.mean(seq), 2),
        "single_ms_p50": round(_pct(seq, 0.5), 2),
        "single_ms_p95": round(_pct(seq, 0.95), 2),
        "seq_qps": round(n / seq_total, 1),
        "thread_workers": workers,
        "thread_qps": round(n / wall, 1),
        "thread_speedup": round((n / wall) / (n / seq_total), 2),
        "note": (
            "加速比 < 1 说明受 GIL / CPU 核数限制；模拟是纯 Python 计算，"
            "多线程不会线性扩展，这正是要用多进程而非多线程扩容的依据。"
        ),
    }


async def _heartbeat(stop: asyncio.Event, gaps: list[float]) -> None:
    """每 10ms 打一次点，记录实际间隔。间隔异常 = 事件循环被占住了。"""
    last = time.perf_counter()
    while not stop.is_set():
        await asyncio.sleep(0.01)
        now = time.perf_counter()
        gaps.append((now - last) * 1000)
        last = now


async def _measure_blocking(use_thread: bool) -> dict:
    stop = asyncio.Event()
    gaps: list[float] = []
    hb = asyncio.create_task(_heartbeat(stop, gaps))
    await asyncio.sleep(0.05)  # 让心跳先稳定

    t0 = time.perf_counter()
    # 连续 8 次 CPU 密集调用（约 8 × 单次耗时）
    if use_thread:
        for _ in range(8):
            await asyncio.to_thread(_sim)
    else:
        for _ in range(8):  # ← 直接在协程里跑同步代码：反模式
            _sim()
    work_ms = (time.perf_counter() - t0) * 1000

    await asyncio.sleep(0.05)
    stop.set()
    await hb
    return {
        "mode": "to_thread" if use_thread else "direct_call",
        "work_ms": round(work_ms, 1),
        "heartbeat_samples": len(gaps),
        "heartbeat_max_gap_ms": round(max(gaps), 1) if gaps else 0.0,
        "heartbeat_p95_gap_ms": round(_pct(gaps, 0.95), 1),
    }


def bench_event_loop() -> dict:
    """② 事件循环阻塞实验：同一段 CPU 工作，两种写法下心跳的最大间隔。"""
    direct = asyncio.run(_measure_blocking(False))
    threaded = asyncio.run(_measure_blocking(True))
    ratio = (
        round(threaded["heartbeat_max_gap_ms"] / direct["heartbeat_max_gap_ms"], 2)
        if direct["heartbeat_max_gap_ms"]
        else None
    )
    return {
        "direct_call": direct,
        "to_thread": threaded,
        "blocked_ratio": ratio,
        "verdict": (
            "直接调用时心跳被拉长到与工作时长同量级，说明整个事件循环被独占；"
            "改为 to_thread 后心跳恢复正常。这就是本项目 SSE 与工具层都必须"
            "离开事件循环的原因。"
        ),
    }


def bench_api(concurrency: int = 8, requests: int = 40) -> dict:
    """③ API 层：并发打 /ping（不触发 LLM），测框架开销与 P95。"""
    from fastapi.testclient import TestClient

    from main import app

    lat = []
    errors = 0
    with TestClient(app) as client:

        def one(_):
            t0 = time.perf_counter()
            try:
                r = client.get("/ping")
                if r.status_code != 200:
                    return None, (time.perf_counter() - t0) * 1000
            except Exception:
                return None, (time.perf_counter() - t0) * 1000
            return r.status_code, (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            for status, ms in ex.map(one, range(requests)):
                if status is None:
                    errors += 1
                lat.append(ms)
        wall = time.perf_counter() - t0

    return {
        "endpoint": "/ping",
        "concurrency": concurrency,
        "requests": requests,
        "qps": round(requests / wall, 1),
        "p50_ms": round(_pct(lat, 0.5), 2),
        "p95_ms": round(_pct(lat, 0.95), 2),
        "max_ms": round(max(lat), 2),
        "errors": errors,
        "note": (
            "这条只测框架与中间件开销，不含 LLM。聊天接口的延迟由模型主导"
            "（首 token 1~2s），所以「并发上限」必须分「服务开销」和「模型配额」"
            "两层说，合成一个数字是耍流氓。"
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30, help="引擎层每档采样次数")
    ap.add_argument("--api", action="store_true", help="额外跑 API 层")
    args = ap.parse_args()

    print(f"[1/2] 引擎层（{args.n} 次，每次 {SIM_N} 局）...", flush=True)
    engine = bench_engine(args.n)
    print(
        f"      单次 {engine['single_ms_mean']}ms  P95 {engine['single_ms_p95']}ms  "
        f"串行 {engine['seq_qps']} QPS  "
        f"{engine['thread_workers']} 线程 {engine['thread_qps']} QPS "
        f"(加速比 {engine['thread_speedup']}x)",
        flush=True,
    )

    print("[2/2] 事件循环阻塞实验...", flush=True)
    loop = bench_event_loop()
    print(
        f"      直接调用：心跳最大间隔 {loop['direct_call']['heartbeat_max_gap_ms']}ms  "
        f"→ to_thread：{loop['to_thread']['heartbeat_max_gap_ms']}ms",
        flush=True,
    )

    result = {"engine": engine, "event_loop": loop}
    if args.api:
        print("[+] API 层（/ping 并发）...", flush=True)
        result["api"] = bench_api()
        print(
            f"      {result['api']['qps']} QPS  P95 {result['api']['p95_ms']}ms  "
            f"错误 {result['api']['errors']}",
            flush=True,
        )

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已落盘：{OUT}")


if __name__ == "__main__":
    main()

"""
集中配置 + 启动校验。

为什么要有这个文件：
1. 所有"魔法数字"集中在一处，改行为只改一个地方（面试问"配置怎么管理"就答这个）
2. 每个值都能用环境变量覆盖，方便部署到不同环境
3. validate() 在启动时把配置问题一次性说清楚，而不是等运行到一半崩

注意：本文件不导入任何业务模块，避免循环依赖。
"""

import os

from dotenv import load_dotenv

load_dotenv()  # 读 backend/.env；不存在也不报错，只是拿不到 key

# ===== 模型 =====
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")
API_BASE = os.getenv("API_BASE", "https://api.deepseek.com")
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# ===== Agent 循环 =====
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "10"))
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "12"))  # 上下文滑窗大小

# ===== 战斗模拟 =====
# 调参结论：DAMAGE_FACTOR=1.0 + jitter=0.35 时 extreme_ratio 从 1.0 降到 0.60。
# 之前工具层写 0.2、诊断层写 0.35，两套参数跑出两个不同的"世界"，
# 现在统一到 0.35 —— 但评测集真值必须重跑 gen_cases.py 重新取证。
SIM_N = int(os.getenv("SIM_N", "500"))
DAMAGE_JITTER = float(os.getenv("DAMAGE_JITTER", "0.35"))
SIM_SEED = int(os.getenv("SIM_SEED", "42"))

# ===== 工具层 =====
TOOL_TIMEOUT = float(os.getenv("TOOL_TIMEOUT", "30"))

# ===== 接入层 =====
RATE_LIMIT_CAPACITY = int(os.getenv("RATE_LIMIT_CAPACITY", "20"))
RATE_LIMIT_REFILL = float(os.getenv("RATE_LIMIT_REFILL", "0.5"))
# 为空则不校验（本地开发）；部署时务必设置，否则任何人可无限调用你的 API key
API_TOKEN = os.getenv("API_TOKEN", "")

# ===== 降级 =====
FAILURE_THRESHOLD = int(os.getenv("FAILURE_THRESHOLD", "2"))


def validate() -> list[str]:
    """返回配置问题列表。空列表 = 一切正常。"""
    problems: list[str] = []

    if not API_KEY:
        problems.append("DEEPSEEK_API_KEY 未设置（检查 backend/.env）")
    if SIM_N <= 0:
        problems.append(f"SIM_N 必须 > 0，当前 {SIM_N}")
    if not 0 <= DAMAGE_JITTER <= 1:
        problems.append(f"DAMAGE_JITTER 应在 0~1 之间，当前 {DAMAGE_JITTER}")
    if MAX_ROUNDS <= 0:
        problems.append(f"MAX_ROUNDS 必须 > 0，当前 {MAX_ROUNDS}")
    if WINDOW_SIZE < 2:
        problems.append(f"WINDOW_SIZE 太小，至少 2，当前 {WINDOW_SIZE}")
    if RATE_LIMIT_CAPACITY <= 0:
        problems.append(f"RATE_LIMIT_CAPACITY 必须 > 0，当前 {RATE_LIMIT_CAPACITY}")

    return problems


def assert_valid() -> None:
    """启动时调用：配置有问题直接抛，别等运行到一半才发现。"""
    problems = validate()
    if problems:
        raise RuntimeError(
            "配置存在问题，已中止启动：\n" + "\n".join(f"  - {p}" for p in problems)
        )


def summary() -> dict:
    """脱敏后的配置快照，用于日志/评测报告。"""
    return {
        "model": MODEL_NAME,
        "max_rounds": MAX_ROUNDS,
        "window_size": WINDOW_SIZE,
        "sim_n": SIM_N,
        "damage_jitter": DAMAGE_JITTER,
        "sim_seed": SIM_SEED,
        "tool_timeout": TOOL_TIMEOUT,
        "rate_limit": f"{RATE_LIMIT_CAPACITY}/{RATE_LIMIT_REFILL}per sec",
        "auth_enabled": bool(API_TOKEN),
        "failure_threshold": FAILURE_THRESHOLD,
        "api_key_set": bool(API_KEY),
    }

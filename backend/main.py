"""
SLG 数值平衡 Agent —— 后端入口
Step 0：先验证 FastAPI 服务能正常启动并返回数据。
"""

import json
import time
from contextlib import asynccontextmanager
from typing import Annotated

import config
from agent import ask_agent_stream
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from infra import bind_session, check_rate_limit, log_event, new_request_id, request_id
from llm import chat_stream
from pydantic import BaseModel, Field


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动检查 + 收尾。

    用 lifespan 而不是已废弃的 @app.on_event("startup")：
    后者在 FastAPI 0.9x+ 会抛 DeprecationWarning，新版迟早移除。
    """
    problems = config.validate()
    if problems:
        for p in problems:
            print(f"[config][ERROR] {p}")
        raise RuntimeError("配置不合法，已中止启动")

    log_event("startup", **config.summary())
    if not config.API_TOKEN:
        print("[config][WARN] API_TOKEN 未设置 → 接口无鉴权，仅适合本地开发")
    yield
    log_event("shutdown")


# 创建 FastAPI 应用实例；title/version 会显示在自动生成的接口文档 /docs 里
app = FastAPI(title="SLG 数值平衡 Agent", version="0.1.0", lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],  # 本地前端来源（精确匹配）
    allow_origin_regex=r"https://.*\.onrender\.com",  # Render 部署的前端子域（正则匹配）
    allow_methods=["*"],
    allow_headers=["*"],
)


# 观测中间件：给每个请求分配 request_id，记录路径/状态码/耗时。
#
# ⚠ 顺序机制（实测过，别凭直觉）：Starlette 的 add_middleware 是 insert(0)，
#   **后加的在最外层**。所以这里 obs 在外层、CORS 在内层。执行顺序是
#   ServerError → obs → CORS → 路由 → CORS → obs。
#   429 是路由内部返回的，响应回来时会经过 CORS，所以照样带 CORS 头。
#   反过来若 obs 自己抛异常，CORS 头会丢（概率低，但这是它在外层的代价）。
#
# 注意：这里不返回错误。限流只针对 /api/chat/stream 这类"贵"接口，
# 放在路由内部判断更精准（否则 /ping 也会被限）。
@app.middleware("http")
async def obs_middleware(request: Request, call_next):
    new_request_id()
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    response.headers["X-Request-Id"] = request_id()
    log_event("http", path=request.url.path, status=response.status_code, ms=ms)
    return response


# @app.get("/ping") 是一个"路由装饰器"：
# 当浏览器用 GET 方式访问 /ping 时，下面的函数会被 FastAPI 自动调用。
@app.get("/ping")
def ping():
    # 返回的 dict 会被 FastAPI 自动转成 JSON：{"ok": true, "message": "pong"}
    return {"ok": True, "message": "pong"}


@app.get("/")
def root():
    return {"service": "slg-balance-agent", "status": "running"}


class ChatRequest(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=2000)]
    session_id: Annotated[str, Field(max_length=64)] = "default"


async def require_token(authorization: str = Header(default="")) -> None:
    """Bearer 鉴权。

    设计取舍：API_TOKEN 未配置时**放行**（本地开发不折腾），配置后强制校验。
    听起来"默认不安全"，但这是刻意的——如果真的默认拒绝，本地跑不起来就没人用，
    最后会变成把 token 写死在代码里。正确做法是「默认放行 + 启动日志明确提示」，
    部署时由环境变量锁死。这个取舍本身是面试可以讲的一点。
    """
    if not config.API_TOKEN:
        return
    if authorization != f"Bearer {config.API_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid or missing token")


@app.post("/api/chat/stream")
async def chat_stream_api(body: ChatRequest, _: None = Depends(require_token)):
    """Agent 流式对话：tool_call → tool_result → answer 事件序列。"""
    # ① 绑定会话：让日志/工具层能拿到 session_id
    bind_session(body.session_id)

    # ② 限流：一次对话会消耗大量 token 和 CPU（500 次对局模拟），必须挡
    ok, snap = check_rate_limit()
    if not ok:
        log_event("rate_limited", tokens=snap["tokens"], capacity=snap["capacity"])
        return JSONResponse(
            {"error": "请求过于频繁，请稍后再试", **snap}, status_code=429
        )

    def event_gen():
        # 客户端断开检测：用户关页面后，不该继续跑 500 局模拟、继续烧 token。
        # 这里用的是「同步生成器 + GeneratorExit」而不是 request.is_disconnected()：
        # ask_agent_stream 是同步生成器（Starlette 会丢线程池迭代），如果在里面
        # await is_disconnected() 反而要跨线程调度。GeneratorExit 是 Starlette
        # 关闭响应时抛进来的，捕获到就说明对端已断——这是同步生成器的正确姿势。
        try:
            for evt in ask_agent_stream(body.message, body.session_id):
                yield f"event: {evt['event']}\ndata: {json.dumps(evt['data'], ensure_ascii=False)}\n\n"
        except GeneratorExit:
            log_event("client_disconnect", thread_id=body.session_id)
            raise

    return StreamingResponse(event_gen(), media_type="text/event-stream")

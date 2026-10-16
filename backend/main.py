"""
SLG 数值平衡 Agent —— 后端入口
Step 0：先验证 FastAPI 服务能正常启动并返回数据。
"""

import json

from agent import ask_agent_stream
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from llm import chat_stream
from pydantic import BaseModel

# 创建 FastAPI 应用实例；title/version 会显示在自动生成的接口文档 /docs 里
app = FastAPI(title="SLG 数值平衡 Agent", version="0.1.0")


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
    message: str


@app.post("/api/chat/stream")
async def chat_stream_api(body: ChatRequest):
    """Agent 流式对话：tool_call → tool_result → answer 事件序列。"""

    def event_gen():
        for evt in ask_agent_stream(body.message):
            yield f"event: {evt['event']}\ndata: {json.dumps(evt['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")

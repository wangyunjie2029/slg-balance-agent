"""
LLM 接入：OpenAI 兼容客户端 + 最小对话函数。
Step 2 第 1 小步。
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

# 读取 backend/.env（不存在也不报错，只是拿不到 key）
load_dotenv()


def get_client() -> OpenAI:
    """创建 LLM 客户端；key 从环境变量读，绝不硬编码。"""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("未找到 DEEPSEEK_API_KEY，请检查 backend/.env")
    return OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",  # 换厂商时只改这里和模型名
    )


def chat(messages: list[dict]) -> str:
    """最小对话：传入 [{"role": "user", "content": "..."}]，返回回复文本。"""
    client = get_client()
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
    )
    return resp.choices[0].message.content

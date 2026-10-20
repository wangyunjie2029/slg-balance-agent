import json

from llm import get_client

JUDGE_SYSTEM = """你是 AI Agent 回答质量的评审官。你会收到【用户问题】和【Agent 回答】，
请从三个维度打分（每项 0~10 分）并给出理由：

1. faithfulness（归因忠实度）：回答中的因果解释是否有依据？
   - 引用了工具数据做归因 → 高分；用通用常识脑补因果（如编造克制关系）→ 低分
2. completeness（引用完整性）：该引用工具结果的地方是否引用了？
   - 报告类回答应引用关键数字/指标；纯对话类可放宽
3. appropriateness（得体性）：面对模糊/异常输入的应对是否得体？
   - 反问澄清、声明假设 → 高分；不懂装懂、答非所问 → 低分

输出严格为 JSON（不要多余文字）：
{"faithfulness": <0-10>, "completeness": <0-10>, "appropriateness": <0-10>,
 "reasons": {"faithfulness": "...", "completeness": "...", "appropriateness": "..."}}"""


def judge_answer(question: str, answer: str) -> dict:
    client = get_client()
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {
                "role": "user",
                "content": f"【用户问题】{question}\n\n【Agent 回答】{answer}",
            },
        ],
        temperature=0,  # Judge 要稳定，不要创造性
    )
    return json.loads(resp.choices[0].message.content)

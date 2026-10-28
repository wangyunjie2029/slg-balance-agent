import json
import re

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


def _parse_json(text: str) -> dict:
    """从模型输出里抠出 JSON。

    为什么需要：即使 prompt 写了「严格输出 JSON」，模型仍可能返回：
      ```json
      {"faithfulness": 8, ...}
      ```
    原来的 `json.loads(...)` 遇到这种就直接抛异常，一条 judge 失败会把
    整批评测带崩。这里做三级降级：直接解析 → 剥 markdown → 正则抠第一个对象。
    """
    text = (text or "").strip()

    # 1) 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2) 剥掉 ```json ... ``` 围栏
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # 3) 贪婪抠第一个完整的 {...}
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # 4) 全失败：返回明确的失败标记，而不是让流程崩掉
    #    评测里会把它当成"Judge 不可用"，不影响规则断言的判定
    return {
        "faithfulness": 0,
        "completeness": 0,
        "appropriateness": 0,
        "reasons": {"error": f"Judge 输出无法解析: {text[:120]}"},
    }


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
    return _parse_json(resp.choices[0].message.content)

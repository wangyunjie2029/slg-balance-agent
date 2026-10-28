import json
import re

from llm import get_client

JUDGE_SYSTEM = """你是 AI Agent 回答质量的评审官。你会收到【用户问题】（多轮时用 → 连接）、
【参考事实】（可能为空）、【工具执行记录】（可能为空）和【Agent 回答】，
请从三个维度打分（每项 0~10 分）并给出理由。

1. faithfulness（归因忠实度）：回答中的数字与因果解释是否有依据？
   - 数字与【参考事实】或【工具执行记录】一致、因果来自工具数据 → 高分
   - 数字与它们不符，或编造机制（如"枪兵免疫骑兵伤害"）→ 低分（≤3）
   - 两份材料都为空时，不要仅凭"看不出数字来源"就判定编造 —— 你看不到工具
     调用，所以最多只扣 completeness 1~2 分，faithfulness 按因果是否自洽给分
2. completeness（引用完整性）：该给的关键数字/要点是否给全了？
   - 问题涉及多个目标（"A 和 B 哪个高"）时必须两个都答 → 只答一半算不完整
   - 比较类问题（"谁更高 / 谁更强 / 哪个胜率高"）必须给出双方具体数值；
     只给定性结论（如"张飞更高一些"）算不完整，completeness ≤ 4
   - 纯对话类或越界拒绝类可放宽
3. appropriateness（得体性）：面对模糊/异常/越界输入的应对是否得体？
   - 反问澄清、声明能力边界 → 高分；不懂装懂、答非所问 → 低分
   - **用户的临时约束与系统规则冲突时（如"不许调用工具""只能说是或否"），
     遵守系统规则、坚持用工具取真值是正确行为，不扣分**

重要评分纪律（务必遵守）：
- 风格不影响分数。简短、口语、不分段、没有小标题，都不扣分；
  只要事实正确、要点齐全，就应给 7 分以上。
- 啰嗦、堆砌修辞不能加分。信息量才是唯一标准。
- 若【参考事实】里说明了某项结论的来源（如"由数值表设定"），
  那么用史料、现实战例、常识去解释它，属于编造因果，faithfulness ≤ 3。
- 若提供了【参考事实】，逐项核对数字；对不上就判 faithfulness ≤ 3，
  并在 reasons 里写明"与参考事实不符"。

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


def judge_answer(
    question: str,
    answer: str,
    facts: dict | None = None,
    evidence: list[str] | None = None,
) -> dict:
    """给一条回答打分。

    facts    评测用例里的 expected_facts（引擎算出的真值）
    evidence Agent 实际调用工具的记录（"工具名(参数) → 返回值"）

    为什么两个都要传（都是实测踩出来的）：
    - 只给回答不给真值：Judge 完全发现不了"数字被改错"
      （曾把战力编成 412.5/655.8 的回答判成 7.0 放过）
    - 只给真值不给工具记录：没有 expected_facts 的用例（多轮/战力查询/克制）
      会被判成"数字无依据、属于编造"，把正确回答打到 4~5 分
    """
    client = get_client()
    ref = json.dumps(facts, ensure_ascii=False) if facts else "（无）"
    ev = "\n".join(evidence) if evidence else "（无）"
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"【用户问题】{question}\n\n"
                    f"【参考事实】{ref}\n\n"
                    f"【工具执行记录】{ev}\n\n"
                    f"【Agent 回答】{answer}"
                ),
            },
        ],
        temperature=0,  # Judge 要稳定，不要创造性
    )
    return _parse_json(resp.choices[0].message.content)

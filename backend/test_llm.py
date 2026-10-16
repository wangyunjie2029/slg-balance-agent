from llm import chat

reply = chat([{"role": "user", "content": "用一句话介绍三国里的张飞"}])
print("模型回复：", reply)

# 顺便试一下 system 角色设定的效果
reply2 = chat(
    [
        {"role": "system", "content": "你是一个三国历史学者，说话文雅简练。"},
        {"role": "user", "content": "评价一下吕布这个人"},
    ]
)
print("学者回复：", reply2)

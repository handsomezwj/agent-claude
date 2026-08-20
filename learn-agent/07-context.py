# 第十课：上下文管理——对话越聊越长，总有一个时刻会超窗。
# 演示：10 轮寒暄，粗略一算就超了 budget → 裁掉最老的，保住最近的。
from context import history_tokens, trim_history


def make_smalltalk(rounds):
    """造一轮又一轮的寒暄，模拟 agent 被反复调用的历史"""
    history = []
    for i in range(1, rounds + 1):
        history.append({"role": "user", "content": f"第{i}轮：今天天气怎么样？"})
        history.append({"role": "assistant", "content": "看起来不错，适合出门走走。"})
    return history


def show(name, history):
    print(f"\n--- {name}（{len(history)} 条，约 {history_tokens(history)} token）---")
    for msg in history:
        print(f"  {msg['role']:>9}: {msg['content']}")


if __name__ == "__main__":
    history = make_smalltalk(10)
    show("原始对话（10 轮）", history)

    budget = 120  # 假设模型这一次只能读 120 token
    print(f"\n窗口预算：{budget} token —— 超了，必须裁")

    trimmed = trim_history(history, budget)
    show("裁剪之后", trimmed)

    print("\n老人被忘掉了，最近的几轮还在——agent 才能继续干活。")

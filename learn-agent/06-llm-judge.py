# 第九课：裁判模型——用一个 LLM 给另一个 LLM 的回答打分
# 带 --fake 只跑假裁判（一分钱不花）；不带参数会连真 API，花一点点钱。
import os
import sys
import anthropic
from dotenv import load_dotenv
from llm_judge import judge_answer
from agent_loop import FakeModel, FakeResponse, text_block

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

TASK = "用两句话解释 Python 的 GIL。"
ANSWERS = [
    ("好回答", "GIL 是 CPython 的全局解释器锁，保证同一时刻只有一个线程执行字节码，从而保护内存安全。代价是多线程没法真正利用多核 CPU。"),
    ("一般回答", "GIL 就是全局锁，多线程不能同时干活，性能受影响。"),
    ("差回答", "GIL 是一种编程语言。"),
]


def fake_judge_run():
    print("== 假裁判（剧本）：先把流程跑通，一分钱不花 ==")
    fake = FakeModel([FakeResponse("end_turn", [text_block("4/5\n准确清晰，稍欠展开")])])
    score, _ = judge_answer(fake, TASK, ANSWERS[0][1])
    print(f"  假裁判给'好回答'打了 {score}/5 → 流程验证成功")
    print("  下面换真裁判上场。")


def real_judge_run():
    print("== 真裁判：给三份回答打分 ==")
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )
    for label, answer in ANSWERS:
        score, text = judge_answer(client, TASK, answer)
        print(f"\n[{label}] 得分：{score}/5")
        print(f"裁判原话：{text}")


if __name__ == "__main__":
    fake_judge_run()
    if len(sys.argv) > 1 and sys.argv[1] == "--fake":
        print("（--fake 模式：跳过真裁判，不花钱）")
    else:
        real_judge_run()

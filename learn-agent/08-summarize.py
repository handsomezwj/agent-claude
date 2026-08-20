# 第十一课：摘要压缩——trim 的进阶。超预算时不扔掉旧对话，而是浓缩成几句话。
# 带 --fake 用假摘要模型跑通（一分钱不花）；不带参数连真 API。
import os
import sys
import anthropic
from dotenv import load_dotenv
from summarize import replace_with_summary
from agent_loop import FakeModel, FakeResponse, text_block
from context import history_tokens

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))


def make_smalltalk(rounds):
    history = []
    for i in range(1, rounds + 1):
        history.append({"role": "user", "content": f"第{i}轮：今天天气怎么样？"})
        history.append({"role": "assistant", "content": "看起来不错，适合出门走走。"})
    return history


def fake_run():
    print("== 假摘要模型（剧本）：先把流程跑通，一分钱不花 ==")
    history = make_smalltalk(3)
    fake = FakeModel([FakeResponse("end_turn", [text_block("用户问了三天天气，都适合出门")])])
    new_h, summary = replace_with_summary(history, 12, fake)
    print(f"  原对话约 {history_tokens(history)} token → 摘要：'{summary}'")
    print(f"  替换后 {len(new_h)} 条，约 {history_tokens(new_h)} token")
    print("  下面换真摘要模型上场。")


def real_run():
    print("== 真摘要模型 ==")
    history = make_smalltalk(6)
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )
    new_h, summary = replace_with_summary(history, 40, client)
    print(f"  原对话约 {history_tokens(history)} token")
    print(f"  摘要：{summary}")
    print(f"  替换后 {len(new_h)} 条，约 {history_tokens(new_h)} token")


if __name__ == "__main__":
    fake_run()
    if len(sys.argv) > 1 and sys.argv[1] == "--fake":
        print("（--fake 模式：跳过真模型，不花钱）")
    else:
        real_run()

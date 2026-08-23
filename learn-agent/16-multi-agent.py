# 第 19 课：真正的多 Agent 协作——双脑版
#
# 第 13 课是单脑版（一个模型换 prompt 演两个角色，共用一份记忆）。
# 这课是双脑版：写手、评审是两个独立 Agent 对象，各有各的记忆（messages），
# 协调器（coordinator）只认 .ask() 这个门。结尾把两个人的"账本"摊开——
# 写手记写手的，评审记评审的，互不污染。
#
# 用法：
#   python 16-multi-agent.py --fake   假模型剧本，零成本，看全流程 + 各记各的账
#   python 16-multi-agent.py          真模型，写手+评审真的协作（花一点钱）
import os
import sys

from agent_loop import FakeModel, FakeResponse, text_block
from multi_agent import (
    WRITER_SYSTEM,
    REVIEWER_SYSTEM,
    Agent,
    run_collab,
)

TASK = "杭州 AI 应用开发方向的自我介绍"
MAX_ROUNDS = 3

if "--fake" in sys.argv:
    print("【假模型模式】两个假脑子照剧本演，零成本。注意每轮评审都记得自己上一轮说了啥。\n")
    writer = Agent("写手", WRITER_SYSTEM, FakeModel([
        FakeResponse("end_turn", [text_block("我叫小张，杭州求职 AI 应用开发。")]),
        FakeResponse("end_turn", [text_block("我叫小张，杭州求职 AI 应用开发。我学过 Python 和机器学习，也用 LLM API 写过小工具。")]),
        FakeResponse("end_turn", [text_block("我叫小张，杭州求职 AI 应用开发。我手写过基于 Anthropic SDK 的 Agent 系统（工具循环 + 护栏 + 流式），也搭过 RAG 管线（向量检索），代码开源在 github.com/handsomezwj。")]),
    ]))
    reviewer = Agent("评审", REVIEWER_SYSTEM, FakeModel([
        FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 没提任何技术或项目\n【被审内容】x")]),
        FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 有技术了但没项目；2. 上一轮说缺技术，这轮补上了，很好，但还缺 RAG/Agent 这类岗位关键词\n【被审内容】x")]),
        FakeResponse("end_turn", [text_block("【结论】通过\n【意见】无\n【被审内容】x")]),
    ]))
else:
    print("【真实模型模式】写手、评审各带各的记忆，真调 API（花一点钱）。\n")
    from dotenv import load_dotenv

    # .env 在 learn-agent 的上一级（c:\Users\zwj\.env），不在本目录——向上找
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    import anthropic

    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )
    model_name = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    # 两个 Agent 共用同一个 client（client 无状态，对话全在各自的 messages 里），
    # 但各自的记忆互不相通——这就是双脑。
    writer = Agent("写手", WRITER_SYSTEM, client, model_name)
    reviewer = Agent("评审", REVIEWER_SYSTEM, client, model_name)


# ---- 协调器跑全流程（只认 .ask()，不认谁装的脑子）----
result = run_collab(writer, reviewer, TASK, max_rounds=MAX_ROUNDS)

print("--- 协作过程 ---")
for entry in result["log"]:
    print(f"第 {entry['round']} 轮  评审【{entry['verdict']}】")
    print(f"  评审意见：{entry['opinions'][:60]}")
    print(f"  写手当前稿：{entry['draft'][:40]}...")

print(f"\n--- 结果 ---")
print(f"通过？{'✅ 是' if result['passed'] else '❌ 否'}（{result['rounds']} 轮）  "
      f"{result['error'] or ''}".strip())
if result["text"]:
    print(f"最终稿：\n{result['text']}")

print("\n--- 各记各的账（两个脑子各自的记忆）---")
print("写手记得：")
for m in writer.history():
    print(f"  [{m['role']}] {m['content'][:48]}")
print("评审记得：")
for m in reviewer.history():
    print(f"  [{m['role']}] {m['content'][:48]}")

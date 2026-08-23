# 第 13 课：多 Agent 评审模式 demo。
# 写手写 → 评审挑 → 按意见改 → 再评，直到通过或到顶。
# 默认 --fake 用假模型剧本（零成本）；去掉 --fake 用真实模型（花一点钱）。
# 跑法：python 10-debate.py --fake
import os
import sys

from agent_loop import FakeModel, FakeResponse, text_block
from debate import (
    _call,
    build_critic_prompt,
    build_draft_prompt,
    build_revise_prompt,
    parse_critic,
)

USE_FAKE = "--fake" in sys.argv
TOPIC = "杭州 AI 应用开发方向的自我介绍"
MAX_ROUNDS = 3

if USE_FAKE:
    print("【假模型模式】剧本演出，零成本。看稿子怎么被评审逼着越写越好。\n")
    model = FakeModel([
        FakeResponse("end_turn", [text_block("我叫小张，杭州求职 AI 应用开发。")]),
        FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 太空泛，没提任何技术或项目\n【被审内容】x")]),
        FakeResponse("end_turn", [text_block("我叫小张，杭州求职 AI 应用开发。我学过 Python 和机器学习，也用过 LLM API。")]),
        FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 有技术但没项目；2. 没提 RAG/Agent 这类岗位关键词\n【被审内容】x")]),
        FakeResponse("end_turn", [text_block("我叫小张，杭州求职 AI 应用开发。我手写过基于 Anthropic SDK 的 Agent 系统（工具循环 + 四道护栏），也搭过 RAG 管线（BGE 向量化 + Chroma 检索），代码开源在 github.com/handsomezwj。")]),
        FakeResponse("end_turn", [text_block("【结论】通过\n【意见】无\n【被审内容】x")]),
    ])
    model_name = "fake"
else:
    print("【真实模型模式】会花一点钱（每次调 API 都计费）。\n")
    from dotenv import load_dotenv

    # .env 在 learn-agent 的上一级（c:\Users\zwj\.env），不在本目录——向上找
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    import anthropic

    model = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )
    model_name = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")


# 手动循环展示每一轮（只借 debate.py 的函数，不抄）
draft = _call(model, build_draft_prompt(TOPIC), model_name)
print(f"写手第一稿：{draft}\n")

passed = False
for round_no in range(1, MAX_ROUNDS + 1):
    critic = _call(model, build_critic_prompt(TOPIC, draft), model_name)
    verdict, opinions = parse_critic(critic)
    print(f"第 {round_no} 轮评审：【{verdict}】{opinions[:50]}")

    if verdict == "通过" or opinions == "无":
        print(f"\n✅ 第 {round_no} 轮通过！最终稿：\n\n{draft}\n")
        passed = True
        break

    draft = _call(model, build_revise_prompt(TOPIC, draft, opinions), model_name)
    print(f"   ↳ 写手重写：{draft[:60]}...\n")

if not passed:
    print(f"{MAX_ROUNDS} 轮都没给通过，拿最后一稿交差（护栏兜底）：\n{draft}")
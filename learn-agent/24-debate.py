# 多 Agent 专项演示：辩论/评审团模式（模式 C）
#
# 你抛一个面试题，三个专家（原理官 / 工程官 / 面试官）各答一遍，
# 主席收齐汇总成一份「面试满分答案」+ 常见追问。
#
# 带 --fake 用假剧本离线跑（一分钱不花）；不带参数连真 API。
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
from agent_loop import FakeModel, FakeResponse, text_block
from multi_agent import Agent
from ops_debate import (
    CHAIR_SYSTEM, EXPERT_SYSTEMS, EXPERT_LABELS,
    run_debate,
)

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

QUESTION = "讲一下 RAG 是怎么实现的"


def make_fake_agents():
    """主席 + 三个专家，剧本各演一句——三个专家被问的是同一道题。"""
    def one(system, text):
        return Agent("x", system, FakeModel([FakeResponse("end_turn", [text_block(text)])]))
    experts = {
        "theory": one(EXPERT_SYSTEMS["theory"],
            "原理：RAG = 检索增强生成。为什么：模型不懂你的私有资料，又不能重训。"
            "怎么工作：资料先切块，提问时检索最相关的几块拼进 prompt 再回答——三步：切块 → 检索 → 拼接。"),
        "eng": one(EXPERT_SYSTEMS["eng"],
            "实现：chunk_text 切块（200 字）、retrieve_top_k 检索（关键词打分，进阶换向量）、"
            "把资料塞进问题前面。坑：停用字要过滤；检索不到不硬塞，让模型如实说不知道。"),
        "interviewer": one(EXPERT_SYSTEMS["interviewer"],
            "面试官想听：①为什么需要 RAG（幻觉 / 私有资料）；②三步流程；③进阶向量检索（同义词）；"
            "④成本与边界。加分：提到 min_sim 阈值和优雅降级。追问：番茄搜西红柿怎么解？查不到怎么办？"),
    }
    chair = Agent("chair", CHAIR_SYSTEM, FakeModel([FakeResponse("end_turn", [text_block(
        "# 满分答案\n## 一句话版\nRAG 先在自己资料里检索最相关的几段，再拼进 prompt 让模型回答，"
        "解决模型不懂私有资料的问题。\n## 详细版\n三步：切块（200 字）→ 检索（关键词/向量，停用字过滤）"
        "→ 拼接问答（资料在问题前）。查不到不硬塞，让模型说不知道。\n"
        "## 常见追问\n① 番茄搜西红柿怎么解？（向量检索，同义词语义召回）\n"
        "② 查不到怎么办？（不硬塞，如实说不知道）\n③ 成本？"
    )])]))
    return chair, experts


def make_real_agents():
    import anthropic
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    experts = {name: Agent(EXPERT_LABELS[name], system, client, model)
               for name, system in EXPERT_SYSTEMS.items()}
    chair = Agent("主席", CHAIR_SYSTEM, client, model)
    return chair, experts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true", help="离线用假剧本，不花钱")
    args = parser.parse_args()

    chair, experts = make_fake_agents() if args.fake else make_real_agents()
    print(f"面试题：{QUESTION}\n")

    result = run_debate(chair, experts, QUESTION)
    if not result["ok"]:
        print("⛔ 主席没说上话，汇总出不来。")
        return

    print("【三位专家各自发言（同一道题，三个角度）】")
    for key in EXPERT_LABELS:
        print(f"  - {EXPERT_LABELS[key]}：{result['answers'][key]}")
    print("\n【主席汇总 → 面试满分答案】")
    print(result["summary"])
    print('\n  一句话收尾：同一道题换角度答，主席汇总取长补短——自己答自己评，最容易吹。')


if __name__ == "__main__":
    main()

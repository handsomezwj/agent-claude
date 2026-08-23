# 第十六课：RAG 检索增强——提问前先在你自己的资料库里"检索最相关的几段"，
# 再连问题一起交给 AI。AI 先翻到对的那页，再回答。
# 带 --fake 用假模型跑通（一分钱不花）；不带参数连真 API。
import os
import sys
import anthropic
from pathlib import Path
from dotenv import load_dotenv
from agent_loop import FakeModel, FakeResponse, text_block
from rag import chunk_text, retrieve_top_k, answer_with_rag

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

CHUNK_SIZE = 200   # 每块多长（字符）
TOP_K = 2          # 每次挑最相关的几块


def load_knowledge():
    """读知识库（跟 agent-claude.py 共用同一个文件）"""
    path = Path(__file__).parent / "knowledge.md"
    return path.read_text(encoding="utf-8")


def fake_run():
    print("== 假模型（剧本）：一分钱不花，先看三步走 ==")
    knowledge = load_knowledge()
    chunks = chunk_text(knowledge, CHUNK_SIZE)
    print(f"  知识库 {len(knowledge)} 字 → 切成 {len(chunks)} 块")

    query = "龙井茶怎么泡？"
    context = retrieve_top_k(query, chunks, TOP_K)
    print(f"  问『{query}』→ 检索出 {len(context)} 块最相关的")
    for i, c in enumerate(context):
        print(f"    第 {i+1} 块（开头）：{c[:30]}……")

    fake = FakeModel([FakeResponse("end_turn", [text_block("资料里说龙井茶要用八十度左右的泉水泡。")])])
    answer = answer_with_rag(fake, query, context)
    print(f"  假模型回答：{answer}")

    # 坏情况：知识库里没有的，检索到 0 块
    query2 = "蟑螂"
    context2 = retrieve_top_k(query2, chunks, TOP_K)
    print(f"  问『{query2}』→ 检索出 {len(context2)} 块（知识库里没有）→ 不硬塞资料，让模型如实说不知道")


def real_run():
    print("== 真模型 ==")
    knowledge = load_knowledge()
    chunks = chunk_text(knowledge, CHUNK_SIZE)
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )
    for query in ["龙井茶怎么泡？", "杭州有什么好吃的？", "杭州的地铁方便吗？"]:
        context = retrieve_top_k(query, chunks, TOP_K)
        answer = answer_with_rag(client, query, context)
        print(f"  问『{query}』→ 检索 {len(context)} 块 → {answer[:60]}")


if __name__ == "__main__":
    fake_run()
    if len(sys.argv) > 1 and sys.argv[1] == "--fake":
        print("（--fake 模式：跳过真模型，不花钱）")
    else:
        real_run()
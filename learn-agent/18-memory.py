"""
第 21 课演示：Agent 记忆系统（记事本）

核心矛盾：模型天生失忆（第一课就说过——每次调用都是全新的脑子），
你替它记的 messages 也只活在内存里，程序一关就清零。
这课给 agent 一个"记事本"：把重要的事存进文件，下次启动还能想起来。

--fake：用假模型 + 临时文件离线演五幕（零成本）
不带参数：五幕照演，最后第 5 幕用真 API 演"两段对话之间重启"，模型真的记得
"""
import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dotenv import load_dotenv
# 真配置在上一级目录（c:\Users\zwj\.env），不是本脚本所在目录
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

import anthropic

from agent_loop import FakeModel, FakeResponse, text_block
from memory_store import MemoryStore, build_memory_prompt, extract_facts, remember_last_turn


def show(store, label="记事本现状"):
    print(f"  {label}：")
    if not store.all():
        print("    （空的）")
    for i, m in enumerate(store.all(), 1):
        print(f"    {i}. {m}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true", help="用假模型离线跑（不花 API 钱）")
    args = parser.parse_args()

    work = tempfile.mkdtemp(prefix="memory_demo_")
    path = os.path.join(work, "notebook.json")
    print(f"记事本文件：{path}\n")

    # ---------- 第 1 幕 · 记事本长什么样（增 / 查 / 存盘） ----------
    print("===== 第 1 幕 · 记事本长什么样（增 / 查 / 存文件） =====")
    store = MemoryStore(path, max_items=3)
    print(f"  加『我叫小张』 → {store.add('我叫小张')}")
    print(f"  加『我在杭州工作』 → {store.add('我在杭州工作')}")
    print(f"  加『我喜欢吃火锅』 → {store.add('我喜欢吃火锅')}")
    print(f"  重复加『我叫小张』 → {store.add('我叫小张')}（重复的不记）")
    show(store)
    store.save()
    print(f"  已存盘，文件里写了啥：\n{open(path, encoding='utf-8').read()}")
    print("  → 记事本 = 一个 JSON 文件，一条事实一行。就这么朴素。")

    # ---------- 第 2 幕 · 重启不失忆 ----------
    print("\n===== 第 2 幕 · 重启不失忆（程序关了，记事本还在） =====")
    store2 = MemoryStore(path, max_items=3)
    store2.load()   # 模拟"程序重启"：new 一个，从同一个文件读回来
    show(store2, "新实例 load() 之后")
    print("  → 第一课说模型失忆，但它现在记得你是谁了——因为记忆在文件里，不在脑子里。")

    # ---------- 第 3 幕 · 自动写记事本 ----------
    print("\n===== 第 3 幕 · 自动写记事本（从对话里抽事实） =====")
    msgs = [
        {"role": "user", "content": "我叫小张，在杭州做 AI 开发。今天天气不错。"},
        {"role": "assistant", "content": [text_block("好的小张，我记住了。")]},
    ]
    added = remember_last_turn(store2, msgs)
    print(f"  这一轮对话，自动记下 {added} 条新事实：")
    show(store2, "自动记完的记事本")
    print("  → 规则是死的：只认『我叫/我住在/我喜欢』这类句式。")
    print("  → extract_facts 的 extractor 参数是个门：将来可换 LLM 提炼，更聪明但花 token。")

    # ---------- 第 4 幕 · 记忆贴进 system prompt ----------
    print("\n===== 第 4 幕 · 把记忆贴进 system prompt（模型一开场就知道你是谁） =====")
    prompt = build_memory_prompt(store2.all())
    print("  拼出来要贴进 system prompt 的一段：")
    print("  " + prompt.replace("\n", "\n  "))
    print("  → 模型每次回答前都会先看到这段——它『记得』全在这，不靠脑子。")

    # ---------- 第 5 幕 · 两段对话之间重启 ----------
    if args.fake:
        print("\n===== 第 5 幕 · 两段对话之间重启（--fake 看机制接线，不花 API 钱） =====")
        s1 = [
            {"role": "user", "content": "我叫小张，在杭州做 AI 开发，最近在准备 agent 面试。"},
            {"role": "assistant", "content": [text_block("小张你好！我记住你啦。")]},
        ]
        added = remember_last_turn(store2, s1)
        print(f"  会话 1：用户自我介绍 → 自动记下 {added} 条：")
        show(store2, "会话 1 结束后的记事本")
        store3 = MemoryStore(path, max_items=50)
        store3.load()   # 会话 1 结束 → "程序重启"
        print("\n  『程序重启』→ 新进程从同一个文件 load 回来：")
        show(store3)
        print("\n  会话 2 只发一句话：『我们这是第一次聊天吧？你记得我吗？』")
        print("  system prompt 里被贴进记忆：")
        print("  " + build_memory_prompt(store3.all()).replace("\n", "\n  "))
        print("  → 模型『记得』的全在这一段里——这就是重启不失忆的机关。")
    else:
        print("\n===== 第 5 幕 · 两段对话之间重启（真 API，看模型真的记得） =====")
        client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        )
        model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
        base_system = "你是 lcc，一个耐心的学习伙伴，用中文回答，保持简洁。"

        # 会话 1：自我介绍 → 真模型回答 → 自动记下事实
        s1 = [{"role": "user", "content": "我叫小张，在杭州做 AI 开发，最近在准备 agent 面试。"}]
        r1 = client.messages.create(model=model, max_tokens=300, system=base_system, messages=s1)
        reply1 = "".join(b.text for b in r1.content if getattr(b, "type", None) == "text")
        print(f"  会话 1 agent 答：{reply1[:80]}")
        remember_last_turn(
            store2,
            s1 + [{"role": "assistant", "content": [text_block(reply1)]}],
        )
        store3 = MemoryStore(path, max_items=50)
        store3.load()   # 会话 1 结束 → "程序重启"
        print(f"\n  『程序重启』→ 记事本：{store3.all()}")

        # 会话 2：只发一句话，system 里带上记忆 → 看它真记得
        s2 = [{"role": "user", "content": "我们这是第一次聊天吧？你记得我叫什么、在做什么、为什么准备面试吗？"}]
        r2 = client.messages.create(
            model=model,
            max_tokens=300,
            system=base_system + "\n\n" + build_memory_prompt(store3.all()),
            messages=s2,
        )
        reply2 = "".join(b.text for b in r2.content if getattr(b, "type", None) == "text")
        print(f"  会话 2 agent 答：{reply2}")
        print("  → 注意：会话 2 只有一句话 + 记事本——它『记得』全靠文件，不靠脑子。")


if __name__ == "__main__":
    main()

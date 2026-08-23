# 第十四课：流式输出——真模型"边生成边吐字"，打字机效果。
# 带 --fake 用假流跑通（一分钱不花）；不带参数连真 API。
import os
import sys
import time
import anthropic
from dotenv import load_dotenv
from agent_loop import FakeResponse, FakeStream, text_block, tool_block
from streaming import run_stream

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))


def typewriter(text):
    """打字机：吐一块就打印一块，不换行，立即刷屏"""
    print(text, end="", flush=True)


def fake_typewriter(text):
    """假流版打字机：打印 + 慢半拍，把"边生成边吐"演得更像"""
    typewriter(text)
    time.sleep(0.03)


def fake_run():
    print("== 假流（剧本）：一分钱不花，先看打字机效果 ==")

    # 剧本 1：正常问答——一段长回答切成小片，模拟"边生成边吐字"
    script = FakeResponse("end_turn", [
        text_block("你好，我是 lcc。这是一条很长的回答，用来演示打字机效果。")
    ])
    print("AI：", end="")
    reply, final = run_stream(lambda: FakeStream(script, chunk_size=2), on_chunk=fake_typewriter)
    print(f"\n  拼起来：'{reply}'（{len(reply)} 字）；stop_reason={final.stop_reason}")

    # 剧本 2：工具循环——没有文字块，吐不出字，但 stop_reason 照常传回
    script2 = FakeResponse("tool_use", [tool_block("load_skill", {"skill_name": "python"})])
    reply2, final2 = run_stream(lambda: FakeStream(script2, chunk_size=2), on_chunk=typewriter)
    print(f"  工具循环：文字碎片空；stop_reason={final2.stop_reason} → 护栏逻辑照走，不用改")


def real_run():
    print("== 真流式 ==")
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )
    kwargs = dict(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"),
        max_tokens=300,
        messages=[{"role": "user", "content": "用三句话介绍一下你自己，最后讲一个冷笑话。"}],
    )
    print("AI：", end="")
    reply, final = run_stream(lambda: client.messages.stream(**kwargs), on_chunk=typewriter)
    print(f"\n  完整回答 {len(reply)} 字；stop_reason={final.stop_reason}")


if __name__ == "__main__":
    fake_run()
    if len(sys.argv) > 1 and sys.argv[1] == "--fake":
        print("（--fake 模式：跳过真模型，不花钱）")
    else:
        real_run()

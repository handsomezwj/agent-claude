# 第四课：更聪明的护栏——识别"原地打转"
import os
import anthropic
from dotenv import load_dotenv
from spin_guard import make_fingerprint, track_repeat
from agent_tools import run_tool
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
)
model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")

MAX_ITERS = 5      # 兜底：最多 5 圈
MAX_REPEATS = 3    # 聪明：同一道菜连点 3 次 = 打转

TOOLS = [
    {
        "name": "get_weather",
        "description": "查询某个城市的天气。当用户问天气时使用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名"},
            },
            "required": ["city"],
        },
    },
]

history = []

while True:
    user = input("你：")
    if not user.strip():
        continue
    history.append({"role": "user", "content": user})

    turn = 0
    last_call = None     # ← 记下"上一道菜"长什么样
    repeat_count = 0     # ← 记下"同一道菜连点了几次"
    while True:
        turn += 1
        if turn > MAX_ITERS:   # 兜底护栏
            print("AI：我绕不出来了，请换个说法再试。")
            break

        resp = client.messages.create(
            model=model,
            max_tokens=1000,
            tools=TOOLS,
            messages=history,
        )

        if resp.stop_reason == "tool_use":
            history.append({"role": "assistant", "content": resp.content})

            results = []
            stuck = False   # ← 这一圈有没有"打转"的标记
            for block in resp.content:
                if block.type == "tool_use":
                    # 打转判断交给"被测试过"的函数，一行搞定
                    this_call = make_fingerprint(block.name, block.input)
                    repeat_count, stuck_now = track_repeat(
                        last_call, repeat_count, this_call, MAX_REPEATS
                    )
                    last_call = this_call

                    if stuck_now:
                        print(f"  [检测到打转] 连续 {MAX_REPEATS} 次调用同一工具：{block.name}")
                        stuck = True
                        break

                    result = run_tool(block.name, block.input)
                    print(f"  [执行工具] {block.name}({block.input}) -> {result}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            if stuck:   # 打转 → 不把结果喂回去，直接刹车
                print("AI：我在原地打转，请换个说法再试。")
                break

            history.append({"role": "user", "content": results})

        else:
            answer = "".join(b.text for b in resp.content if b.type == "text")
            print("AI：", answer)
            history.append({"role": "assistant", "content": resp.content})
            break

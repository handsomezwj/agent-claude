# 第三课：护栏——防止模型永远点菜不回答
import os
import anthropic
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
)
model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")

MAX_ITERS = 5   # ← 护栏：最多让模型连续点菜 5 次，再点就强制停

def get_weather(city: str) -> str:
    fake = {"北京": "晴，32°C", "上海": "小雨，28°C", "广州": "多云，30°C"}
    return fake.get(city, f"暂无 {city} 的天气数据")

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

def run_tool(name: str, args: dict) -> str:
    if name == "get_weather":
        return get_weather(args["city"])
    return f"没有这个工具：{name}"

history = []

while True:
    user = input("你：")
    if not user.strip():
        continue
    history.append({"role": "user", "content": user})

    # 内层循环，这次带护栏
    turn = 0   # ← 从 0 开始数，每转一圈 +1
    while True:
        turn += 1
        if turn > MAX_ITERS:   # ← 护栏在这里：转太多次，强制停
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
            for block in resp.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input)
                    print(f"  [执行工具] {block.name}({block.input}) -> {result}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            history.append({"role": "user", "content": results})

        else:
            answer = "".join(b.text for b in resp.content if b.type == "text")
            print("AI：", answer)
            history.append({"role": "assistant", "content": resp.content})
            break

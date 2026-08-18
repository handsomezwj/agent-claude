# 第七课：重构——把"验证过的逻辑"插回去
#
# 04 里的打转判断，上节课已经被抽成了 spin_guard.py 里的两个纯函数，
# 并且用 test_spin_property.py 用 500 个随机序列证明了规则是对的。
# 这节课把它插回循环里：程序跑的还是一模一样的判断，但代码更短、
# 更不容易写错，而且"规则"只存在于一个地方。
import os
import anthropic
from dotenv import load_dotenv

# ★ 本课唯一的新增：不自己写判断，从 spin_guard 导入。
#   注意：这些函数已经被测试过了，是"可信的零件"。
from spin_guard import make_fingerprint, track_repeat

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
)
model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")

MAX_ITERS = 5      # 兜底：最多 5 圈
MAX_REPEATS = 3    # 聪明：同一道菜连点 3 次 = 打转

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

    turn = 0
    last_call = None     # 上一道菜的指纹
    repeat_count = 0     # 同一道菜连点了几次
    while True:
        turn += 1
        if turn > MAX_ITERS:   # 兜底护栏（没动，还是原来的）
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
            stuck = False
            for block in resp.content:
                if block.type == "tool_use":
                    # ① 指纹：不再自己写 (name, str(sorted(...)))，交给函数
                    this_call = make_fingerprint(block.name, block.input)

                    # ② 连数计算 + 打转判断：不再自己写 if/else，交给函数
                    #    （返回 (新连数, 是否打转)，和 04 里那几行 if 完全等价）
                    repeat_count, stuck = track_repeat(
                        last_call, repeat_count, this_call, MAX_REPEATS
                    )
                    last_call = this_call

                    if stuck:   # 连数超过阈值 → 刹车
                        print(f"  [检测到打转] 连续 {MAX_REPEATS} 次调用同一工具：{block.name}")
                        break

                    result = run_tool(block.name, block.input)
                    print(f"  [执行工具] {block.name}({block.input}) -> {result}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            if stuck:
                print("AI：我在原地打转，请换个说法再试。")
                break

            history.append({"role": "user", "content": results})

        else:
            answer = "".join(b.text for b in resp.content if b.type == "text")
            print("AI：", answer)
            history.append({"role": "assistant", "content": resp.content})
            break

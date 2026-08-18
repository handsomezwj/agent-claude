# 第二课：给 AI 装一只手（工具调用循环）
import os
import anthropic
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
)
model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")

# ---- 定义一只"手"：查天气（演示用，用假数据）----
def get_weather(city: str) -> str:
    fake = {"北京": "晴，32°C", "上海": "小雨，28°C", "广州": "多云，30°C"}
    return fake.get(city, f"暂无 {city} 的天气数据")

# ---- 给模型的"手说明书"：这只手长什么样、接受什么参数 ----
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
    """你的程序替模型执行工具"""
    if name == "get_weather":
        return get_weather(args["city"])
    return f"没有这个工具：{name}"

history = []

while True:
    user = input("你：")
    if not user.strip():
        continue
    history.append({"role": "user", "content": user})

    # ---- 内层循环：打电话 → 看 stop_reason → 决定继续还是停下 ----
    while True:
        resp = client.messages.create(
            model=model,
            max_tokens=1000,
            tools=TOOLS,          # 把"手说明书"交给模型
            messages=history,
        )

        if resp.stop_reason == "tool_use":
            # 模型说："我要用手！"——注意它没有回答，只说想用哪个工具
            # ① 必须把这句话原样记下来（协议要求，不能只记文字）
            history.append({"role": "assistant", "content": resp.content})

            # ② 你的程序替它执行每个工具
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input)
                    print(f"  [执行工具] {block.name}({block.input}) -> {result}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,   # 相当于"回执编号"，对上号
                        "content": result,
                    })

            # ③ 把结果念给模型听（放进记录，再打一次电话）
            history.append({"role": "user", "content": results})
            # ④ 回到循环顶部 → 模型这次看完结果，就会真的回答

        else:
            # 模型直接回答了（stop_reason == "end_turn"）
            answer = "".join(b.text for b in resp.content if b.type == "text")
            print("AI：", answer)
            history.append({"role": "assistant", "content": resp.content})
            break

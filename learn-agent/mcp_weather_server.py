# 一个最小的 MCP 服务器：假装会查天气，天气数据写死在代码里。
#
# 它住在一个独立进程里，从标准输入一行一行读 JSON-RPC 请求，
# 在标准输出一行一行回答。agent（客户端）启动它、问它要工具、喊它执行。
#
# 它真的符合 MCP 协议：initialize → tools/list → tools/call，一个不落。
# 看懂这个文件，你就看懂了"MCP 服务器"到底是个什么东西。
import json
import sys

# Windows 下强制用 UTF-8 读写管道，不然中文会变乱码
# 注意：reconfigure() 是"就地改"，不返回值，别用 = 接住
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 这个服务器提供的工具清单：现在只有一个"查天气"
TOOLS = [
    {
        "name": "get_weather",
        "description": "查某个城市的天气",
        "inputSchema": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名，比如 杭州"}},
            "required": ["city"],
        },
    }
]

# "数据库"：写死的天气数据（假装联网查的）
WEATHER = {"杭州": "晴，28 度", "北京": "多云，22 度", "上海": "小雨，26 度"}


def handle(msg):
    """看请求说的是什么，返回对应的结果。"""
    method = msg.get("method")
    if method == "initialize":
        # 握手：告诉客户端"我支持什么、我是谁"
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "weather", "version": "1.0.0"},
        }
    if method == "tools/list":
        # 有人问"你有什么工具" → 把清单给他
        return {"tools": TOOLS}
    if method == "tools/call":
        # 有人喊"帮我执行工具" → 查"数据库"回答
        args = msg.get("params", {}).get("arguments", {})
        city = args.get("city", "杭州")
        text = WEATHER.get(city, f"没有「{city}」的天气数据")
        return {"content": [{"type": "text", "text": text}]}
    return {}


def main():
    # 一直接收请求，直到没人说话（管道关闭）为止
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        # 只回"带编号的请求"；不带编号的是通知，不用回
        if "id" in msg:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg)}
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

# 第十五课：MCP 工具接入——不自己写死工具，而是问一个"独立小程序"要工具。
# 带 --fake 用假门（剧本）跑通，一分钱不花；
# 不带参数启动迷你天气服务器（也是本机代码），真走一遍 JSON-RPC。
import os
import sys
from mcp_client import McpClient, FakeTransport, StdioTransport

# 假门剧本：一个会查天气的"服务器"，被问时直接照剧本回答
FAKE_RESULTS = {
    "initialize": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
    "tools/list": {"tools": [
        {"name": "get_weather", "description": "查城市天气",
         "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}}},
    ]},
    "tools/call": {"content": [{"type": "text", "text": "杭州：晴，28 度"}]},
}


def fake_run():
    print("== 假门（剧本）：一分钱不花，先看流程 ==")
    client = McpClient(FakeTransport(FAKE_RESULTS))
    client.handshake()
    tools = client.list_tools()
    print(f"  问服务器要工具 → 它说：{[t['name'] for t in tools]}")
    text = client.call_tool("get_weather", {"city": "杭州"})
    print(f"  喊它执行 get_weather(杭州) → {text}")
    print("  下面换真门：启动迷你天气服务器，真实走一遍 JSON-RPC。")


def real_run():
    print("== 真门（迷你天气服务器，本机进程）==")
    server = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_weather_server.py")
    command = f'"{sys.executable}" "{server}"'
    client = McpClient(StdioTransport(command))
    client.handshake()
    tools = client.list_tools()
    print(f"  服务器有 {len(tools)} 个工具：{[t['name'] for t in tools]}")
    for city in ["杭州", "北京", "成都"]:
        text = client.call_tool("get_weather", {"city": city})
        print(f"  get_weather({city}) → {text}")
    client.close()
    print("  查完了，关掉服务器进程。")


if __name__ == "__main__":
    fake_run()
    if len(sys.argv) > 1 and sys.argv[1] == "--fake":
        print("（--fake 模式：跳过真门，不启动进程）")
    else:
        real_run()

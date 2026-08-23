# 被测对象：MCP 客户端——工具不住在你家，住在一个"独立小程序"里，你去问它要。
#
# 以前（前面所有课）：工具写死在 agent 代码里（agent-claude.py 的 TOOLS 列表）。
#   想加一个工具 = 改代码、重新上线。工具跟 agent 绑死了。
# 现在（MCP，Model Context Protocol 的套路）：工具住在一个单独的程序里，
#   那个程序叫【MCP 服务器】。agent 启动时问它："你有什么工具？"
#   要用时喊它："帮我执行这个工具。" 想加工具 = 加一个服务器，agent 代码一行不改。
#
# 对话方式：JSON-RPC 2.0——一行一行 JSON 消息，从标准输入/输出进出（stdio）。
#
# 核心心法（还是老规矩）：给"外部系统"开一个门（transport）。
#   真门 = 启动服务器子进程；假门 = 按剧本回答，一分钱不花。
#   门后面是真是假，McpClient 自己不知道，也不用知道。
import json
import subprocess


# ---------------------- 纯函数：协议怎么说话（可测） ----------------------

def encode_request(req_id, method, params=None):
    """把"问一个问题"包成一行 JSON-RPC 消息。纯函数，可测。"""
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg, ensure_ascii=False)


def decode_response(line):
    """把服务器回的一行 JSON 拆开。纯函数，可测。"""
    return json.loads(line)


def normalize_tools(raw_tools):
    """把 MCP 服务器给的工具描述，翻译成 agent 认的格式。纯函数，可测。

    翻译表：服务器说 inputSchema（JSON Schema 格式）→ agent 认 input_schema。
    name/description 两边叫法一样，直接搬。
    """
    return [
        {
            "name": t.get("name"),
            "description": t.get("description", ""),
            "input_schema": t.get("inputSchema", {"type": "object", "properties": {}}),
        }
        for t in raw_tools
    ]


def result_to_text(result):
    """把 MCP 工具调用的结果摊成一段纯文字。纯函数，可测。

    结果是一堆"内容块"（可能有文字、图片、资源），这里只捡文字块。
    图片那些先不管——老规矩，优雅降级，有用的先捡走。
    """
    parts = [b["text"] for b in result.get("content", []) if b.get("type") == "text"]
    if result.get("isError"):
        parts.append("（工具执行报错）")
    return "\n".join(parts)


# ---------------------- 门（transport）：真门 / 假门 ----------------------

class StdioTransport:
    """真门：启动一个 MCP 服务器进程，跟它通过标准输入/输出一行一行说话。"""
    def __init__(self, command):
        self._proc = subprocess.Popen(
            command, shell=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        self._next_id = 1

    def request(self, method, params=None):
        """发一条请求（带编号），等服务器回相同编号的那一行，把 result 还给你。"""
        req_id = self._next_id
        self._next_id += 1
        self._proc.stdin.write(encode_request(req_id, method, params) + "\n")
        self._proc.stdin.flush()
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            msg = decode_response(line)
            if msg.get("id") == req_id:          # 编号对上了才是这一问的回答
                return msg.get("result", {})
        return {}                                # 服务器没回（比如崩了），给个空结果

    def close(self):
        self._proc.terminate()


class FakeTransport:
    """假门：不启动进程，按剧本回答。剧本 = {方法名: 结果} 一个字典。

    跟真门接口一模一样，所以 McpClient 一行不改——
    老规矩，给外部系统开个门，门后真假都能进。
    """
    def __init__(self, results):
        self.results = dict(results)
        self.calls = []                          # 记下每次被问了什么，测试用

    def request(self, method, params=None):
        self.calls.append((method, params))
        return self.results.get(method, {})

    def close(self):
        pass


# ---------------------- 客户端：握手 → 发现 → 调用 ----------------------

class McpClient:
    """MCP 客户端。门后面是真是假都能进。"""
    def __init__(self, transport):
        self._transport = transport

    def handshake(self):
        """见面先握手：告诉服务器"我是谁"。真协议还会发一条 initialized 通知，
        我们的迷你服务器不要求，就省了。"""
        self._transport.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "learn-agent", "version": "1.0.0"},
        })

    def list_tools(self):
        """发现：问服务器"你有什么工具？" 返回翻译成 agent 格式的清单。"""
        raw = self._transport.request("tools/list", {})
        return normalize_tools(raw.get("tools", []))

    def call_tool(self, name, args=None):
        """调用：喊服务器"帮我执行这个工具"。返回一段纯文字结果。"""
        result = self._transport.request("tools/call", {
            "name": name,
            "arguments": args or {},
        })
        return result_to_text(result)

    def close(self):
        self._transport.close()

# 第十五课 eval：测 MCP 客户端——协议拼装（纯函数）+ 假门跑通 + 调用顺序。
import unittest
from mcp_client import (
    McpClient, FakeTransport,
    encode_request, decode_response, normalize_tools, result_to_text,
)


class TestProtocol(unittest.TestCase):
    """测"协议怎么说话"这些纯函数"""

    def test_encode_request_roundtrip(self):
        # 拼出来的一行，能拆回原来的消息
        line = encode_request(3, "tools/list", {})
        msg = decode_response(line)
        self.assertEqual(msg["id"], 3)
        self.assertEqual(msg["method"], "tools/list")
        self.assertEqual(msg["jsonrpc"], "2.0")

    def test_encode_without_params_omits_key(self):
        self.assertNotIn('"params"', encode_request(1, "initialize"))


class TestNormalizeTools(unittest.TestCase):
    """测"翻译"：MCP 的 inputSchema → agent 的 input_schema"""

    def test_renames_input_schema(self):
        raw = [{"name": "get_weather", "description": "查天气",
                "inputSchema": {"type": "object", "properties": {}}}]
        tools = normalize_tools(raw)
        self.assertEqual(tools[0]["name"], "get_weather")
        self.assertIn("input_schema", tools[0])
        self.assertNotIn("inputSchema", tools[0])

    def test_missing_fields_get_defaults(self):
        # 服务器偷懒只给个名字，翻译也要补出默认值，不能崩
        tools = normalize_tools([{"name": "only_name"}])
        self.assertEqual(tools[0]["description"], "")
        self.assertEqual(tools[0]["input_schema"], {"type": "object", "properties": {}})


class TestResultToText(unittest.TestCase):
    """测"结果摊平"：一堆内容块 → 一段纯文字"""

    def test_text_blocks_join(self):
        result = {"content": [{"type": "text", "text": "晴，28 度"}]}
        self.assertEqual(result_to_text(result), "晴，28 度")

    def test_is_error_appends_note(self):
        result = {"isError": True, "content": [{"type": "text", "text": "城市不存在"}]}
        self.assertEqual(result_to_text(result), "城市不存在\n（工具执行报错）")

    def test_no_text_returns_empty(self):
        self.assertEqual(result_to_text({"content": []}), "")


class TestMcpClient(unittest.TestCase):
    """测流程：握手 → 发现 → 调用；假门记下问过什么"""

    def test_list_tools_returns_normalized(self):
        client = McpClient(FakeTransport({
            "tools/list": {"tools": [{"name": "get_weather", "description": "查天气"}]},
        }))
        tools = client.list_tools()
        self.assertEqual(tools[0]["name"], "get_weather")
        self.assertIn("input_schema", tools[0])

    def test_call_tool_returns_text(self):
        client = McpClient(FakeTransport({
            "tools/call": {"content": [{"type": "text", "text": "晴，28 度"}]},
        }))
        self.assertEqual(client.call_tool("get_weather", {"city": "杭州"}), "晴，28 度")

    def test_handshake_then_list_then_call_order(self):
        # 剧本故意不给 tools/list 结果（返回空），但顺序必须对
        t = FakeTransport({
            "initialize": {},
            "tools/list": {"tools": []},
            "tools/call": {"content": [{"type": "text", "text": "hi"}]},
        })
        client = McpClient(t)
        client.handshake()
        client.list_tools()
        client.call_tool("ping")
        methods = [c[0] for c in t.calls]
        self.assertEqual(methods, ["initialize", "tools/list", "tools/call"])


if __name__ == "__main__":
    unittest.main()

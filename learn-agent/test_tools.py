# eval：让程序自己验证 agent 的"零件"对不对
# 运行方式：python test_tools.py
import unittest
from agent_tools import get_weather, run_tool


class TestWeatherTool(unittest.TestCase):

    def test_known_city(self):
        """输入: 北京 → 期望: 晴，32°C"""
        self.assertEqual(
            run_tool("get_weather", {"city": "北京"}),
            "晴，32°C",
        )

    def test_unknown_city(self):
        """输入: 火星 → 期望: 返回默认提示"""
        self.assertEqual(
            run_tool("get_weather", {"city": "火星"}),
            "暂无 火星 的天气数据",
        )

    def test_unknown_tool(self):
        """输入: 不存在的工具 → 期望: 报错提示"""
        self.assertEqual(
            run_tool("bad_tool", {}),
            "没有这个工具：bad_tool",
        )


if __name__ == "__main__":
    unittest.main()

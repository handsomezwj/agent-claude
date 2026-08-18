# 第八课的 eval：测整个循环——从"测手"升级到"测整条手臂"
import unittest
from agent_loop import FakeModel, FakeResponse, tool_block, text_block, handle_turn


class TestLoop(unittest.TestCase):
    def test_normal_answer(self):
        model = FakeModel([FakeResponse("end_turn", [text_block("你好")])])
        self.assertEqual(handle_turn(model, "hi", []), "ANSWER:你好")

    def test_tool_then_answer(self):
        model = FakeModel([
            FakeResponse("tool_use", [tool_block("get_weather", {"city": "北京"})]),
            FakeResponse("end_turn", [text_block("北京晴")]),
        ])
        self.assertEqual(handle_turn(model, "天气", []), "ANSWER:北京晴")
        self.assertEqual(model.calls, 2)   # 调 2 次：一次点菜，一次回答

    def test_spin_guard_brakes(self):
        # 连点 3 次同样的工具 → 第 3 次就刹车，不用等第 4 次
        model = FakeModel([
            FakeResponse("tool_use", [tool_block("get_weather", {"city": "北京"})]) for _ in range(3)
        ])
        self.assertEqual(handle_turn(model, "查", []), "STUCK")
        self.assertEqual(model.calls, 3)

    def test_max_iters_brakes(self):
        # 每次换城市 → 不打转，5 圈后兜底，第 6 圈检查就拦住
        model = FakeModel([
            FakeResponse("tool_use", [tool_block("get_weather", {"city": c})])
            for c in ["北京", "上海", "广州", "深圳", "武汉"]
        ])
        self.assertEqual(handle_turn(model, "查", []), "MAX_ITERS")
        self.assertEqual(model.calls, 5)

    def test_script_too_short_raises(self):
        # 剧本只有 1 句，循环却要调第 2 次 → 假模型报错，当场抓出"剧本没写够"
        model = FakeModel([FakeResponse("tool_use", [tool_block("get_weather", {"city": "北京"})])])
        with self.assertRaises(RuntimeError):
            handle_turn(model, "查", [])


if __name__ == "__main__":
    unittest.main()

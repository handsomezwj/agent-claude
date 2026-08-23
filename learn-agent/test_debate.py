# 第 13 课 eval：测评审模式的纯函数 + 全流程（假模型演戏，零成本）
import unittest

from agent_loop import FakeModel, FakeResponse, text_block
from debate import (
    build_critic_prompt,
    build_draft_prompt,
    build_revise_prompt,
    parse_critic,
    run_debate,
)


class TestParseCritic(unittest.TestCase):
    """测解析：抠结论 + 意见"""

    def test_pass(self):
        self.assertEqual(parse_critic("【结论】通过\n【意见】无"), ("通过", "无"))

    def test_revise_with_opinions(self):
        verdict, opinions = parse_critic(
            "【结论】需改\n【意见】1. 太空泛\n2. 没量化\n【被审内容】x"
        )
        self.assertEqual(verdict, "需改")
        self.assertIn("太空泛", opinions)

    def test_no_verdict_defaults_to_revise(self):
        # 评审跑飞格式 → 保守判"需改"，不放行
        verdict, _ = parse_critic("评审：我觉得还行吧")
        self.assertEqual(verdict, "需改")

    def test_pass_ignores_extra_text(self):
        verdict, opinions = parse_critic("废话【结论】通过【意见】无【被审内容】x")
        self.assertEqual(verdict, "通过")
        self.assertEqual(opinions, "无")


class TestPrompts(unittest.TestCase):
    """测 prompt 构造：主题得进指令"""

    def test_draft_contains_topic(self):
        self.assertIn("自我介绍", build_draft_prompt("自我介绍"))

    def test_critic_contains_draft(self):
        self.assertIn("这是草稿", build_critic_prompt("主题", "这是草稿"))

    def test_revise_contains_both(self):
        p = build_revise_prompt("主题", "原稿", "意见1")
        self.assertIn("原稿", p)
        self.assertIn("意见1", p)


class TestRunDebate(unittest.TestCase):
    """测全流程：假模型演戏，免费看协作"""

    def test_passes_on_third_round(self):
        # 剧本：草稿 → 需改+改 → 需改+改 → 通过（第 3 轮放行）
        model = FakeModel([
            FakeResponse("end_turn", [text_block("第一稿")]),
            FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 太泛\n【被审内容】x")]),
            FakeResponse("end_turn", [text_block("第二稿：加了项目")]),
            FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 缺 RAG\n【被审内容】x")]),
            FakeResponse("end_turn", [text_block("第三稿：加了 RAG")]),
            FakeResponse("end_turn", [text_block("【结论】通过\n【意见】无\n【被审内容】x")]),
        ])
        r = run_debate(model, "自我介绍", max_rounds=3)
        self.assertTrue(r["ok"])
        self.assertTrue(r["passed"])
        self.assertEqual(r["rounds"], 3)
        self.assertIn("RAG", r["text"])

    def test_max_rounds_backstop(self):
        # 评审永远需改 → 兜底结束，不崩，passed=False
        model = FakeModel([
            FakeResponse("end_turn", [text_block("第一稿")]),
            FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 再改\n【被审内容】x")]),
            FakeResponse("end_turn", [text_block("改一次")]),
            FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 再改\n【被审内容】x")]),
            FakeResponse("end_turn", [text_block("改两次")]),
        ])
        r = run_debate(model, "x", max_rounds=2)
        self.assertTrue(r["ok"])
        self.assertFalse(r["passed"])
        self.assertEqual(r["rounds"], 2)
        self.assertIn("改两次", r["text"])

    def test_empty_first_draft_degrades(self):
        # 第一稿就是空的 → 降级：ok=False，不崩
        model = FakeModel([FakeResponse("end_turn", [text_block("")])])
        r = run_debate(model, "x")
        self.assertFalse(r["ok"])
        self.assertIsNone(r["text"])

    def test_critic_fails_returns_draft(self):
        # 评审中途挂掉 → 拿当前稿交差，passed=False 但 ok=True
        model = FakeModel([
            FakeResponse("end_turn", [text_block("第一稿")]),
            FakeResponse("end_turn", [text_block("")]),   # 评审空输出
        ])
        r = run_debate(model, "x")
        self.assertTrue(r["ok"])
        self.assertFalse(r["passed"])
        self.assertEqual(r["text"], "第一稿")


if __name__ == "__main__":
    unittest.main()
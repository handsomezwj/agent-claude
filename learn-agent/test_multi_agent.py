# 第 19 课 eval：测双脑 Agent + 协调器（假模型演戏，零成本）
import unittest

from agent_loop import FakeModel, FakeResponse, text_block
from multi_agent import (
    WRITER_SYSTEM,
    REVIEWER_SYSTEM,
    Agent,
    build_draft_prompt,
    build_review_prompt,
    build_revise_prompt,
    parse_review,
    run_collab,
)


class BoomModel:
    """假模型：一调就炸。测优雅降级——ask 必须返回 None，绝不抛给协调器。"""

    def __init__(self):
        self.calls = 0

    @property
    def messages(self):
        class _M:
            def __init__(self, owner):
                self.owner = owner

            def create(self, **kwargs):
                self.owner.calls += 1
                raise RuntimeError("boom")

        return _M(self)


class TestAgentMemory(unittest.TestCase):
    """测 Agent：门 + 各记各的账"""

    def test_ask_returns_text_and_records_memory(self):
        a = Agent("写手", WRITER_SYSTEM,
                  FakeModel([FakeResponse("end_turn", [text_block("你好")])]))
        self.assertEqual(a.ask("在吗"), "你好")
        hist = a.history()
        self.assertEqual(len(hist), 2)                       # 你说 + 它回
        self.assertEqual(hist[0], {"role": "user", "content": "在吗"})
        self.assertEqual(hist[1], {"role": "assistant", "content": "你好"})

    def test_memory_is_own(self):
        # 两个 Agent 各记各的账，互不污染
        w = Agent("写手", WRITER_SYSTEM,
                  FakeModel([FakeResponse("end_turn", [text_block("稿子")])]))
        r = Agent("评审", REVIEWER_SYSTEM,
                  FakeModel([FakeResponse("end_turn", [text_block("挑刺")])]))
        w.ask("写个稿")
        r.ask("审一下")
        self.assertEqual(len(w.history()), 2)
        self.assertEqual(len(r.history()), 2)
        # 写手的记忆里绝没有评审那句「审一下」
        w_contents = [m["content"] for m in w.history()]
        self.assertNotIn("审一下", w_contents)

    def test_ask_failure_degrades(self):
        # 模型一调就炸 → ask 返回 None，记忆里只留"问了"，不留"答了"，不崩
        a = Agent("写手", WRITER_SYSTEM, BoomModel())
        self.assertIsNone(a.ask("在吗"))
        hist = a.history()
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["role"], "user")
        self.assertEqual(a.calls, 1)


class TestParseReview(unittest.TestCase):
    """测解析：抠结论 + 意见"""

    def test_pass(self):
        self.assertEqual(parse_review("【结论】通过\n【意见】无"), ("通过", "无"))

    def test_revise_with_opinions(self):
        verdict, opinions = parse_review(
            "【结论】需改\n【意见】1. 太空泛\n2. 没量化\n【被审内容】x"
        )
        self.assertEqual(verdict, "需改")
        self.assertIn("太空泛", opinions)

    def test_no_verdict_defaults_to_revise(self):
        # 评审跑飞格式 → 保守判"需改"，不放行
        verdict, _ = parse_review("评审：我觉得还行吧")
        self.assertEqual(verdict, "需改")

    def test_pass_ignores_extra_text(self):
        verdict, opinions = parse_review("废话【结论】通过【意见】无【被审内容】x")
        self.assertEqual(verdict, "通过")
        self.assertEqual(opinions, "无")


class TestPrompts(unittest.TestCase):
    """测 prompt 构造：任务/稿子/意见得各就各位"""

    def test_draft_contains_task(self):
        self.assertIn("自我介绍", build_draft_prompt("自我介绍"))

    def test_review_contains_draft(self):
        self.assertIn("这是草稿", build_review_prompt("主题", "这是草稿"))

    def test_revise_contains_both(self):
        p = build_revise_prompt("主题", "原稿", "意见1")
        self.assertIn("原稿", p)
        self.assertIn("意见1", p)


class TestRunCollab(unittest.TestCase):
    """测协调器全流程：假模型双脑演戏，免费看协作"""

    def _make(self, writer_script, reviewer_script):
        w = Agent("写手", WRITER_SYSTEM, FakeModel(writer_script))
        r = Agent("评审", REVIEWER_SYSTEM, FakeModel(reviewer_script))
        return w, r

    def test_passes_after_one_revision(self):
        w, r = self._make(
            [FakeResponse("end_turn", [text_block("第一稿")]),
             FakeResponse("end_turn", [text_block("第二稿：加了技术")])],
            [FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 没提技术\n【被审内容】x")]),
             FakeResponse("end_turn", [text_block("【结论】通过\n【意见】无\n【被审内容】x")])],
        )
        res = run_collab(w, r, "自我介绍", max_rounds=3)
        self.assertTrue(res["ok"])
        self.assertTrue(res["passed"])
        self.assertEqual(res["rounds"], 2)
        self.assertIn("技术", res["text"])
        self.assertEqual(len(res["log"]), 2)

    def test_max_rounds_backstop(self):
        # 评审永远需改 → 兜底结束，不崩，passed=False
        w, r = self._make(
            [FakeResponse("end_turn", [text_block("第一稿")]),
             FakeResponse("end_turn", [text_block("改一次")]),
             FakeResponse("end_turn", [text_block("改两次")])],
            [FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 再改\n【被审内容】x")]),
             FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 再改\n【被审内容】x")])],
        )
        res = run_collab(w, r, "x", max_rounds=2)
        self.assertTrue(res["ok"])
        self.assertFalse(res["passed"])
        self.assertEqual(res["rounds"], 2)
        self.assertIn("改两次", res["text"])

    def test_empty_first_draft_degrades(self):
        w, r = self._make(
            [FakeResponse("end_turn", [text_block("")])],
            [],
        )
        res = run_collab(w, r, "x")
        self.assertFalse(res["ok"])
        self.assertIsNone(res["text"])

    def test_reviewer_fails_returns_draft(self):
        # 评审中途挂掉 → 拿当前稿交差，passed=False 但 ok=True
        w, r = self._make(
            [FakeResponse("end_turn", [text_block("第一稿")])],
            [FakeResponse("end_turn", [text_block("")])],
        )
        res = run_collab(w, r, "x")
        self.assertTrue(res["ok"])
        self.assertFalse(res["passed"])
        self.assertEqual(res["text"], "第一稿")

    def test_writer_revision_fails_returns_draft(self):
        # 写手改不出来 → 拿当前稿交差，不崩
        w, r = self._make(
            [FakeResponse("end_turn", [text_block("第一稿")]),
             FakeResponse("end_turn", [text_block("")])],
            [FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 改\n【被审内容】x")])],
        )
        res = run_collab(w, r, "x")
        self.assertTrue(res["ok"])
        self.assertFalse(res["passed"])
        self.assertEqual(res["text"], "第一稿")

    def test_reviewer_remembers_its_own_reviews(self):
        # 双脑的关键：评审的账本里攒着它每一轮说过的话（各记各的账）
        w, r = self._make(
            [FakeResponse("end_turn", [text_block("第一稿")]),
             FakeResponse("end_turn", [text_block("第二稿")])],
            [FakeResponse("end_turn", [text_block("【结论】需改\n【意见】1. 没技术\n【被审内容】x")]),
             FakeResponse("end_turn", [text_block("【结论】通过\n【意见】无\n【被审内容】x")])],
        )
        run_collab(w, r, "自我介绍", max_rounds=3)
        reviews = [m for m in r.history() if m["role"] == "assistant"]
        self.assertEqual(len(reviews), 2)                      # 评审说了两次话
        self.assertIn("没技术", reviews[0]["content"])         # 第一次挑的刺还在
        # 评审的 user 消息里得有两份稿子（它审过两次）
        judged = [m for m in r.history() if m["role"] == "user"]
        self.assertIn("第一稿", judged[0]["content"])
        self.assertIn("第二稿", judged[1]["content"])


if __name__ == "__main__":
    unittest.main()

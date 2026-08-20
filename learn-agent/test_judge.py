# 第九课的 eval：测裁判模型——抠分数（纯函数）+ 假裁判跑通，全程零成本
import unittest
from llm_judge import parse_score, judge_answer
from agent_loop import FakeModel, FakeResponse, text_block


class TestParseScore(unittest.TestCase):
    """测"抠分数"这个纯函数：裁判的屁话里能不能准确抠出分数"""

    def test_standard_format(self):
        self.assertEqual(parse_score("4/5\n理由：很好"), 4)

    def test_full_mark(self):
        self.assertEqual(parse_score("5/5\n无可挑剔"), 5)

    def test_zero(self):
        self.assertEqual(parse_score("0/5\n空回答"), 0)

    def test_garbage_around_score(self):
        # 裁判不守规矩，前面废话一堆——照样抠出来
        self.assertEqual(parse_score("整体还行但漏了一点。\n3/5\n主要问题…"), 3)

    def test_no_score_returns_none(self):
        # 裁判彻底跑偏，一个分数都没给 → 优雅降级，不崩
        self.assertIsNone(parse_score("我不知道该怎么评"))

    def test_wrong_scale_returns_none(self):
        # 给了数但不是 X/5 格式 → 不认识，降级
        self.assertIsNone(parse_score("我给 8 分"))


class TestJudgeAnswer(unittest.TestCase):
    """测裁判调用：换假裁判，验证流程真能跑通"""

    def test_fake_judge_scores(self):
        # 假裁判按剧本给 4/5 → judge_answer 应解析出 4
        fake = FakeModel([FakeResponse("end_turn", [text_block("4/5\n不错")])])
        score, text = judge_answer(fake, "题目", "回答")
        self.assertEqual(score, 4)
        self.assertIn("4/5", text)

    def test_fake_judge_mad_output(self):
        # 假裁判跑偏 → score 是 None，judge_answer 不崩
        fake = FakeModel([FakeResponse("end_turn", [text_block("随便吧")])])
        score, text = judge_answer(fake, "题目", "回答")
        self.assertIsNone(score)


if __name__ == "__main__":
    unittest.main()

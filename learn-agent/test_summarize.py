# 第十一课 eval：测摘要压缩——打包提示（纯函数）+ 假摘要模型跑通 + 压缩替换。
import unittest
from summarize import build_summarize_prompt, summarize, replace_with_summary
from agent_loop import FakeModel, FakeResponse, text_block


class TestBuildPrompt(unittest.TestCase):
    """测"打包提示"这个纯函数"""

    def test_contains_instruction_and_transcript(self):
        history = [
            {"role": "user", "content": "杭州天气怎么样？"},
            {"role": "assistant", "content": "今天 28 度，晴。"},
        ]
        prompt = build_summarize_prompt(history)
        self.assertIn("浓缩成", prompt)
        self.assertIn("杭州天气怎么样？", prompt)
        self.assertIn("28 度", prompt)


class TestSummarize(unittest.TestCase):
    """测摘要调用：换假摘要模型，验证流程能跑通"""

    def test_fake_summarizer_returns_text(self):
        fake = FakeModel([FakeResponse("end_turn", [text_block("用户问了天气，得到晴天回答")])])
        self.assertEqual(
            summarize(fake, [{"role": "user", "content": "hi"}]),
            "用户问了天气，得到晴天回答",
        )

    def test_model_breaks_returns_empty(self):
        # 剧本用尽 → FakeModel 抛 RuntimeError → summarize 优雅降级返回 ""
        fake = FakeModel([])
        self.assertEqual(summarize(fake, [{"role": "user", "content": "hi"}]), "")


class TestReplaceWithSummary(unittest.TestCase):
    """测"压缩替换"：预算够不动，超了把最老的压成摘要，压缩失败退化裁剪"""

    def test_fits_unchanged(self):
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，有什么可以帮你？"},
        ]
        new_h, summary = replace_with_summary(history, 100, FakeModel([]))
        self.assertEqual(new_h, history)
        self.assertEqual(summary, "")

    def test_over_budget_compresses(self):
        # 三段对话超预算（2+1+7=10 > 7）：最老两段被压缩，最后一段保留
        history = [
            {"role": "user", "content": "在吗"},
            {"role": "assistant", "content": "在"},
            {"role": "user", "content": "杭州天气怎么样"},
        ]
        fake = FakeModel([FakeResponse("end_turn", [text_block("用户问过天气")])])
        new_h, summary = replace_with_summary(history, 7, fake)
        self.assertEqual(summary, "用户问过天气")
        self.assertEqual(len(new_h), 2)                 # 摘要消息 + 保留的最后一条
        self.assertEqual(new_h[0]["role"], "user")
        self.assertIn("摘要", new_h[0]["content"])
        self.assertEqual(new_h[1], history[2])          # 最后一条原样保留

    def test_compress_failure_falls_back(self):
        # 摘要模型剧本用尽 → 压缩失败 → 退化成"只裁剪"
        history = [
            {"role": "user", "content": "在吗"},
            {"role": "assistant", "content": "在"},
            {"role": "user", "content": "杭州天气怎么样"},
        ]
        new_h, summary = replace_with_summary(history, 7, FakeModel([]))
        self.assertEqual(summary, "")
        self.assertEqual(len(new_h), 1)                 # 只留最后一条


if __name__ == "__main__":
    unittest.main()

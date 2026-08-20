# 第十课的 eval：测"估 token + 裁对话"——全是纯函数，零成本。
import unittest
from context import estimate_tokens, history_tokens, trim_history


class TestEstimateTokens(unittest.TestCase):
    """测"估 token"这个纯函数：一句话大概占几个 token"""

    def test_empty(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_cjk_chars(self):
        # 中文一字约一 token
        self.assertEqual(estimate_tokens("你好世界"), 4)

    def test_english_words(self):
        # 英文一词约一 token
        self.assertEqual(estimate_tokens("hello world"), 2)

    def test_mixed(self):
        # 中英混排：英文按词、中文按字，加起来
        self.assertEqual(estimate_tokens("hello 你好"), 3)


class TestHistoryTokens(unittest.TestCase):
    """测整段对话的 token 总量"""

    def test_empty_history(self):
        self.assertEqual(history_tokens([]), 0)

    def test_two_messages(self):
        history = [
            {"role": "user", "content": "你好"},  # 2
            {"role": "assistant", "content": "你好，有什么可以帮你？"},  # 9
        ]
        self.assertEqual(history_tokens(history), 11)


class TestTrimHistory(unittest.TestCase):
    """测"裁对话"：预算以内不动，超了从最老开始丢"""

    def test_fits_unchanged(self):
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，有什么可以帮你？"},
        ]
        self.assertEqual(trim_history(history, 100), history)

    def test_drop_oldest(self):
        history = [
            {"role": "user", "content": "在"},  # 1
            {"role": "assistant", "content": "好"},  # 1
            {"role": "user", "content": "今天天气怎么样"},  # 7
        ]
        # 1+1+7 = 9 超预算 7 → 丢最老两条，只留最后一条
        kept = trim_history(history, 7)
        self.assertEqual(kept, [history[2]])

    def test_keep_last_even_if_too_big(self):
        history = [{"role": "user", "content": "今天天气怎么样"}]  # 7 > 5
        # 最后一条再超预算也得留——一条消息是砍不掉的
        self.assertEqual(trim_history(history, 5), history)

    def test_does_not_mutate_original(self):
        history = [
            {"role": "user", "content": "在"},
            {"role": "assistant", "content": "好"},
            {"role": "user", "content": "今天天气怎么样"},
        ]
        before = list(history)
        trim_history(history, 7)
        self.assertEqual(history, before)


if __name__ == "__main__":
    unittest.main()

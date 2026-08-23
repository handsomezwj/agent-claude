# 第十六课 eval：测 RAG——切块/拆词/打分/检索/拼 prompt（纯函数）+ 假模型跑通。
import unittest
from agent_loop import FakeModel, FakeResponse, text_block
from rag import (
    chunk_text, tokenize, score_chunk, retrieve_top_k, build_rag_prompt, answer_with_rag,
)


class TestChunkText(unittest.TestCase):
    """测"切块"：把长文切成小段"""

    def test_exact_multiple(self):
        self.assertEqual(chunk_text("abcdef", 2), ["ab", "cd", "ef"])

    def test_last_chunk_shorter(self):
        self.assertEqual(chunk_text("abcde", 2), ["ab", "cd", "e"])

    def test_empty(self):
        self.assertEqual(chunk_text("", 10), [])


class TestTokenize(unittest.TestCase):
    """测"拆词"：中文一个字一个词，英文一个单词一个词"""

    def test_chinese_chars(self):
        self.assertEqual(tokenize("龙井茶"), ["龙", "井", "茶"])

    def test_english_words(self):
        self.assertEqual(tokenize("RAG is cool"), ["RAG", "is", "cool"])


class TestScoreChunk(unittest.TestCase):
    """测"打分"：问题里的词命中了多少"""

    def test_more_overlap_higher_score(self):
        q = "龙井茶"
        self.assertGreater(score_chunk(q, "龙井茶产自龙井村"), score_chunk(q, "西湖很美"))

    def test_no_overlap_zero(self):
        self.assertEqual(score_chunk("茶", "火星和木星"), 0)

    def test_stopword_alone_scores_zero(self):
        # "的"是停用字，被过滤掉，不该让它凑数得分
        self.assertEqual(score_chunk("的", "西湖很美"), 0)


class TestRetrieveTopK(unittest.TestCase):
    """测"检索"：挑最相关的 k 块，分高的在前，零命中不返回"""

    def test_picks_most_relevant_first(self):
        chunks = ["西湖有十景", "龙井茶产自龙井村", "断桥在西湖边"]
        top = retrieve_top_k("龙井茶", chunks, 2)
        self.assertEqual(top[0], "龙井茶产自龙井村")
        self.assertLessEqual(len(top), 2)

    def test_no_match_returns_empty(self):
        self.assertEqual(retrieve_top_k("火星", ["西湖", "龙井茶"], 2), [])

    def test_stopword_only_query_returns_empty(self):
        # 问题里只剩停用字 → 检索不出任何东西（"的"不会把不相干的块捞出来）
        self.assertEqual(retrieve_top_k("的", ["西湖很美", "龙井茶很香"], 2), [])


class TestBuildRagPrompt(unittest.TestCase):
    """测"拼 prompt"：问题和资料都在里面"""

    def test_contains_query_and_context(self):
        prompt = build_rag_prompt("龙井茶怎么泡", ["用 80 度水"])
        self.assertIn("龙井茶怎么泡", prompt)
        self.assertIn("用 80 度水", prompt)


class TestAnswerWithRag(unittest.TestCase):
    """测"问模型"：假模型照剧本回答"""

    def test_fake_model_returns_text(self):
        fake = FakeModel([FakeResponse("end_turn", [text_block("资料说用 80 度水。")])])
        self.assertEqual(
            answer_with_rag(fake, "龙井茶怎么泡", ["资料：用 80 度水"]),
            "资料说用 80 度水。",
        )


if __name__ == "__main__":
    unittest.main()
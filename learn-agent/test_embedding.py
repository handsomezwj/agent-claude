# 第十七课 eval：测 embedding——余弦相似度 / 词表 / 词袋向量 / 向量检索（纯函数）+ 假门。
import unittest
from embedding import (
    cosine_similarity, build_vocab, vectorize, BowEmbedder, retrieve_top_k,
)


class TestCosineSimilarity(unittest.TestCase):
    """测"像不像"：两个向量夹角的余弦"""

    def test_identical_is_one(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)

    def test_proportional_is_one(self):
        # (1,2) 和 (2,4) 方向一模一样，只是长了一倍——余弦不受长度影响
        self.assertAlmostEqual(cosine_similarity([1.0, 2.0], [2.0, 4.0]), 1.0)

    def test_orthogonal_is_zero(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_opposite_is_minus_one(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [-1.0, 0.0]), -1.0)

    def test_zero_vector_is_zero(self):
        # 零向量没有方向，不能除零，按"没关系"算
        self.assertEqual(cosine_similarity([0.0, 0.0], [5.0, 3.0]), 0.0)

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            cosine_similarity([1.0], [1.0, 2.0])


class TestBuildVocab(unittest.TestCase):
    """测"词表"：把资料里的词收齐、去重、排好序"""

    def test_dedup_and_sorted(self):
        self.assertEqual(build_vocab(["cat eats fish", "dog eats bone"]),
                         ["bone", "cat", "dog", "eats", "fish"])

    def test_empty_chunks(self):
        self.assertEqual(build_vocab([]), [])

    def test_only_stopwords_gives_empty(self):
        # "的了"全是停用字，被滤掉 → 词表空
        self.assertEqual(build_vocab(["的 了 是"]), [])


class TestVectorize(unittest.TestCase):
    """测"文字变向量"：出现几次填几"""

    def test_counts_occurrences(self):
        vocab = build_vocab(["cat eats fish", "dog eats bone"])
        # vocab = [bone, cat, dog, eats, fish]，'cat' 在第 1 位，出现 2 次
        self.assertEqual(vectorize("cat cat", vocab), [0.0, 2.0, 0.0, 0.0, 0.0])

    def test_stopword_ignored(self):
        vocab = ["a", "b", "c"]
        # "的"是停用字，不占位置、不加分
        self.assertEqual(vectorize("a 的", vocab), [1.0, 0.0, 0.0])

    def test_all_zeros_length_matches_vocab(self):
        vocab = ["a", "b", "c"]
        self.assertEqual(vectorize("zzz", vocab), [0.0, 0.0, 0.0])


class TestBowEmbedder(unittest.TestCase):
    """测"门"：BowEmbedder.embed 跟 vectorize 一个样"""

    def test_embed_matches_vectorize(self):
        vocab = ["a", "b", "c"]
        e = BowEmbedder(vocab)
        self.assertEqual(e.embed("a b b"), vectorize("a b b", vocab))


class TestRetrieveTopK(unittest.TestCase):
    """测"向量检索"：挑最像的 k 块"""

    def test_picks_most_similar_first(self):
        chunks = ["龙井茶产自龙井村", "西湖有十景", "断桥残雪在西湖"]
        vocab = build_vocab(chunks)
        e = BowEmbedder(vocab)
        top = retrieve_top_k("龙井茶", chunks, 2, e.embed)
        self.assertEqual(top[0], "龙井茶产自龙井村")

    def test_density_wins_over_length(self):
        # 两块都只有"狗"一个词命中，但"狗"这块更"纯"——余弦偏爱短而准
        chunks = ["狗 猫", "狗"]
        vocab = build_vocab(chunks)
        e = BowEmbedder(vocab)
        top = retrieve_top_k("狗", chunks, 1, e.embed)
        self.assertEqual(top, ["狗"])

    def test_no_overlap_returns_empty(self):
        chunks = ["西湖", "龙井茶"]
        vocab = build_vocab(chunks)
        e = BowEmbedder(vocab)
        # "火星"一个字都撞不上 → 相似度 0 → 不硬塞
        self.assertEqual(retrieve_top_k("火星", chunks, 2, e.embed), [])

    def test_min_sim_filters_weak_matches(self):
        chunks = ["狗", "猫"]
        vocab = build_vocab(chunks)
        e = BowEmbedder(vocab)
        # 问"狗 猫"，两块各命中一半，相似度约 0.707 < 0.8 → 都不合格
        self.assertEqual(retrieve_top_k("狗 猫", chunks, 2, e.embed, min_sim=0.8), [])

    def test_precomputed_vectors_same_result(self):
        chunks = ["龙井茶产自龙井村", "西湖有十景"]
        vocab = build_vocab(chunks)
        e = BowEmbedder(vocab)
        vectors = [e.embed(c) for c in chunks]
        self.assertEqual(
            retrieve_top_k("龙井茶", chunks, 1, e.embed, chunk_vectors=vectors),
            retrieve_top_k("龙井茶", chunks, 1, e.embed),
        )


if __name__ == "__main__":
    unittest.main()

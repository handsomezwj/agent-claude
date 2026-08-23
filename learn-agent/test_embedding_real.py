# 第十八课 eval：测"真门"——ModelEmbedder 包装、工厂优雅降级、真模型阈值下的检索。
# 注意：不真下载模型！loader 是"门套门"，测试里塞假的。
import unittest
import numpy as np
from embedding_models import ModelEmbedder, try_load_model, REAL_MIN_SIM, DEFAULT_MODEL
from embedding import retrieve_top_k


class FakeFastModel:
    """假 fastembed 模型：照剧本返回向量。真模型长什么样，就长什么样。"""

    def __init__(self, vectors, dimension=4):
        self.vectors = {t: np.array(v, dtype=float) for t, v in vectors.items()}
        self.dimension = dimension

    def embed(self, texts):
        for t in texts:
            yield self.vectors.get(t, np.zeros(self.dimension))


class TestModelEmbedder(unittest.TestCase):
    """测"真门"：把 fastembed 返回的 numpy 转成干净的 list[float]"""

    def test_embed_returns_float_list(self):
        model = FakeFastModel({"番茄": [0.5, 0.5, 0.5, 0.5]}, dimension=4)
        e = ModelEmbedder(model)
        vec = e.embed("番茄")
        self.assertIsInstance(vec, list)
        self.assertTrue(all(isinstance(x, float) for x in vec))
        self.assertEqual(vec, [0.5, 0.5, 0.5, 0.5])

    def test_dim_exposed(self):
        model = FakeFastModel({}, dimension=512)
        self.assertEqual(ModelEmbedder(model).dim, 512)

    def test_embed_missing_text_zeros(self):
        model = FakeFastModel({"西红柿": [1.0, 0.0, 0.0, 0.0]}, dimension=4)
        e = ModelEmbedder(model)
        self.assertEqual(e.embed("没见过的词"), [0.0, 0.0, 0.0, 0.0])


class TestTryLoadModel(unittest.TestCase):
    """测"工厂"：真门套得成功 / 失败优雅返回 None"""

    def test_success_returns_embedder(self):
        emb, err = try_load_model("any", loader=lambda name: FakeFastModel({"a": [1.0, 0.0, 0.0]}))
        self.assertIsNone(err)
        self.assertEqual(emb.embed("a"), [1.0, 0.0, 0.0])

    def test_failure_returns_none_with_error(self):
        def boom(name):
            raise RuntimeError("模型加载失败")
        emb, err = try_load_model("any", loader=boom)
        self.assertIsNone(emb)
        self.assertIsInstance(err, RuntimeError)

    def test_default_model_constant_is_sane(self):
        self.assertIsInstance(DEFAULT_MODEL, str)
        self.assertIn("bge", DEFAULT_MODEL)


class TestRealThresholdRetrieval(unittest.TestCase):
    """测"真模型的检索"：换真门后，同义词能搜到；低于阈值的不捞"""

    def test_synonym_retrieved_with_real_style_vectors(self):
        # 模拟真模型给"番茄/西红柿"很接近的向量，跟写"西红柿"的正文靠得近
        chunk = "西红柿是常见蔬菜，可以炒鸡蛋。"
        other = "杭州是浙江的省会。"
        model = FakeFastModel({
            "番茄": [1.0, 0.9, 0.0, 0.0],
            "西红柿是常见蔬菜，可以炒鸡蛋。": [0.9, 1.0, 0.0, 0.0],
            "杭州是浙江的省会。": [0.0, 0.0, 1.0, 0.9],
        }, dimension=4)
        e = ModelEmbedder(model)
        chunks = [chunk, other]
        vectors = [e.embed(c) for c in chunks]
        top = retrieve_top_k("番茄", chunks, 2, e.embed, vectors, min_sim=REAL_MIN_SIM)
        self.assertEqual(top, [chunk])   # 同义词把正身捞出来了

    def test_unrelated_below_threshold_excluded(self):
        # "股票"和"杭州旅游"毫无关系，真模型下余弦也低，但要靠阈值挡住
        model = FakeFastModel({
            "股票": [1.0, 0.0, 0.0, 0.0],
            "杭州是浙江的省会，以西湖闻名。": [0.0, 0.0, 1.0, 0.0],
        }, dimension=4)
        e = ModelEmbedder(model)
        chunks = ["杭州是浙江的省会，以西湖闻名。"]
        top = retrieve_top_k("股票", chunks, 1, e.embed, min_sim=REAL_MIN_SIM)
        self.assertEqual(top, [])   # 相似度 0 < 0.3，不硬塞


if __name__ == "__main__":
    unittest.main()

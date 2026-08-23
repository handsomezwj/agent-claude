# 被测对象：把"假门"换成真向量模型（第十八课）
#
# 第十七课的词袋假门只认字面——问"番茄"搜不到写"西红柿"的资料（余弦 0）。
# 真向量模型把"语义"学进了向量里：番茄和西红柿的向量会挨得很近（实测 0.75）。
# 门还是同一个：.embed(text) → 一串数字。换实现，检索代码一行不改。
#
# 真门用什么：fastembed 加载本地 ONNX 模型 bge-small-zh-v1.5（中文，512 维，免费离线）。
# 首次使用会下载模型（~100MB）；下载过就有本地缓存，之后离线可用。
# 加载是重活：任何一步失败都返回 None，让调用方优雅降级回假门——绝不崩。
import os

# 默认的中文向量模型（Qdrant 的 bge-small-zh-v1.5，对标 BAAI/bge-small-zh-v1.5）
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"

# 真模型的相似度阈值：跟词袋假门不同（撞不上 = 0），真模型没有"正好 0"一说——
# 任何两句中文之间余弦都有 0.3~0.6 的"基础分"（实测：问"北京的雾霾"，杭州攻略
# 每块都给了 0.30~0.34）。所以阈值得抬高，还要跟着语料调。0.45 是杭州攻略调出来的值：
# 问龙井茶，最像那块 0.61 过关；雾霾那批 0.30~0.34 全部被挡在门外。换语料要重新调。
REAL_MIN_SIM = 0.45


class ModelEmbedder:
    """真门：包一个本地向量模型。embed(text) → list[float]，跟 BowEmbedder 同一个接口。

    model 是什么？fastembed.TextEmbedding 的实例。测试里可以塞一个假的（见 test）。
    心法照旧：调用方只认 .embed() 长什么样，不认它背后是真模型还是假实现。
    """

    def __init__(self, model):
        self.model = model
        # fastembed 没暴露维度属性，干脆实测一次：量一下自己吐的向量多长。
        # 一次微型嵌入，加载时做一次即可。
        try:
            self.dim = len(self.embed("测"))
        except Exception:
            self.dim = None

    def embed(self, text):
        # fastembed 的 .embed([text]) 返回一个生成器，取第一项就是这句话的向量
        vec = list(self.model.embed([text]))[0]
        return [float(x) for x in vec]   # 统一成 list[float]，别让 numpy 泄漏出去


def try_load_model(model_name, loader=None):
    """真门工厂：尝试加载真向量模型，成功返回 (ModelEmbedder, None)，失败返回 (None, 错误)。

    loader 是"门套门"：默认用 fastembed.TextEmbedding；测试注入假 loader，
    想让它失败就让假 loader 抛异常。优雅降级就靠这一层兜底。
    """
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")   # 镜像站不支持 Xet，走普通 HTTP
    try:
        if loader is None:
            from fastembed import TextEmbedding
            loader = TextEmbedding
        return ModelEmbedder(loader(model_name)), None
    except Exception as exc:
        return None, exc

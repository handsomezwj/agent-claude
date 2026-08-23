# 被测对象：embedding（向量嵌入）——把文字变成一串数字，用"距离"找相关
#
# 第十六课的关键词打分有个硬伤：只认字面，不认意思。
# 问"西子湖"搜不到写"西湖"的资料——明明是一个地方。因为字对不上。
# 换一个思路：给文字编码成"一串数字"（向量），让意思相近的文字，数字也相近。
# 找资料 = 找数字最接近的那块。这"数字相不近"就用余弦相似度来量。
#
# 怎么把文字变数字？这就是"嵌入"（embedding）。真实世界是训练好的向量模型干的：
# 一个模型，输入一句话，吐出一长串数字，同义词会映射到相近的数字。
# 这课先把机制讲透——用一个免费的本地实现当"门"（词袋向量）：
# 给词表里每个词一个位置，文本里出现几次，那个位置就填几。
# 门长什么样（.embed(text) 返回一串数字），将来换真向量模型就是换这个实现，别的代码一行不改。
from rag import tokenize


def cosine_similarity(a, b):
    """两个向量的相似度：越接近 1 越像，越接近 0 越没关系（还可能为负）。纯函数，可测。
    公式：a·b / (|a| × |b|)。就是"夹角的余弦"——方向越一致越像，跟长度无关。
    零向量（全是 0）没有方向，按 0 算。"""
    if len(a) != len(b):
        raise ValueError(f"向量长度不一致：{len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def build_vocab(chunks):
    """把资料里出现过的所有词收集起来，按字典序排好，编上位置号。纯函数，可测。
    这叫"词表"（vocabulary）。每个词占向量里的一个位置。
    字典序是为了"可复现"——同样的资料，永远得到同样的向量。"""
    vocab = set()
    for chunk in chunks:
        vocab.update(tokenize(chunk))
    return sorted(vocab)


def vectorize(text, vocab):
    """词袋向量：文本里每个词出现几次，对应位置就填几。纯函数，可测。
    例子：词表 ['井','湖','茶','西','龙']，文本"西湖的西湖"
    → '西' 出现 2 次、'湖' 出现 2 次 → [0, 2, 0, 2, 0]（'的'是停用字被滤掉）。"""
    index = {w: i for i, w in enumerate(vocab)}
    vec = [0.0] * len(vocab)
    for w in tokenize(text):
        if w in index:
            vec[index[w]] += 1.0
    return vec


class BowEmbedder:
    """假门：本地词袋向量——不花钱、可复现，把"文字 → 向量"的机制讲透。
    真门长一个样：.embed(text) 返回一串数字。将来换上真向量模型
    （比如 OpenAI text-embedding、开源 bge/m3e），只换这个实现，
    下面所有检索代码一行不用改。"""

    def __init__(self, vocab):
        self.vocab = vocab
        self._index = {w: i for i, w in enumerate(vocab)}

    def embed(self, text):
        return vectorize(text, self.vocab)


def retrieve_top_k(query, chunks, k, embed, chunk_vectors=None, min_sim=0.0):
    """向量检索：给每块资料算"跟问题有多像"（余弦相似度），挑最像的 k 块。纯逻辑，可测。
    embed 是"门"——传什么实现，就用什么把文字变向量。
    chunk_vectors 传进来就不用每问一次重算一遍（启动时算好，这是给生产用的缓存位）。
    min_sim：相似度不高于这个值就不要（太不像 = 硬塞 = 误导）。
    词袋向量下，一个词都对不上时相似度正好是 0，所以默认阈值 0 就够。"""
    if chunk_vectors is None:
        chunk_vectors = [embed(c) for c in chunks]
    qvec = embed(query)
    scored = sorted(
        (
            (cosine_similarity(qvec, cvec), i, c)
            for i, (c, cvec) in enumerate(zip(chunks, chunk_vectors))
        ),
        key=lambda x: (-x[0], x[1]),   # 先比相似度（高在前），同分保持原顺序
    )
    return [c for s, i, c in scored[:k] if s > min_sim]
# 第十七课：embedding（向量嵌入）——把文字变成数字，用"距离"找相关
#
# 第十六课的关键词打分只认字面（问"西子湖"搜不到"西湖"）。
# 这课把文字变成向量，用余弦相似度找"最像的块"。整个演示全本地、免费：
# 用词袋向量当"假门"把机制讲透。真向量模型是同一扇门（.embed(text) 返回一串数字），
# 将来换实现即可——下面检索的代码一行不用改。
#
# 用法：python 14-embedding.py   （本地假门，不花一分钱；--fake 也一样的本地流程）
from pathlib import Path
from rag import chunk_text
from embedding import build_vocab, vectorize, cosine_similarity, BowEmbedder, retrieve_top_k


def load_knowledge():
    """读知识库（跟 agent-claude.py 共用同一个文件）"""
    path = Path(__file__).parent / "knowledge.md"
    return path.read_text(encoding="utf-8")


def part1_mechanism():
    """第 1 幕：把文字变数字，用手算得出来的小例子看机制"""
    print("== 第 1 幕：文字怎么变成一串数字（词袋向量） ==")
    vocab = build_vocab(["西湖", "龙井茶"])
    print(f"  词表（按字典序）        : {vocab}   ← 每个词占向量一个位置")
    v1 = vectorize("西湖的西湖", vocab)
    v2 = vectorize("龙井茶", vocab)
    print(f"  『西湖的西湖』→ {v1}  （'的'是停用字被滤掉；'西湖'出现两次填 2）")
    print(f"  『龙井茶』    → {v2}")
    print(f"  它俩的余弦相似度 = {cosine_similarity(v1, v2)}   ← 一个词都没撞上，就是 0（没关系）")
    print()


def part2_real():
    """第 2 幕：真知识库走一遍向量检索，把每一块的相似度打出来"""
    print("== 第 2 幕：在杭州攻略里向量检索 ==")
    knowledge = load_knowledge()
    chunks = chunk_text(knowledge, 200)
    print(f"  知识库 {len(knowledge)} 字 → 切成 {len(chunks)} 块，词表 {len(build_vocab(chunks))} 个词")

    e = BowEmbedder(build_vocab(chunks))
    chunk_vectors = [e.embed(c) for c in chunks]

    query = "龙井茶怎么泡？"
    qvec = e.embed(query)
    print(f"  问『{query}』，每一块的相似度：")
    for i, c in enumerate(chunks):
        sim = cosine_similarity(qvec, chunk_vectors[i])
        print(f"    第{i+1}块  sim={sim:.3f}   {c[:20]}……")
    top = retrieve_top_k(query, chunks, 2, e.embed, chunk_vectors)
    print(f"  → 挑出最像的 {len(top)} 块：")
    for i, c in enumerate(top):
        print(f"      【资料{i+1}】{c[:40]}……")
    print()


def part3_why_better():
    """第 3 幕：向量检索比关键词打分强在哪（一个具体的例子）"""
    print("== 第 3 幕：向量检索比关键词强在哪 ==")
    # 两块都命中"狗"，关键词打分分不出高下；余弦按长度归一化，偏爱"短而准"的块
    toy = ["狗 猫 狗 猫", "狗"]
    e = BowEmbedder(build_vocab(toy))
    print(f"  问『狗』，两块资料：{toy}")
    for i, c in enumerate(toy):
        sim = cosine_similarity(e.embed("狗"), e.embed(c))
        print(f"    第{i+1}块  sim={sim:.3f}  （关键词打分两块都是 1 次命中，平手）")
    print("  → 余弦认为『狗』这块更纯、更相关：短而准胜过又长又啰嗦。\n")


def part4_limit():
    """第 4 幕：词袋向量的天花板 = 为什么真向量模型值得上"""
    print("== 第 4 幕：字面检索的天花板 ==")
    # 番茄和西红柿是同一种东西，但字全不一样——这是词袋向量（和关键词）的死穴
    kb = "西红柿是常见蔬菜，可以炒鸡蛋，也可以凉拌。"
    chunks = [kb]
    e = BowEmbedder(build_vocab(chunks))
    vectors = [e.embed(c) for c in chunks]
    for q in ["番茄", "西红柿"]:
        top = retrieve_top_k(q, chunks, 2, e.embed, vectors)
        print(f"  问『{q}』（和西红柿一个东西）→ 检索出 {len(top)} 块")
    print("  『番茄』的字一个都撞不上『西红柿』→ 词袋向量搜不到。")
    print("  但人知道它俩是一回事。真向量模型（换掉这个假门）会把'意思相近'")
    print("  的词映射到'数字相近'的位置，这里就搜得到了——这就是语义检索，")
    print("  也是为什么要用真 embedding。\n")


if __name__ == "__main__":
    part1_mechanism()
    part2_real()
    part3_why_better()
    part4_limit()
    print("（演示完。这课没有真模型调用，全本地、免费；真向量模型是同一扇门，将来换 embed 实现即可）")

# 第十八课：把"假门"换成真向量模型——语义检索终于来了
#
# 第十七课的词袋假门只认字面（问"番茄"搜不到写"西红柿"的资料）。
# 这课把门换成真向量模型（本地 bge-small-zh-v1.5，免费离线，首次用会下载 ~100MB）：
# 番茄和西红柿的向量实测余弦 0.75——同义词终于能互相找到了。
#
# 用法：
#   python 15-embedding-real.py --fake   假门（词袋），不碰模型，纯复习
#   python 15-embedding-real.py          真模型，看语义检索的威力（已下载过就不花钱不联网）
import os
import sys
from pathlib import Path
from rag import chunk_text
from embedding import build_vocab, BowEmbedder, cosine_similarity, retrieve_top_k
from embedding_models import try_load_model, DEFAULT_MODEL, REAL_MIN_SIM


def load_knowledge():
    path = Path(__file__).parent / "knowledge.md"
    return path.read_text(encoding="utf-8")


def fake_run():
    """假门：词袋向量，一分钱不花，复习上一课"""
    print("== 假门（词袋向量）：只认字面 ==")
    knowledge = load_knowledge()
    chunks = chunk_text(knowledge, 200)
    e = BowEmbedder(build_vocab(chunks))
    vectors = [e.embed(c) for c in chunks]
    top = retrieve_top_k("番茄", ["西红柿是常见蔬菜，可以炒鸡蛋，也可以凉拌。"], 1, e.embed)
    print(f"  问『番茄』→ 检索出 {len(top)} 块（字全不同，搜不到）")
    print("  → 假门到此为止。换真门看下一幕。\n")


def real_run():
    print("== 真门（bge 中文向量模型）：语义检索 ==")
    emb, err = try_load_model(DEFAULT_MODEL)
    if emb is None:
        print(f"  真模型加载失败：{err}")
        print("  （检查网络：首次需从 HF 镜像下载 ~100MB；或设 HF_ENDPOINT=https://hf-mirror.com）")
        return

    print(f"  模型加载成功（{emb.dim} 维）。\n")

    # ① 同义词之战：假门是 0，真门是多少？
    sim = cosine_similarity(emb.embed("番茄"), emb.embed("西红柿"))
    print(f"  番茄 vs 西红柿 余弦 = {sim:.3f}   （假门词袋向量这里是 0）")

    # ② 检索实战：知识库里只写"西红柿"，问"番茄"
    print(f"\n  问『番茄』（阈值 {REAL_MIN_SIM}，低于它不捞）：")
    toy = ["西红柿是常见蔬菜，可以炒鸡蛋，也可以凉拌。", "杭州是浙江的省会，以西湖闻名。"]
    vectors = [emb.embed(c) for c in toy]
    for i, c in enumerate(toy):
        print(f"    『{c[:12]}…』 sim={cosine_similarity(emb.embed('番茄'), vectors[i]):.3f}")
    top = retrieve_top_k("番茄", toy, 2, emb.embed, vectors, min_sim=REAL_MIN_SIM)
    print(f"  → 检索出 {len(top)} 块，第一块开头：『{top[0][:12]}…』" if top else "  → 0 块")

    # ③ 真知识库走一遍（杭州攻略）：每一块的相似度都打出来，看阈值怎么干活
    print("\n  在杭州攻略里检索（阈值 =", REAL_MIN_SIM, "低于它不捞）：")
    knowledge = load_knowledge()
    chunks = chunk_text(knowledge, 200)
    vectors = [emb.embed(c) for c in chunks]
    for q in ["龙井茶怎么泡", "北京的雾霾"]:
        sims = [cosine_similarity(emb.embed(q), v) for v in vectors]
        print(f"    问『{q}』各块相似度：{['%.2f' % s for s in sims]}")
        top = retrieve_top_k(q, chunks, 2, emb.embed, vectors, min_sim=REAL_MIN_SIM)
        print(f"      → 检索出 {len(top)} 块" + (f"，最像：{top[0][:16]}…" if top else "（全在阈值下 = 知识库里没有，不硬塞）"))
    print("    注意『北京的雾霾』：每块都是 0.30~0.34，没一个高、也没一个是 0——")
    print("    这就是密集向量跟关键词的本质差别：没有'正好 0'，只能靠阈值挡。")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fake":
        fake_run()
    else:
        real_run()

# 被测对象：RAG（Retrieval-Augmented Generation，检索增强）
#
# 问题：AI 懂很多，但不懂"你自己的东西"（你的简历、你的笔记、你的产品说明）。
# 你不可能重训它，也没法把整份资料塞进 prompt（太长、费钱）。
# RAG 的思路：有人提问时，先在你的资料里"检索最相关的几段"，
# 然后把【问题 + 这几段】一起交给 AI——AI 相当于先翻到对的那页，再回答。
#
# 三步走：切块（chunking）→ 检索（retrieval）→ 拼接问答（augmented generation）。
# 检索这里用最朴素的关键词打分（问题里的词，命中了多少）——不上向量库，
# 先把思想搞懂。心法照旧：要问的模型是个"门"，真模型 / FakeModel 都能进。
import os
import re


def chunk_text(text, size):
    """把一篇文章切成一段一段（块）。纯函数，可测。
    为什么要切：整篇塞不进 prompt，而且提问时只想找最相关的那几段。"""
    return [text[i:i + size] for i in range(0, len(text), size)]


# 中文里的"停用字"：没有信息量（的、是、了、有……），检索时不能让它们凑数。
# 不然问"火星的天气"也会因为撞上一个"的"字，把毫不相干的块捞出来。
STOPWORDS = set("的了是在有和与就也都吗呢吧啊这那什么我怎么你他她它们")


def tokenize(text):
    """把文字拆成词：中文一个字算一个词（跳过停用字），英文一个单词算一个词。纯函数，可测。"""
    words = re.findall(r"[A-Za-z0-9]+", text)   # 英文单词
    words += [ch for ch in text if "一" <= ch <= "鿿" and ch not in STOPWORDS]  # 有信息量的中文字
    return words


def score_chunk(query, chunk):
    """给一块资料打分：问题里的词，有多少个出现在这块里。纯函数，可测。
    命中的词越多，说明这块跟问题越相关。返回命中数。"""
    query_words = set(tokenize(query))
    return sum(1 for w in query_words if w in chunk)


def retrieve_top_k(query, chunks, k):
    """检索：给所有块打分，挑最相关的 k 块，分高的在前。纯函数，可测。
    一块都没命中的话返回空——查不到就不硬塞资料，让模型如实说不知道。"""
    scored = sorted(
        ((score_chunk(query, c), i, c) for i, c in enumerate(chunks)),
        key=lambda x: (-x[0], x[1]),        # 先比分，同分保持原顺序
    )
    return [c for s, i, c in scored[:k] if s > 0]


def build_rag_prompt(query, context):
    """把【问题 + 找来的资料】拼成给模型的一句话。纯函数，可测。"""
    blocks = "\n\n".join(f"【资料{i+1}】{c}" for i, c in enumerate(context))
    return f"""请根据下面提供的资料回答用户的问题。资料里没有的，就照实说不知道。

【资料】
{blocks}

【问题】
{query}"""


def answer_with_rag(model, query, context, model_name=None):
    """问模型要答案。model 是"门"——真模型 or FakeModel 都能进。"""
    if model_name is None:
        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    resp = model.messages.create(
        model=model_name,
        max_tokens=300,
        messages=[{"role": "user", "content": build_rag_prompt(query, context)}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")

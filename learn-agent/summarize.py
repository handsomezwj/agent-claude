# 被测对象：摘要压缩——trim 的进阶。
# trim_history（第十课）超预算就把最老的消息"扔掉"——省地方，但早期信息真没了。
# 摘要压缩不扔：先把最老的对话浓缩成几句话，再替换回去。信息还在，只是被压扁了。
# 跟裁判（第九课）一个套路：这也是"请一台 AI 干活"，所以它也能被假模型替换、被测试。
import os
from context import history_tokens

# 给摘要模型的指令：写清楚"浓缩成几句话、保留什么、丢什么、只输出摘要本身"
SUMMARIZE_INSTRUCTION = """把下面的对话浓缩成 2-3 句摘要。要求：
- 保留关键事实、用户的要求和已经得出的结论
- 丢掉寒暄和废话
- 只输出摘要本身，不要任何前缀"""


def build_summarize_prompt(messages):
    """把一段对话打包成给摘要模型的一句话。纯函数，可测。"""
    transcript = "\n".join(
        f"{m['role']}: {m['content']}"
        for m in messages
        if isinstance(m.get("content"), str)
    )
    return f"{SUMMARIZE_INSTRUCTION}\n\n【对话】\n{transcript}"


def summarize(model, messages, model_name=None):
    """请模型把一段对话压成摘要。返回摘要文本；失败返回 ""（优雅降级）。

    模型不靠谱就返回空摘要——调用方拿空摘要兜底，绝不让主循环崩。
    """
    if model_name is None:
        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    try:
        resp = model.messages.create(
            model=model_name,
            max_tokens=200,
            messages=[{"role": "user", "content": build_summarize_prompt(messages)}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception:
        return ""


def replace_with_summary(history, budget, model):
    """超预算时：把最老的对话压成一条摘要替换掉，而不是像 trim 那样直接扔。

    返回 (新history, 摘要文本)。
    - 预算够 → 不动，摘要文本为 ""
    - 预算不够 → 从最老开始把旧消息收进"压缩桶"，剩下的放得进预算就停，
      然后请模型把压缩桶浓缩成一条摘要，塞回最前面
    - 压缩失败（模型跑飞）→ 退化成 trim：只裁剪，摘要文本为 ""
    """
    kept = list(history)
    compressed = []
    while len(kept) > 1 and history_tokens(kept) > budget:
        compressed.insert(0, kept.pop(0))   # 最老的一条进压缩桶

    if not compressed:
        return kept, ""

    summary = summarize(model, compressed)
    if not summary:
        return kept, ""   # 压缩失败 → 至少裁剪保命

    summary_msg = {"role": "user", "content": f"[更早对话摘要] {summary}"}
    return [summary_msg] + kept, summary

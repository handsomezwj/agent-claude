# 被测对象：上下文管理——对话越长，越要防"超窗"。
#
# 模型每次"读"你的对话，都受一个上限管着——上下文窗口（context window）。
# 你 agent 的 history 是无脑累积的，聊得越久越接近这个上限，总有一天会超，
# 超了 API 直接报错，agent 当场罢工。这一课给它上"预算"：
#   1. estimate_tokens  粗略估一句话占多少 token（模型的最小阅读单位）
#   2. history_tokens   估整段对话占多少 token
#   3. trim_history     超预算就从最老的消息开始丢，永远保住最后一条
#
# 三个都是纯函数，不碰网络、不碰外部状态——可以白测。
import re

# 中文一字约一 token，英文一词约一 token。粗估够用了，不需要精确。
_CJK_RE = re.compile(r"[一-鿿]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def estimate_tokens(text):
    """粗略估算一段文本占多少 token。纯函数，可测。

    不是精确值——只需要量级对，能用来算预算就行。
    content 可能不是字符串（真实 SDK 里可能是 block 列表），一律转成 str 再算。
    """
    if not isinstance(text, str):
        text = str(text)
    return len(_CJK_RE.findall(text)) + len(_WORD_RE.findall(text))


def history_tokens(history):
    """估算整段对话占多少 token。纯函数，可测。

    history 是 [{"role": ..., "content": ...}, ...]，跟 API 的 messages 同款结构。
    """
    total = 0
    for msg in history:
        total += estimate_tokens(msg.get("content", ""))
    return total


def trim_history(history, budget):
    """把对话裁到预算以内：从最老的消息开始丢，永远保住最后一条。

    返回一个新列表，不改动传入的 history——调用方可以放心传 messages。
    裁对话像清冰箱：过期的最先扔，最近的要留。
    """
    kept = list(history)
    while len(kept) > 1 and history_tokens(kept) > budget:
        kept.pop(0)  # 扔最老的一条
    return kept

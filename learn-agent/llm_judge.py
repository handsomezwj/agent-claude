# 被测对象：裁判模型（LLM-judge）——用一个 LLM 给另一个 LLM 的回答打分。
#
# 之前的测试都在问"循环走对没有"（打转？绕圈？）——那是结构性的，程序自己能判断。
# 但"这个回答写得好不好"是质量问题，程序不会读中文，只能再请一台 AI 当裁判。
# 裁判也是 AI，所以它也能被假模型替换、被测试——这就是本课的核心。
import os
import re

# 评分标准（rubric）：几条硬杠杠，裁判照着评。
# 标准越具体，裁判越不容易瞎评——这是裁判模型的关键。
RUBRIC = """按下面的标准给这份回答打分，满分 5 分：
- 5 分：完整、准确、有条理，几乎没有毛病
- 4 分：基本正确，有一两处小遗漏
- 3 分：方向对，但有明显错误或答非所问
- 2 分：只有一半有用内容，或者信息错误
- 1 分：几乎没用，或完全跑题
- 0 分：空回答 / 什么都没答

输出格式（必须严格遵守）：
第一行写 X/5（X 是 0 到 5 的整数）
第二行写一句评分理由。
不要输出第三行，不要客气话。"""


def build_judge_prompt(task, answer):
    """把题目 + 回答 + 标准，打包成给裁判的一句话"""
    return f"""你是一名严格的评审。下面是题目，和一份 AI 的回答。

【题目】
{task}

【回答】
{answer}

{RUBRIC}"""


def parse_score(text):
    """从裁判的回答里抠出分数。纯函数，可测。

    认 "X/5" 这种格式；裁判跑偏给不出分数就返回 None——
    优雅降级：宁可没分，不能让整个 agent 崩掉。
    """
    m = re.search(r"(\d)\s*/\s*5", text)
    if m:
        return int(m.group(1))
    return None


JUDGE_MAX_TOKENS = 1500


def judge_answer(model, task, answer, model_name=None):
    """问裁判打分。返回 (分数, 裁判原话)。分数解析失败时分数为 None。

    model 可以是真 client，也可以是第八课的 FakeModel——
    "想测的东西，先给它一个门"，裁判也一样。
    model_name 不传就默认用环境里的模型（真跑时有效）。
    """
    if model_name is None:
        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    prompt = build_judge_prompt(task, answer)
    # 关掉裁判的思考：裁判只是照标准打个分，不需要推理链。而支持 thinking 的端点
    # （如第三方兼容端点）默认开着思考，且思考按输出计费、先花预算——长回答下它会
    # 把预算全烧在思考上，回来只有 thinking 块、正文一个字都没有，判分静默失效。
    # 真机实测（deepseek 兼容端点）：1500 token 全花在思考上，stop_reason=max_tokens。
    # 端点不认这个参数就退回不带（"一套代码多后端"）。
    kw = {"model": model_name, "max_tokens": JUDGE_MAX_TOKENS,
          "messages": [{"role": "user", "content": prompt}]}
    try:
        resp = model.messages.create(**kw, thinking={"type": "disabled"})
    except TypeError:                       # 假模型 / 老 SDK 不认这个关键字
        resp = model.messages.create(**kw)
    except Exception as exc:                # 端点明确说不支持再退回，别的错照抛（别掩盖真问题）
        msg = str(exc).lower()
        if not any(w in msg for w in ("thinking", "unsupported", "unexpected", "invalid")):
            raise
        resp = model.messages.create(**kw)
    text = "".join(b.text for b in resp.content if b.type == "text")
    return parse_score(text), text

# 被测对象：多 Agent 评审模式（写手 + 评审，多轮迭代）
# 第 13 课核心：把"写"和"审"拆成两个角色——审的不护短，协作 > 单干。
import re


# ---------------------- 纯函数：三个 prompt ----------------------

def build_draft_prompt(topic):
    """写手第一稿的指令"""
    return f"""你是写手，为「{topic}」写一段内容。
要求：直接输出内容本身，不要任何开场白、解释、客套话。"""


def build_critic_prompt(topic, draft):
    """评审挑刺的指令——结构化输出：结论 + 意见"""
    return f"""你是严格的评审，审阅下面这份关于「{topic}」的内容。
输出格式（必须严格遵守）：
【结论】通过 或 需改
【意见】若需改：写 1-3 条具体意见，用「1.」「2.」编号；若通过：写"无"
【被审内容】
{draft}"""


def build_revise_prompt(topic, draft, opinions):
    """写手按评审意见修改的指令"""
    return f"""你是写手，请根据评审意见修改下面这份关于「{topic}」的内容。
【评审意见】
{opinions}
【原稿】
{draft}
直接输出修改后的完整内容，不要任何解释。"""


# ---------------------- 纯函数：解析评审输出 ----------------------

_VERDICT_RE = re.compile(r"【结论】\s*(通过|需改)")
_OPINIONS_RE = re.compile(r"【意见】\s*(.*?)(?=【|$)", re.S)


def parse_critic(text):
    """从评审输出抠出 (结论, 意见)。
    解析失败按"需改 + 无意见"处理——保守：宁可不放行，不让烂稿过关。
    """
    m = _VERDICT_RE.search(text)
    verdict = m.group(1) if m else "需改"
    m2 = _OPINIONS_RE.search(text)
    opinions = m2.group(1).strip() if m2 else "无"
    return verdict, opinions


# ---------------------- 门：发一次模型调用（优雅降级） ----------------------

def _call(model, prompt, model_name="fake"):
    """发一次模型调用，抠出文本。异常/空输出返回 None——优雅降级。
    model_name 默认 "fake"：FakeModel 不在乎模型名；真模型调用时传真实模型名。
    """
    try:
        resp = model.messages.create(
            model=model_name, max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text") or None
    except Exception:
        return None


# ---------------------- 门：评审循环 ----------------------

def run_debate(model, topic, max_rounds=3):
    """写手写 → 评审挑 → 按意见改 → 再评，直到通过或到顶。
    返回 {ok, text, rounds, passed, error}。护栏思想：max_rounds 兜底（第 3 课 MAX_ITERS 的延伸）。
    """
    draft = _call(model, build_draft_prompt(topic))
    if draft is None:
        return {"ok": False, "text": None, "rounds": 0, "passed": False,
                "error": "写手第一稿就没出来，请重试。"}

    for round_no in range(1, max_rounds + 1):
        critic = _call(model, build_critic_prompt(topic, draft))
        if critic is None:
            return {"ok": True, "text": draft, "rounds": round_no, "passed": False,
                    "error": "评审没出来，拿当前稿交差。"}
        verdict, opinions = parse_critic(critic)
        if verdict == "通过" or opinions == "无":
            return {"ok": True, "text": draft, "rounds": round_no, "passed": True}
        revised = _call(model, build_revise_prompt(topic, draft, opinions))
        if revised is None:
            return {"ok": True, "text": draft, "rounds": round_no, "passed": False,
                    "error": "修改没出来，拿当前稿交差。"}
        draft = revised

    return {"ok": True, "text": draft, "rounds": max_rounds, "passed": False,
            "error": f"评审 {max_rounds} 轮都没给通过，拿最后一稿交差。"}
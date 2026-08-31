# ops_debate.py — 多 Agent 辩论/评审团模式（模式 C）
#
# 场景：你抛一个面试题，三个专家（原理/工程/面试官角度）各答一遍，
# 主席收齐后汇总成一份「面试满分答案」+ 常见追问。
#
# 和主管-工人（模式 A）的区别：
#   主管-工人 = 拆活分工：每人干不同的任务（状态/日志/风险）。
#   评审团   = 多角度审同一件事：同一道题，每人从自己的角度答，汇总取长补短。
#
# 心法：防自评盲区——自己答自己评容易吹，换个角度的人评才客观；
#       主席负责"汇总"，不替专家答题。

CHAIR_SYSTEM = (
    "你是评审团主席。收齐三位专家的意见后，汇总成一份高质量的『面试满分答案』，"
    "再给 2~3 个常见追问。答案要取各专家之长，结构清晰。"
    "直接输出最终答案，不要开场白。"
)

EXPERT_SYSTEMS = {
    "theory": "你是原理官。从原理角度回答问题：为什么要它、核心机制是什么、它怎么工作。说人话，讲机制。",
    "eng": "你是工程官。从实现角度回答问题：怎么落地、用什么组件、有什么坑、怎么测试。",
    "interviewer": "你是面试官。从考察角度回答问题：面试官想听到什么、哪些是加分点、最可能追问什么。",
}

EXPERT_LABELS = {"theory": "原理官", "eng": "工程官", "interviewer": "面试官"}


def build_expert_prompt(question):
    return f"面试题：{question}\n请从你的角度作答，直接输出要点，不要复述题目。"


def build_summary_prompt(question, answers):
    """主席把三个专家的答案拼起来，汇总成满分答案（纯函数，可测）。

    某专家没发言 → 占位符顶替，主席照常汇总（优雅降级，不崩）。
    """
    parts = []
    for key in EXPERT_LABELS:
        txt = answers.get(key)
        if not txt:
            txt = "（该专家未发言）"
        parts.append(f"【{EXPERT_LABELS[key]}】\n{txt}")
    return f"""面试题：{question}
三位专家已发言，请汇总成一份『面试满分答案』并给 2~3 个常见追问。

{chr(10).join(parts)}

输出格式：
# 满分答案
## 一句话版
## 详细版
## 常见追问"""


def run_debate(chair, experts, question):
    """评审团跑一遍。experts = {'theory','eng','interviewer'} 三个 Agent，chair 是主席 Agent。

    流程：同一道题发给三个专家（各自角度、各自独立上下文）→ 收齐 → 主席汇总。
    某专家没说上话 → 汇总占位不崩；主席没说上话 → ok=False。
    """
    answers = {}
    for key, expert in experts.items():
        answers[key] = expert.ask(build_expert_prompt(question))

    summary = chair.ask(build_summary_prompt(question, answers))
    return {
        "ok": summary is not None,
        "answers": answers,
        "summary": summary,
    }

# 被测对象：真正的多 Agent 协作——双脑版（第 19 课）
#
# 第 13 课是"单脑版"：一个模型，靠换 prompt 演两个角色，写手和评审其实共用一份记忆。
# 这课升级成"双脑版"：写手、评审是两个独立的 Agent 对象，**各有各的记忆（messages）**，
# 由协调器（coordinator）调度。协调器只认 Agent 的 .ask() 这一个门——
# 背后是真模型还是假模型，它一概不知道、也不关心（门哲学第三次兑现）。
#
# 心法对照：
#   Agent   = 一个会说话的脑子（角色 + 记忆 + 门）
#   协调器  = 只负责让两个脑子按流程协作，自己不动脑子
#   各记各的账 = 写手记写手的，评审记评审的，互不污染（信息隔离）
import re


# ---------------------- 门：一个 Agent 对象 ----------------------

class Agent:
    """一个 Agent = 角色 + 自己的记忆（messages）+ 一个门（ask）。

    记忆只记它自己的账：别人对它说了什么、它回了什么，全都留档（history）。
    谁装它背后？真模型或 FakeModel 都行——ask 只看 .messages.create() 长什么样。
    这就是"门"：调用方（协调器、演示、测试）永远只碰 .ask() 和 .history()。
    """

    def __init__(self, role, system_prompt, model, model_name="fake"):
        self.role = role
        self.model = model
        self.model_name = model_name
        self.calls = 0
        # 自己的记忆：系统提示永远打底，之后每次对话都追加
        self.messages = [{"role": "system", "content": system_prompt}]

    def ask(self, text):
        """对它说一句话，拿回它的回答，并把这两句都记进它自己的记忆。"""
        self.messages.append({"role": "user", "content": text})
        try:
            resp = self.model.messages.create(
                model=self.model_name, max_tokens=2000, messages=self.messages
            )
            answer = "".join(
                b.text for b in resp.content if getattr(b, "type", None) == "text"
            ) or None
        except Exception:
            answer = None   # 优雅降级：一次调用挂了，返回 None，绝不让协调器崩
        if answer is not None:
            self.messages.append({"role": "assistant", "content": answer})
        self.calls += 1
        return answer

    def history(self):
        """给外人看的记忆（不带 system 提示）。测试/演示用它验证"各记各的账"。"""
        return [m for m in self.messages if m["role"] != "system"]


# ---------------------- 角色人设（写进各自的大脑） ----------------------

WRITER_SYSTEM = (
    "你是写手。你的任务：写内容、按评审意见修改。"
    "直接输出内容本身，不要任何开场白、解释、客套话。"
)

REVIEWER_SYSTEM = (
    "你是严格的评审。你的任务：挑刺，审阅写手交来的内容。"
    "输出必须严格遵守这个格式：\n"
    "【结论】通过 或 需改\n"
    "【意见】需改时写 1-3 条具体意见，用「1.」「2.」编号；通过时写「无」"
)


# ---------------------- 纯函数：三个 prompt ----------------------

def build_draft_prompt(task):
    return f"请为「{task}」写一份内容。"


def build_review_prompt(task, draft):
    return f"审阅下面这份关于「{task}」的内容：\n【被审内容】\n{draft}"


def build_revise_prompt(task, draft, opinions):
    return f"""根据评审意见修改下面这份关于「{task}」的内容：
【评审意见】
{opinions}
【原稿】
{draft}
直接输出修改后的完整内容，不要解释。"""


# ---------------------- 纯函数：解析评审输出 ----------------------

_VERDICT_RE = re.compile(r"【结论】\s*(通过|需改)")
_OPINIONS_RE = re.compile(r"【意见】\s*(.*?)(?=【|$)", re.S)


def parse_review(text):
    """从评审输出抠出 (结论, 意见)。
    解析失败按"需改 + 无意见"处理——保守：宁可不放行，不让烂稿过关。
    """
    m = _VERDICT_RE.search(text)
    verdict = m.group(1) if m else "需改"
    m2 = _OPINIONS_RE.search(text)
    opinions = m2.group(1).strip() if m2 else "无"
    return verdict, opinions


# ---------------------- 协调器：只管流程，不碰脑子和内容质量 ----------------------

def run_collab(writer, reviewer, task, max_rounds=3):
    """协调器：只认 writer.ask / reviewer.ask 两个门，不认识模型。

    流程：写手产稿 → 评审挑刺 → 通过就交；需改就让写手按意见重写 → 再评。
    护栏：max_rounds 兜底（第 3 课 MAX_ITERS 的延伸），到顶拿最后一稿交差，不崩。

    返回 {ok, text, rounds, passed, error, log}：
      ok      协调器本身没翻车（写手/评审说不上话算 ok，只是没通过）
      passed  评审给了「通过」
      rounds  用了多少轮
      log     每一轮的 {round, verdict, opinions, draft}，演示用
    """
    log = []
    draft = writer.ask(build_draft_prompt(task))
    if draft is None:
        return {"ok": False, "text": None, "rounds": 0, "passed": False,
                "error": "写手第一稿就没出来，请重试。", "log": log}

    for round_no in range(1, max_rounds + 1):
        review = reviewer.ask(build_review_prompt(task, draft))
        if review is None:
            return {"ok": True, "text": draft, "rounds": round_no, "passed": False,
                    "error": "评审没说话，拿当前稿交差。", "log": log}
        verdict, opinions = parse_review(review)
        log.append({"round": round_no, "verdict": verdict, "opinions": opinions,
                    "draft": draft})
        if verdict == "通过" or opinions == "无":
            return {"ok": True, "text": draft, "rounds": round_no, "passed": True,
                    "error": None, "log": log}
        revised = writer.ask(build_revise_prompt(task, draft, opinions))
        if revised is None:
            return {"ok": True, "text": draft, "rounds": round_no, "passed": False,
                    "error": "写手改不出来，拿当前稿交差。", "log": log}
        draft = revised

    return {"ok": True, "text": draft, "rounds": max_rounds, "passed": False,
            "error": f"评审 {max_rounds} 轮都没给通过，拿最后一稿交差。", "log": log}

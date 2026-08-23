# 被测对象：Agent 记忆系统（第二十一课）
#
# 核心矛盾：模型天生失忆（第一课就说过——每次调用都是全新的脑子），
# 你替它记的 messages 也只活在内存里，程序一关就清零。
# 这课给 agent 一个"记事本"：把重要的事存进文件，下次启动还能想起来。
#
# 三块：
#   ① MemoryStore   记事本本身：增 / 查 / 存文件 / 读文件
#                    文件路径就是"门"——生产传真路径，测试传临时文件。
#   ② extract_facts 什么时候该记：从对话里抽出"关于用户的事实"
#                    extractor 参数是"门"——不传用内置规则（免费、确定、可测），
#                    传了交给它提炼（比如将来让 LLM 总结，花 token 但更聪明）。
#   ③ remember_last_turn / build_memory_prompt
#                    怎么用：一轮对话结束自动记；记忆贴进 system prompt，
#                    让模型"一开场就知道你是谁"（跟装手、裁判一个套路）。
#
# 面试八股：agent 的"长记忆" = 把状态落盘（文件/数据库），重启再读回来。
# 规则提取是免费假门，LLM 总结是真门——又是熟悉的"门哲学"。
import json
import os
import re


# ---------------------- ① 记事本本身：MemoryStore ----------------------

class MemoryStore:
    """一条一条事实的记事本，存 JSON 文件。

    path 是"门"：生产传 learn-agent 外面的 agent_memory.json，测试传临时文件。
    max_items 是护栏：记忆无脑堆会撑爆系统提示（跟第十课预算一个道理），
    超了就把最老的挤掉，永远只留最新的 max_items 条。
    """

    def __init__(self, path=None, max_items=50):
        self.path = path
        self.max_items = max_items
        self._items = []

    # ---- 读 / 写文件 ----

    def load(self):
        """从文件读回记忆。文件不存在 / 坏了 / 读不了 → 空列表，绝不崩。
        优雅降级（第九课的老朋友）：宁可这轮没记忆，不能让 agent 一启动就炸。
        """
        self._items = []
        if not self.path or not os.path.exists(self.path):
            return self._items
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._items = [str(x) for x in data][-self.max_items:]
        except Exception:
            self._items = []
        return self._items

    def save(self):
        """把记忆写回文件。写失败（磁盘满、没权限）就吞掉，不崩。
        记不住比崩溃好——agent 的命是主循环，记忆是身外之物。
        先写临时文件再改名（os.replace）：写入中途挂了也不会留半个文件。
        """
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    # ---- 增 / 查 ----

    def add(self, text):
        """记一条事实。跟已有的重复就不记（记事本不该抄两遍）；
        超了 max_items 把最老的挤掉。返回这条到底记没记（True/False）。
        """
        text = text.strip()
        if not text:
            return False
        if text in self._items:
            return False
        self._items.append(text)
        if len(self._items) > self.max_items:
            self._items = self._items[-self.max_items:]
        return True

    def all(self):
        """当前所有记忆（只读副本，调用方怎么改都不影响记事本本体）。"""
        return list(self._items)

    def remember(self, text):
        """一条龙：记进去 + 立刻存盘。production 里每轮对话结束叫一次。"""
        ok = self.add(text)
        if ok:
            self.save()
        return ok


# ---------------------- ② 什么时候该记：extract_facts ----------------------

# 把文本切成"一句一句"（只认句号/问号/叹号/换行，逗号不断句）
_SPLIT_RE = re.compile(r"[。！？!?\n]+")

def _explicit_fact(chunk):
    """显式命令判断：以"记住/别忘了"开头 → 把后面的话当成要记的事实。

    关键区分：命令 vs 应答。
      "记住：我周五交简历" / "别忘了周四开会" → 是命令，记后面的内容。
      "记住了" / "我记住了"               → 是应答，不是要记的事实。
    所以"记住/别忘了"后面必须还跟着实打实的内容（>=2 个字、不以"了"开头）。
    """
    for pre in ("记住", "别忘了"):
        if not chunk.startswith(pre):
            continue
        rest = chunk[len(pre):].lstrip("：:，, ")
        if not rest or len(rest) < 2 or rest.startswith("了"):
            return None
        return rest
    return None

# 常见"关于用户的事实"句式（规则是死的，够用就行；生产常换成 LLM 提炼）
_FACT_PATTERNS = re.compile(
    r"(?:"
    r"我(?:叫|的名字是|姓)"                       # 身份：我叫 / 我的名字是 / 我姓
    r"|我(?:住在|来自|家住)"                       # 地点：我住在 / 我来自
    r"|我在.{0,8}(?:工作|上班|上学|读书|读研)"     # 职业/学业：我在……工作
    r"|我(?:喜欢|爱|爱好|擅长)"                   # 偏好：我喜欢 / 我擅长
    r")"
)


def extract_facts(text, extractor=None):
    """从一段话里抽出"值得记住的事实"，返回列表（可能空）。

    extractor 是"门"：
      不传 → 用内置规则（免费、确定、可测——测试全走这条）。
      传了 → 整段话交给它，用它的返回值当事实（比如将来让 LLM 总结）。
    同一个门换实现，调用方一行不用改——第 17 课假门/真门的老套路。
    """
    if not text:
        return []
    if extractor is not None:
        result = extractor(text)
        if isinstance(result, (list, tuple)):
            return [str(x).strip() for x in result if str(x).strip()]
        return []
    return _rule_facts(text)


def _rule_facts(text):
    facts = []
    for chunk in _SPLIT_RE.split(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        explicit = _explicit_fact(chunk)
        if explicit:
            facts.append(explicit)   # "记住：X" → 记 X
            continue
        if _FACT_PATTERNS.search(chunk):
            facts.append(chunk)
    return facts


# ---------------------- ③ 怎么用：自动记 + 拼进 system prompt ----------------------

def remember_last_turn(store, messages, extractor=None):
    """一轮对话结束，把"刚学到的关于用户的事实"写进记事本。

    messages 是 agent 的对话账本（Anthropic 格式）。它只抽两样：
      - 最后一条纯文本 user 消息（真问题；tool_result 那种"工具结果"不算）
      - 最后一条带文字的 assistant 回答
    这两段的逻辑跟第九课裁判 judge_last_turn 一模一样——抽"最近一问 + 最近一答"。
    返回新记了几条（记重复了 / 没可记的 → 0）。
    """
    # 最后一条纯文本 user 消息
    task = next(
        (m["content"] for m in reversed(messages)
         if m.get("role") == "user" and isinstance(m.get("content"), str)),
        "",
    )
    # 最后一条带文字的 assistant 回答
    reply = ""
    for m in reversed(messages):
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        texts = (
            [b.text for b in content if getattr(b, "type", None) == "text"]
            if isinstance(content, list)
            else ([content] if isinstance(content, str) else [])
        )
        if texts:
            reply = "\n".join(texts)
            break

    added = 0
    for text in (task, reply):
        for fact in extract_facts(text, extractor):
            if store.add(fact):
                added += 1
    if added:
        store.save()
    return added


MEMORY_HEADER = "【长期记忆 · 重启不忘】"


def build_memory_prompt(memories):
    """把一堆记忆拼成一段"入场自我介绍"，准备贴到 system prompt 里。
    模型每次回答前都会看到这段——它"记得你是谁"全靠这段，不靠脑子。
    """
    lines = [MEMORY_HEADER]
    if not memories:
        lines.append("（还没有记忆）")
    else:
        for i, m in enumerate(memories, 1):
            lines.append(f"{i}. {m}")
    return "\n".join(lines)

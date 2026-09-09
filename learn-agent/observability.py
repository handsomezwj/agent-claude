# observability.py —— 多 Agent 企业级加固 · 可观测性层（第二步）
#
# 问题：多 Agent 一次要调 3~4 次模型（每环/每人一次）。任何一个环节慢了、挂了、
#       被重试救回来、被熔断挡住，用户只看到一句最终结果——"中断（方案）"。
#       可问题是：是哪一环拖的？跑了多久？重试了几次？熔断介入没有？黑盒里全看不见。
#
# 答案：可观测性（Observability）——每次运行留一份"病历"：
#       谁、什么时候、跑了多久、成败如何，一笔一笔记下来。看病要病历，
#       修多 Agent 系统要 trace。
#
# 心法对照（面试可讲）：
#   日志(logging)  = 流水账：程序随手写给运维看的，人肉翻
#   指标(metrics)  = 计数器/仪表盘：请求量、错误率、P95 延迟
#   trace(追踪)    = 一条请求从进来到出去，每一段花在哪（这课做这个）
#   可观测性三件套 = 日志 + 指标 + trace。
#
# 设计照旧：纯逻辑 + 注入"门"。clock 可注入假时钟（测试免真等），
# agent 可注入真模型/FakeModel，trace 只记"谁被叫了、结果如何"，不掺和业务。
import time


# ---------------------- 一段记录（span） ----------------------

class Span:
    """病历里的一行：一段有名字的时间片段（可套娃——父段套子段）。

    状态（status）：ok 正常走完 / error 挂了 / timeout 超时 / degraded 降级……
    谁来定状态？异常退出自动标 error；其余由调用方在 with 块里手动标。
    """

    def __init__(self, name, started):
        self.name = name
        self.started = started      # clock 读数（注入的）
        self.ended = None
        self.status = None          # 没标 = 还没定论
        self.note = ""              # 人话备注：回答几字 / 为什么挂
        self.children = []          # 子段（更细的步骤）

    @property
    def duration(self):
        """跑了多久（秒）。没结束 = None（还在跑 / 没跑成）。"""
        if self.ended is None:
            return None
        return self.ended - self.started

    def to_dict(self):
        return {
            "name": self.name,
            "started": self.started,
            "duration": self.duration,
            "status": self.status,
            "note": self.note,
            "children": [c.to_dict() for c in self.children],
        }


# ---------------------- 病历本（Tracer） ----------------------

class Tracer:
    """病历本：用 with 围出每一段（span），支持嵌套；最后 export() 导出。

    用法：
        tr = Tracer()
        with tr.trace("整次排障") as top:
            with tr.trace("诊断官") as sp:
                answer = diag.ask(q)
                if not answer: sp.status = "error"
            with tr.trace("根因官") as sp:
                ...
        print(tr.as_text())     # 人话病历
        tr.export()             # dict 树，能 json.dumps 存档

    clock：可注入的"现在几点"。测试传假时钟，能精确断言每段耗时，不真等。
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._stack = []        # 还没结束的段（套娃靠它）
        self.roots = []         # 完成/在跑中的根段（一次运行 = 一个根）

    def trace(self, name):
        """开一段。用 `with tracer.trace('名字') as sp:` 包住要计时的那步。"""
        return _SpanCtx(self, name)

    def _open(self, name):
        parent = self._stack[-1] if self._stack else None
        sp = Span(name, self._clock())
        if parent is None:
            self.roots.append(sp)
        else:
            parent.children.append(sp)
        self._stack.append(sp)
        return sp

    def _close(self, sp, status, note):
        sp.ended = self._clock()
        if sp.status is None and status is not None:
            sp.status = status      # 异常退出才由这里标；手动标过的不覆盖
        if note:
            sp.note = note
        if self._stack and self._stack[-1] is sp:
            self._stack.pop()

    def export(self):
        """导出整本病历：dict 树（能 json.dumps 存档，重启后还能回看）。"""
        return [r.to_dict() for r in self.roots]

    def as_text(self):
        """打印用的人话病历：缩进表示嵌套，每行 = 谁 + 状态 + 耗时 + 备注。"""
        return "\n".join(self._render_lines(r, 0) for r in self.roots)

    def _render_lines(self, sp, depth):
        dur = f"{sp.duration * 1000:.0f}ms" if sp.duration is not None else "--"
        line = f"{'  ' * depth}· {sp.name} [{sp.status or '?'}] {dur}"
        if sp.note:
            line += f"  ({sp.note})"
        return "\n".join([line] + [self._render_lines(c, depth + 1) for c in sp.children])

    def summary(self):
        """一行速览：所有没子段的"叶子"（每段实际动作）成败串起来，一眼扫。"""
        parts = []
        for r in self.roots:
            self._collect_leaves(r, parts)
        return " → ".join(f"{name}:{status or '?'}" for name, status in parts) or "(空病历)"

    def _collect_leaves(self, sp, parts):
        if not sp.children:
            parts.append((sp.name, sp.status))
        for c in sp.children:
            self._collect_leaves(c, parts)


class _SpanCtx:
    """tracer.trace() 返回的上下文管理器：enter 开段，exit 记结束时间。"""

    def __init__(self, tracer, name):
        self._tracer = tracer
        self._name = name
        self.span = None

    def __enter__(self):
        self.span = self._tracer._open(self._name)
        return self.span

    def __exit__(self, exc_type, exc, tb):
        self._tracer._close(self.span, "error" if exc_type is not None else None, None)
        return False    # 异常照常往上抛——trace 只记录，不拦事


# ---------------------- 透明门：给 Agent 记 trace（TracedAgent） ----------------------

class TracedAgent:
    """把任意有 .ask()/.history() 的对象包上 trace：每次 ask 记成一段病历。

    跟 reliability.HardenedAgent 是同一款"透明门"：协调器拿到的还是 ask/history
    两个门，行为却多了"记账"。还能套着用：TracedAgent(HardenedAgent(agent))——
    先让硬化层处理重试/熔断，trace 记下最终成败。门套门，谁都不用改。

    label：病历里这段叫什么。默认借用内层 agent 的 .role（诊断官/根因官…）。
    """

    def __init__(self, agent, tracer, label=None):
        self._inner = agent
        self._tracer = tracer
        self.label = label or getattr(agent, "role", None) or type(agent).__name__

    def ask(self, text):
        with self._tracer.trace(self.label) as sp:
            answer = self._inner.ask(text)
            if not answer:
                # 内层挂了 / 超时 / 被熔断 / 重试耗尽 → 返回 None（优雅降级）
                sp.status = "error"
                sp.note = "没拿到回答（挂/超时/熔断/重试耗尽）"
            else:
                sp.status = "ok"
                sp.note = f"回答 {len(answer)} 字"
        return answer

    def history(self):
        return self._inner.history()

    def __getattr__(self, name):
        # role / calls 等没定义的属性转发给内层，演示打印照常可用
        return getattr(self._inner, name)


# ---------------------- 从存档回放病历 ----------------------

def format_text(exports):
    """把 export() 出来的 dict 树渲染回人话（存了档、重启后还能看）。"""
    lines = []

    def render(sp, depth):
        dur = f"{sp['duration'] * 1000:.0f}ms" if sp.get("duration") is not None else "--"
        line = f"{'  ' * depth}· {sp['name']} [{sp.get('status') or '?'}] {dur}"
        if sp.get("note"):
            line += f"  ({sp['note']})"
        lines.append(line)
        for c in sp.get("children", []):
            render(c, depth + 1)

    for root in exports:
        render(root, 0)
    return "\n".join(lines)

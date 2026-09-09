# observability 测试：observability.py（企业级加固 · 可观测性层）
#
# 测什么（全离线、零模型）：
#   Tracer       嵌套 span 记对父子、状态手动标、异常自动标 error、导出成 dict 树
#   假时钟       注入 clock → 耗时可控精确断言（不用真等）
#   TracedAgent  透明门：ok 记 ok+字数、None 记 error、label 借角色、ask/history 透传
#   format_text  export → json → 回放渲染，重启后病历还在
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from observability import Tracer, TracedAgent, format_text


class FakeClock:
    """假时钟：注入 Tracer(clock=...)，用 advance() 精确拨时间，测试免真等。"""

    def __init__(self, start=0.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class StubAgent:
    """最简的"有 ask/history 的 Agent"：text 带 'boom' → 返回 None（模拟挂掉）。"""

    def __init__(self, role, answer="正常回答"):
        self.role = role
        self.answer = answer
        self.calls = 0

    def ask(self, text):
        self.calls += 1
        if "boom" in text:
            return None
        return self.answer

    def history(self):
        return ["记录"]


class TestTracerBasics(unittest.TestCase):
    """病历本：嵌套 span、状态、耗时、导出。"""

    def test_nested_spans_record_children_and_duration(self):
        clock = FakeClock(start=10.0)
        tr = Tracer(clock=clock)
        with tr.trace("整次排障") as top:
            with tr.trace("诊断官"):
                clock.advance(0.4)
            with tr.trace("根因官"):
                clock.advance(1.2)
        # 一个根、两个孩子、嵌套挂对了
        self.assertEqual(len(tr.roots), 1)
        self.assertIs(tr.roots[0], top)
        self.assertEqual([c.name for c in top.children], ["诊断官", "根因官"])
        # 假时钟 → 耗时精确可断言（浮点用近似比，避免 0.4000…036）
        self.assertAlmostEqual(top.children[0].duration, 0.4)
        self.assertAlmostEqual(top.children[1].duration, 1.2)
        self.assertAlmostEqual(top.duration, 1.6)

    def test_manual_error_status_and_note(self):
        tr = Tracer()
        with tr.trace("根因官") as sp:
            sp.status = "error"
            sp.note = "模型超时"
        sp = tr.roots[0]
        self.assertEqual(sp.status, "error")
        self.assertEqual(sp.note, "模型超时")

    def test_default_status_is_none_until_declared(self):
        tr = Tracer()
        with tr.trace("方案官"):
            pass
        self.assertIsNone(tr.roots[0].status)

    def test_export_is_dict_tree_json_serializable(self):
        tr = Tracer()
        with tr.trace("整次排障") as top:
            with tr.trace("诊断官"):
                pass
        tree = tr.export()
        self.assertEqual(tree[0]["name"], "整次排障")
        self.assertEqual(tree[0]["children"][0]["name"], "诊断官")
        # 能 json 序列化 = 能存档（病历留到重启后）
        roundtrip = json.loads(json.dumps(tree, ensure_ascii=False))
        self.assertEqual(roundtrip, tree)

    def test_exception_marks_error_and_rethrows(self):
        tr = Tracer()
        with self.assertRaises(ValueError):
            with tr.trace("会炸的段") as sp:
                raise ValueError("下游崩了")
        # trace 只记录不拦事：异常照常往外抛；但这一段已标 error、已记结束
        self.assertEqual(tr.roots[0].status, "error")
        self.assertIsNotNone(tr.roots[0].ended)

    def test_manual_status_not_overwritten_by_normal_exit(self):
        # 手动标过 error，正常走完 with 也不该被盖回 None
        tr = Tracer()
        with tr.trace("段") as sp:
            sp.status = "error"
        self.assertEqual(tr.roots[0].status, "error")

    def test_summary_lists_leaves_in_order(self):
        tr = Tracer()
        with tr.trace("整次排障"):
            with tr.trace("诊断官"):
                pass
            with tr.trace("根因官") as sp:
                sp.status = "error"
        self.assertEqual(tr.summary(), "诊断官:? → 根因官:error")

    def test_as_text_renders_indented_lines(self):
        tr = Tracer()
        with tr.trace("整次排障") as top:
            with tr.trace("诊断官") as sp:
                sp.status = "ok"
            top.status = "ok"
        text = tr.as_text()
        self.assertIn("整次排障 [ok] ", text)   # 根状态=ok
        self.assertIn("· 诊断官 [ok]", text)     # 孩子缩进一行
        self.assertIn("  · 诊断官", text)         # 确实有缩进


class TestTracedAgent(unittest.TestCase):
    """透明记账门：包上任何 ask/history 对象，每次 ask 记一段病历。"""

    def test_ok_ask_records_ok_span_with_note(self):
        tr = Tracer()
        inner = StubAgent("诊断官", answer="发现连接池耗尽")
        ta = TracedAgent(inner, tr)
        self.assertEqual(ta.ask("查一下"), "发现连接池耗尽")   # 回答原样透传
        sp = tr.roots[0]
        self.assertEqual(sp.name, "诊断官")      # label 借了内层 role
        self.assertEqual(sp.status, "ok")
        self.assertIn("回答", sp.note)

    def test_none_result_marks_error(self):
        tr = Tracer()
        ta = TracedAgent(StubAgent("根因官"), tr)
        self.assertIsNone(ta.ask("boom 一下"))     # 挂了 → None（优雅降级）
        self.assertEqual(tr.roots[0].status, "error")

    def test_label_override(self):
        tr = Tracer()
        ta = TracedAgent(StubAgent("诊断官"), tr, label="第一环")
        ta.ask("查")
        self.assertEqual(tr.roots[0].name, "第一环")

    def test_history_and_getattr_passthrough(self):
        tr = Tracer()
        inner = StubAgent("诊断官")
        ta = TracedAgent(inner, tr)
        self.assertEqual(ta.history(), ["记录"])     # history 透传
        ta.ask("查")
        self.assertEqual(ta.calls, 1)                 # calls 等属性转发内层


class TestFormatText(unittest.TestCase):
    """存档回放：export 的 dict 树能渲染回和 as_text 一样的病历。"""

    def test_roundtrip_matches_as_text(self):
        tr = Tracer()
        with tr.trace("整次排障") as top:
            with tr.trace("诊断官") as sp:
                sp.status = "ok"
                sp.note = "回答 6 字"
            with tr.trace("根因官") as sp:
                sp.status = "error"
        stored = json.loads(json.dumps(tr.export(), ensure_ascii=False))
        self.assertEqual(format_text(stored), tr.as_text())


if __name__ == "__main__":
    unittest.main()

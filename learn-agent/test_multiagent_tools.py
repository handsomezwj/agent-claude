# 多 Agent 工具封装测试：multiagent_tools.py（接进 agent-claude.py 的「手」）
#
# 测什么：
#   三个工具正常跑通     剧本按调用顺序喂，返回文本含各环节输出
#   安全护栏           流水线方案官说出「重启」→ 返回带 ⚠ 护栏提示
#   优雅降级            某环/某人挂 → 返回带前缀的说明文本，绝不抛异常
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_loop import FakeModel, FakeResponse, text_block
from reliability import CircuitBreaker
from observability import Tracer
import multiagent_tools as mt


def script(*texts):
    """按调用顺序排的剧本：每个文本 = 一次 ask 的回答。"""
    return FakeModel([FakeResponse("end_turn", [text_block(t)]) for t in texts])


class FlakyModel:
    """会抽风的下游：前 fail_first 次调用抛连接错误，之后交给内层 FakeModel。

    演"网络抖动 / 下游暂时不可用"——这正是可靠性层（重试 / 熔断）要扛的场景。
    always_fail=True = 一直坏（演雪崩，看熔断怎么快速失败）。
    """

    def __init__(self, inner_model, fail_first=0, always_fail=False):
        self._inner = inner_model
        self.fail_first = fail_first
        self.always_fail = always_fail
        self.failed = 0
        self.calls = 0

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.calls += 1
        if self.always_fail or self.failed < self.fail_first:
            self.failed += 1
            raise ConnectionError("下游暂时不可用（模拟网络抖动）")
        return self._inner.create(**kwargs)


class TestTroubleshoot(unittest.TestCase):
    """流水线：诊断 → 根因 → 方案，三次调用。"""

    def test_runs_three_stages(self):
        out = mt.troubleshoot("服务好像挂了", script("现场报告X", "根因Y", "方案Z"))
        self.assertIn("现场报告X", out)
        self.assertIn("根因Y", out)
        self.assertIn("方案Z", out)

    def test_guard_warning_surfaced(self):
        # 方案官建议里带「重启」→ 护栏拦住，提示需人工确认
        out = mt.troubleshoot("服务好像挂了", script("报告", "根因", "建议重启服务"))
        self.assertIn("安全护栏", out)
        self.assertIn("重启", out)

    def test_interrupted_stage_not_crash(self):
        # 剧本只够两环 → 第三环（方案官）说不出 → 优雅降级，不抛异常
        out = mt.troubleshoot("服务好像挂了", script("报告", "根因"))
        self.assertIn("中断", out)

    def test_all_silent_not_crash(self):
        out = mt.troubleshoot("服务好像挂了", FakeModel([]))
        self.assertIn("中断", out)


class TestOpsReport(unittest.TestCase):
    """主管-工人：三个工人 + 主管汇总，四次调用。"""

    def test_returns_report(self):
        out = mt.ops_report("出一份排查报告", script("状态S", "日志L", "风险R", "主管总报告"))
        self.assertIn("主管总报告", out)
        self.assertIn("排查报告", out)

    def test_silent_boss_not_ok(self):
        # 剧本只够三个工人 → 主管第 4 次调用说不出 → ok=False
        out = mt.ops_report("出一份排查报告", script("状态S", "日志L", "风险R"))
        self.assertIn("主管", out)

    def test_all_silent_not_crash(self):
        out = mt.ops_report("出一份排查报告", FakeModel([]))
        self.assertIn("主管", out)


class TestInterviewPrep(unittest.TestCase):
    """评审团：三个专家 + 主席汇总，四次调用。"""

    def test_returns_summary(self):
        out = mt.interview_prep("讲一下 RAG", script("原理A", "工程B", "面试C", "满分答案D"))
        self.assertIn("满分答案D", out)
        self.assertIn("讲一下 RAG", out)

    def test_silent_chair_not_ok(self):
        # 剧本只够三个专家 → 主席说不出 → ok=False
        out = mt.interview_prep("讲一下 RAG", script("原理A", "工程B", "面试C"))
        self.assertIn("主席", out)

    def test_all_silent_not_crash(self):
        out = mt.interview_prep("讲一下 RAG", FakeModel([]))
        self.assertIn("主席", out)


class TestReliabilityIntegration(unittest.TestCase):
    """企业级加固接进工具（multiagent_tools + reliability.py）：
    重试扛瞬时抖动、熔断防雪崩、对照不配 = 一挂就断。
    """

    def test_retry_saves_transient_failure(self):
        # 诊断官前 2 次调用下游抽风 → retries=2 指数退避后第 3 次成功，整条流水线跑完
        flaky = FlakyModel(script("现场报告X", "根因Y", "方案Z"), fail_first=2)
        out = mt.troubleshoot("服务好像挂了", flaky, retries=2)
        self.assertIn("现场报告X", out)
        self.assertIn("根因Y", out)
        self.assertIn("方案Z", out)

    def test_no_retry_gives_up_on_first_failure(self):
        # 对照：不配 retries（默认 0）→ 诊断官第一次抽风就中断（优雅降级，不重复白打）
        flaky = FlakyModel(script("现场报告X", "根因Y", "方案Z"), fail_first=1)
        out = mt.troubleshoot("服务好像挂了", flaky)
        self.assertIn("中断", out)

    def test_breaker_opens_and_stops_hammering(self):
        # 下游一直坏：熔断器连败 2 次跳闸，第三、四个角色直接快速失败不再碰模型
        flaky = FlakyModel(script("状态S", "日志L", "风险R", "总报告"), always_fail=True)
        breaker = CircuitBreaker(fail_threshold=2, recovery_time=1e9)
        out = mt.ops_report("出一份排查报告", flaky, retries=0, breaker=breaker)
        self.assertIn("主管", out)                 # 优雅降级，绝不抛异常
        self.assertEqual(breaker.state, "OPEN")    # 保险丝跳闸
        # 只打了两发就跳闸：熔断 = 快速失败，不再把坏下游打到雪崩
        self.assertEqual(flaky.calls, 2)


class TestObservabilityIntegration(unittest.TestCase):
    """企业级加固接进工具（multiagent_tools + observability.py）：
    传 tracer=… 就自动给每个角色记病历（谁/状态/耗时）；不传 = 原样零变化。
    """

    def _statuses(self, tracer):
        """取第一次运行顶层病历里所有叶子段的状态。"""
        leaves = []
        for child in tracer.roots[0].children:
            leaves.append((child.name, child.status))
        return leaves

    def test_tracer_records_all_stages_ok(self):
        tr = Tracer()
        out = mt.troubleshoot("服务好像挂了", script("现场报告X", "根因Y", "方案Z"),
                              tracer=tr)
        # 顶层一段病历，三个角色叶子全 ok；返回文本是干净的（病历没混进去）
        self.assertEqual(len(tr.roots), 1)
        self.assertEqual(tr.roots[0].status, "ok")
        self.assertEqual(self._statuses(tr),
                         [("诊断官", "ok"), ("根因官", "ok"), ("方案官", "ok")])
        self.assertIn("现场报告X", out)
        self.assertNotIn("· ", out)

    def test_tracer_marks_failed_ring_and_top(self):
        # 剧本只够两环 → 方案官说不出 → 病历把"断在第几环"记下来
        tr = Tracer()
        mt.troubleshoot("服务好像挂了", script("现场报告X", "根因Y"), tracer=tr)
        self.assertEqual(tr.roots[0].status, "error")          # 顶层标 error
        self.assertEqual(self._statuses(tr),
                         [("诊断官", "ok"), ("根因官", "ok"), ("方案官", "error")])

    def test_tracer_marks_retry_saved_as_ok(self):
        # 重试救回来的，病历记 ok（trace 记最终成败，不是过程中的磕绊）
        flaky = FlakyModel(script("现场报告X", "根因Y", "方案Z"), fail_first=2)
        tr = Tracer()
        mt.troubleshoot("服务好像挂了", flaky, retries=2, tracer=tr)
        self.assertEqual(tr.roots[0].status, "ok")
        self.assertEqual([c.status for c in tr.roots[0].children],
                         ["ok", "ok", "ok"])

    def test_ops_report_records_boss_and_workers(self):
        tr = Tracer()
        mt.ops_report("出一份排查报告",
                      script("状态S", "日志L", "风险R", "主管总报告"),
                      tracer=tr)
        self.assertEqual(len(tr.roots[0].children), 4)          # 3 工人 + 主管
        self.assertEqual([c.status for c in tr.roots[0].children],
                         ["ok", "ok", "ok", "ok"])

    def test_no_tracer_still_runs_clean(self):
        # 对照：不传 tracer → 行为与没接 trace 前完全一致（零开销零污染）
        out = mt.troubleshoot("服务好像挂了", script("现场报告X", "根因Y", "方案Z"))
        self.assertIn("现场报告X", out)
        self.assertIn("方案Z", out)


if __name__ == "__main__":
    unittest.main()

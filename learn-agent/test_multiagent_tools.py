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
import multiagent_tools as mt


def script(*texts):
    """按调用顺序排的剧本：每个文本 = 一次 ask 的回答。"""
    return FakeModel([FakeResponse("end_turn", [text_block(t)]) for t in texts])


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


if __name__ == "__main__":
    unittest.main()

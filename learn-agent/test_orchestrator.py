# 多 Agent 专项测试：ops_orchestrator.py 主管-工人模式（模式 A）
#
# 测什么：
#   build_tasks            拆成三个独立子任务，每个工人拿到自己的任务 + 证据
#   build_summary_prompt   主管汇总包含所有工人输出；缺失的工人用占位符
#   run_orchestrator       三个工人各跑一次 + 主管一次；主管输入包含全部结果
#   优雅降级               工人挂 → 占位不崩；主管挂 → ok=False
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_loop import FakeModel, FakeResponse, text_block
from multi_agent import Agent
from ops_orchestrator import (
    ORCHESTRATOR_SYSTEM, WORKER_SYSTEMS, WORKER_LABELS,
    build_tasks, build_summary_prompt, run_orchestrator,
)

DATA_DIR = Path(__file__).resolve().parent / "ops_demo"


def make_agents(status_txt, log_txt, risk_txt, boss_txt):
    """一个主管 + 三个工人，各自演一句剧本。传 None = 该 agent 一句话也说不出。"""
    def one(system, text):
        if text is None:
            return Agent("x", system, FakeModel([]))  # 空剧本 → ask 返回 None
        return Agent("x", system, FakeModel([FakeResponse("end_turn", [text_block(text)])]))
    return {
        "boss": one(ORCHESTRATOR_SYSTEM, boss_txt),
        "status": one(WORKER_SYSTEMS["status"], status_txt),
        "log": one(WORKER_SYSTEMS["log"], log_txt),
        "risk": one(WORKER_SYSTEMS["risk"], risk_txt),
    }


class TestBuildTasks(unittest.TestCase):
    def setUp(self):
        self.tasks = build_tasks("证据ABC")

    def test_three_independent_tasks(self):
        self.assertEqual(set(self.tasks.keys()), {"status", "log", "risk"})

    def test_each_task_carries_evidence(self):
        # 每个工人拿到同一份证据（材料共享可以，脑子各管各的）
        for task in self.tasks.values():
            self.assertIn("证据ABC", task)

    def test_each_task_has_own_focus(self):
        # 各人干各的活：状态 / 日志 / 风险，任务描述互不串味
        self.assertIn("服务状态", self.tasks["status"])
        self.assertIn("日志", self.tasks["log"])
        self.assertIn("风险", self.tasks["risk"])


class TestSummaryPrompt(unittest.TestCase):
    def test_contains_all_workers(self):
        p = build_summary_prompt("问题", {"status": "S", "log": "L", "risk": "R"})
        self.assertIn("S", p)
        self.assertIn("L", p)
        self.assertIn("R", p)
        self.assertIn("排查报告", p)

    def test_missing_worker_uses_placeholder(self):
        # 优雅降级：没交结果的工人用占位符，主管照常汇总，不崩
        p = build_summary_prompt("问题", {"status": "S"})
        self.assertIn("未交结果", p)
        self.assertIn("S", p)


class TestRunOrchestrator(unittest.TestCase):
    def test_runs_all_once(self):
        agents = make_agents("状态:停止", "日志异常X", "风险Y", "最终报告")
        result = run_orchestrator(agents["boss"],
                                  {"status": agents["status"], "log": agents["log"], "risk": agents["risk"]},
                                  "问题", DATA_DIR)
        self.assertTrue(result["ok"])
        self.assertEqual(result["report"], "最终报告")
        self.assertEqual(result["worker_results"]["status"], "状态:停止")
        # 三个工人 + 主管，各只跑一次
        self.assertEqual(agents["status"].calls, 1)
        self.assertEqual(agents["log"].calls, 1)
        self.assertEqual(agents["risk"].calls, 1)
        self.assertEqual(agents["boss"].calls, 1)

    def test_each_agent_owns_memory(self):
        agents = make_agents("S", "L", "R", "B")
        run_orchestrator(agents["boss"], {"status": agents["status"], "log": agents["log"], "risk": agents["risk"]},
                         "问题", DATA_DIR)
        for key in ("boss", "status", "log", "risk"):
            hist = agents[key].history()
            self.assertEqual(len(hist), 2)          # 1 user + 1 assistant，各管各的账

    def test_boss_input_contains_all_worker_results(self):
        agents = make_agents("状态:停止", "日志异常X", "风险Y", "B")
        run_orchestrator(agents["boss"], {"status": agents["status"], "log": agents["log"], "risk": agents["risk"]},
                         "问题", DATA_DIR)
        boss_input = agents["boss"].history()[0]["content"]
        self.assertIn("状态:停止", boss_input)
        self.assertIn("日志异常X", boss_input)
        self.assertIn("风险Y", boss_input)

    def test_silent_worker_still_ok(self):
        # 工人挂 → 占位符顶替，主管照常汇总，流水线不崩
        agents = make_agents(None, "日志异常X", "风险Y", "最终报告")
        result = run_orchestrator(agents["boss"],
                                  {"status": agents["status"], "log": agents["log"], "risk": agents["risk"]},
                                  "问题", DATA_DIR)
        self.assertTrue(result["ok"])
        boss_input = agents["boss"].history()[0]["content"]
        self.assertIn("未交结果", boss_input)

    def test_silent_boss_not_ok(self):
        agents = make_agents("S", "L", "R", None)
        result = run_orchestrator(agents["boss"],
                                  {"status": agents["status"], "log": agents["log"], "risk": agents["risk"]},
                                  "问题", DATA_DIR)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()

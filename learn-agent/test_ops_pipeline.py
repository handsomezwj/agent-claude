# 多 Agent 专项测试：ops_pipeline.py 三环接力 + 护栏兜底
#
# 测什么：
#   collect_evidence        证据包含服务状态 / 带行号日志 / ERROR 现场（纯函数）
#   接力 prompt             根因官只拿到诊断官的报告，方案官只拿到根因分析
#   guard_remedy            英文黑名单 + 中文破坏性词双保险（纯函数）
#   run_pipeline            三环按顺序各跑一次、各记各的账、护栏警告进结果
#   优雅降级                任一环说不上话 → ok=False + stage 标出哪环挂了
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_loop import FakeModel, FakeResponse, text_block
from multi_agent import Agent
from ops_pipeline import (
    DIAG_SYSTEM, ROOTCAUSE_SYSTEM, REMEDY_SYSTEM,
    collect_evidence,
    build_diag_prompt, build_rootcause_prompt, build_remedy_prompt,
    guard_remedy, run_pipeline,
)

DATA_DIR = Path(__file__).resolve().parent / "ops_demo"


def make_agents(diag_txt, root_txt, remedy_txt):
    """三环各配一个演一句剧本的假模型。传 None = 该环一句话也说不出。"""
    def one(text):
        if text is None:
            return FakeModel([])  # 空剧本：一开口就超出剧本 → ask 返回 None
        return FakeModel([FakeResponse("end_turn", [text_block(text)])])
    return {
        "diag": Agent("诊断官", DIAG_SYSTEM, one(diag_txt)),
        "root": Agent("根因官", ROOTCAUSE_SYSTEM, one(root_txt)),
        "remedy": Agent("方案官", REMEDY_SYSTEM, one(remedy_txt)),
    }


class TestCollectEvidence(unittest.TestCase):
    def setUp(self):
        self.evidence = collect_evidence(DATA_DIR)

    def test_contains_service_status(self):
        self.assertIn("order-api", self.evidence)
        self.assertIn("状态", self.evidence)

    def test_contains_tail_lines_with_number(self):
        # 日志尾部带原行号，方便回答里引用作证据
        self.assertIn("10:05:30 CRITICAL", self.evidence)

    def test_contains_error_keyword_hits(self):
        # 默认按 ERROR 过滤，故障现场（8 连 ERROR）应能搜到
        self.assertIn("connection pool exhausted", self.evidence)


class TestRelayPrompts(unittest.TestCase):
    def test_diag_prompt_carries_problem_and_evidence(self):
        p = build_diag_prompt("服务挂了", "证据A")
        self.assertIn("服务挂了", p)
        self.assertIn("证据A", p)

    def test_rootcause_only_gets_report(self):
        # 接力：根因官的输入只含诊断报告，不含原始证据等杂物
        p = build_rootcause_prompt("诊断报告X")
        self.assertIn("诊断报告X", p)

    def test_remedy_only_gets_analysis(self):
        p = build_remedy_prompt("根因Y")
        self.assertIn("根因Y", p)


class TestGuardRemedy(unittest.TestCase):
    def test_safe_text_passes(self):
        safe, warnings = guard_remedy("建议：查看慢查询日志，给高频 SQL 加索引")
        self.assertTrue(safe)
        self.assertEqual(warnings, [])

    def test_english_dangerous_word_caught(self):
        safe, warnings = guard_remedy("手动执行 rm -rf /data 需人工确认")
        self.assertFalse(safe)
        self.assertTrue(any("rm" in w for w in warnings))

    def test_chinese_dangerous_word_caught(self):
        # 模型写建议常用中文：重启 / 删除，token 黑名单拦不住，中文词兜底要接住
        safe, warnings = guard_remedy("建议重启 order-api 服务")
        self.assertFalse(safe)
        self.assertTrue(any("重启" in w for w in warnings))

    def test_empty_text_is_safe(self):
        safe, warnings = guard_remedy("")
        self.assertTrue(safe)
        self.assertEqual(warnings, [])

    def test_english_word_glued_by_cn_punctuation(self):
        # 模型写「重启、kill」——中文标点把 kill 和前词粘成一坨，
        # 只按空白拆会漏；中文标点也要当分隔符。
        safe, warnings = guard_remedy("涉及重启、kill 等操作需人工确认")
        self.assertFalse(safe)
        self.assertTrue(any("kill" in w for w in warnings))


class TestPipeline(unittest.TestCase):
    def test_runs_all_three_in_order(self):
        agents = make_agents(
            "现场报告甲", "根因乙", "建议丙（无破坏性词）"
        )
        result = run_pipeline(agents, "服务挂了", DATA_DIR)
        self.assertTrue(result["ok"])
        self.assertEqual(result["report"], "现场报告甲")
        self.assertEqual(result["analysis"], "根因乙")
        self.assertEqual(result["remedy"], "建议丙（无破坏性词）")
        # 三环各只跑一次
        self.assertEqual(agents["diag"].calls, 1)
        self.assertEqual(agents["root"].calls, 1)
        self.assertEqual(agents["remedy"].calls, 1)

    def test_each_agent_owns_its_memory(self):
        agents = make_agents("报告", "分析", "建议")
        run_pipeline(agents, "问题", DATA_DIR)
        # 每个 Agent 的记忆 = 1 句 user + 1 句 assistant，各管各的账，互不掺和
        for key in ("diag", "root", "remedy"):
            hist = agents[key].history()
            self.assertEqual(len(hist), 2)
            self.assertEqual(hist[0]["role"], "user")
            self.assertEqual(hist[1]["role"], "assistant")

    def test_relay_report_into_root(self):
        # 接力铁证：根因官的 user 输入 = 封装好的诊断报告，不是原始证据
        agents = make_agents("现场报告X", "根因", "建议")
        run_pipeline(agents, "问题", DATA_DIR)
        root_input = agents["root"].history()[0]["content"]
        self.assertEqual(root_input, build_rootcause_prompt("现场报告X"))

    def test_relay_analysis_into_remedy(self):
        agents = make_agents("报告", "根因Y", "建议")
        run_pipeline(agents, "问题", DATA_DIR)
        remedy_input = agents["remedy"].history()[0]["content"]
        self.assertEqual(remedy_input, build_remedy_prompt("根因Y"))

    def test_guard_warnings_reach_user(self):
        # 方案官建议里出现「重启」→ 护栏扫出警告，用户看到后再拍板
        agents = make_agents("报告", "根因", "建议重启 order-api，必要时 kill 兜底")
        result = run_pipeline(agents, "问题", DATA_DIR)
        self.assertTrue(result["ok"])
        self.assertFalse(result["guard_ok"])
        self.assertTrue(result["warnings"])
        self.assertTrue(any("重启" in w for w in result["warnings"]))

    def test_clean_remedy_no_warnings(self):
        agents = make_agents("报告", "根因", "建议：查看日志并加索引")
        result = run_pipeline(agents, "问题", DATA_DIR)
        self.assertTrue(result["ok"])
        self.assertTrue(result["guard_ok"])
        self.assertEqual(result["warnings"], [])

    def test_silent_diag_interrupts(self):
        agents = make_agents(None, "根因", "建议")
        result = run_pipeline(agents, "问题", DATA_DIR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "诊断")

    def test_silent_root_interrupts(self):
        agents = make_agents("报告", None, "建议")
        result = run_pipeline(agents, "问题", DATA_DIR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "根因")

    def test_silent_remedy_interrupts(self):
        agents = make_agents("报告", "根因", None)
        result = run_pipeline(agents, "问题", DATA_DIR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "方案")


if __name__ == "__main__":
    unittest.main()

# 多 Agent 专项测试：ops_debate.py 辩论/评审团模式（模式 C）
#
# 测什么：
#   build_summary_prompt   主席汇总包含所有专家答案；缺失的专家用占位符
#   run_debate             同一道题发给三个专家（各调一次）+ 主席一次；
#                          主席输入包含全部答案；各 Agent 记忆独立
#   优雅降级               专家挂 → 占位不崩；主席挂 → ok=False
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_loop import FakeModel, FakeResponse, text_block
from multi_agent import Agent
from ops_debate import (
    CHAIR_SYSTEM, EXPERT_SYSTEMS, EXPERT_LABELS,
    build_expert_prompt, build_summary_prompt, run_debate,
)


def make_agents(theory_txt, eng_txt, interviewer_txt, chair_txt):
    """主席 + 三个专家，各自演一句剧本。传 None = 一句话也说不出。"""
    def one(system, text):
        if text is None:
            return Agent("x", system, FakeModel([]))  # 空剧本 → ask 返回 None
        return Agent("x", system, FakeModel([FakeResponse("end_turn", [text_block(text)])]))
    return {
        "chair": one(CHAIR_SYSTEM, chair_txt),
        "theory": one(EXPERT_SYSTEMS["theory"], theory_txt),
        "eng": one(EXPERT_SYSTEMS["eng"], eng_txt),
        "interviewer": one(EXPERT_SYSTEMS["interviewer"], interviewer_txt),
    }


def build_experts(agents):
    return {"theory": agents["theory"], "eng": agents["eng"], "interviewer": agents["interviewer"]}


class TestBuildPrompts(unittest.TestCase):
    def test_expert_prompt_carries_question(self):
        p = build_expert_prompt("讲一下 RAG")
        self.assertIn("讲一下 RAG", p)

    def test_summary_contains_all_answers(self):
        p = build_summary_prompt("问题", {"theory": "T", "eng": "E", "interviewer": "I"})
        self.assertIn("T", p)
        self.assertIn("E", p)
        self.assertIn("I", p)
        self.assertIn("满分答案", p)

    def test_missing_expert_uses_placeholder(self):
        p = build_summary_prompt("问题", {"theory": "T"})
        self.assertIn("未发言", p)
        self.assertIn("T", p)


class TestRunDebate(unittest.TestCase):
    def test_same_question_to_all_three(self):
        agents = make_agents("原理A", "工程B", "面试C", "汇总D")
        result = run_debate(agents["chair"], build_experts(agents), "讲一下 RAG")
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], "汇总D")
        # 同一道题，三个专家各收到，且各只答一次
        self.assertEqual(agents["theory"].calls, 1)
        self.assertEqual(agents["eng"].calls, 1)
        self.assertEqual(agents["interviewer"].calls, 1)
        self.assertEqual(agents["chair"].calls, 1)

    def test_each_agent_owns_memory(self):
        agents = make_agents("A", "B", "C", "D")
        run_debate(agents["chair"], build_experts(agents), "问题")
        for key in ("chair", "theory", "eng", "interviewer"):
            self.assertEqual(len(agents[key].history()), 2)  # 1 user + 1 assistant

    def test_chair_input_contains_all_answers(self):
        agents = make_agents("原理A", "工程B", "面试C", "D")
        run_debate(agents["chair"], build_experts(agents), "问题")
        chair_input = agents["chair"].history()[0]["content"]
        self.assertIn("原理A", chair_input)
        self.assertIn("工程B", chair_input)
        self.assertIn("面试C", chair_input)

    def test_silent_expert_still_ok(self):
        # 专家挂 → 占位符顶替，主席照常汇总，不崩
        agents = make_agents("原理A", None, "面试C", "汇总D")
        result = run_debate(agents["chair"], build_experts(agents), "问题")
        self.assertTrue(result["ok"])
        self.assertIn("未发言", agents["chair"].history()[0]["content"])

    def test_silent_chair_not_ok(self):
        agents = make_agents("A", "B", "C", None)
        result = run_debate(agents["chair"], build_experts(agents), "问题")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()

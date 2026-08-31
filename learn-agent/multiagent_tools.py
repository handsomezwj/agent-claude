# multiagent_tools.py —— 多 Agent 协作工具的封装（给 agent-claude.py 当「手」用）
#
# 三个工具 = 三种协作模式的现成调用，一句自然语言就能触发：
#   troubleshoot    流水线（模式 B 接力）：诊断 → 根因 → 方案，安全护栏兜底
#   ops_report      主管-工人（模式 A 拆活）：主管拆三块小活分给工人，汇总成报告
#   interview_prep  评审团（模式 C 换角度）：同一道面试题三个专家各答，主席汇总满分答案
#
# model 是「门」：真模型（agent-claude.py 的 client）能装、FakeModel 也能装（测试零成本）。
# 每个工具内部会调 model 3~4 次（每环 / 每人各一次）——多 Agent 的成本就在这里，
# 好处是每段回答都更专注、上下文彼此隔离，不挤在一个脑子里。
#
# 每个工具都是「优雅降级」的：内部某个 Agent 挂了 → 返回带前缀的说明文本，绝不抛异常，
# 主循环拿到的是普通字符串，照常接话。
import os

from multi_agent import Agent
from ops_pipeline import (
    DIAG_SYSTEM, ROOTCAUSE_SYSTEM, REMEDY_SYSTEM,
    run_pipeline,
)
from ops_orchestrator import (
    ORCHESTRATOR_SYSTEM, WORKER_SYSTEMS, WORKER_LABELS,
    run_orchestrator,
)
from ops_debate import (
    CHAIR_SYSTEM, EXPERT_SYSTEMS, EXPERT_LABELS,
    run_debate,
)

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ops_demo")
DEFAULT_SERVICE = "order-api"

# 前缀：让主循环一眼看出这段是哪个多 Agent 模式产出的
TAG_PIPELINE = "[多Agent·流水线]"
TAG_ORCHESTRATOR = "[多Agent·主管-工人]"
TAG_DEBATE = "[多Agent·评审团]"


def make_pipeline_agents(model, model_name="fake"):
    """流水线三环：诊断官 → 根因官 → 方案官。返回 dict，传给 run_pipeline。"""
    return {
        "diag": Agent("诊断官", DIAG_SYSTEM, model, model_name),
        "root": Agent("根因官", ROOTCAUSE_SYSTEM, model, model_name),
        "remedy": Agent("方案官", REMEDY_SYSTEM, model, model_name),
    }


def make_orchestrator_agents(model, model_name="fake"):
    """主管 + 三个工人（状态 / 日志 / 风险）。返回 (boss, workers dict)。"""
    boss = Agent("主管", ORCHESTRATOR_SYSTEM, model, model_name)
    workers = {name: Agent(WORKER_LABELS[name], system, model, model_name)
               for name, system in WORKER_SYSTEMS.items()}
    return boss, workers


def make_debate_agents(model, model_name="fake"):
    """主席 + 三个专家（原理 / 工程 / 面试）。返回 (chair, experts dict)。"""
    chair = Agent("主席", CHAIR_SYSTEM, model, model_name)
    experts = {name: Agent(EXPERT_LABELS[name], system, model, model_name)
               for name, system in EXPERT_SYSTEMS.items()}
    return chair, experts


def troubleshoot(problem, model, model_name="fake",
                 service_name=DEFAULT_SERVICE, data_dir=DEFAULT_DATA_DIR):
    """流水线排障：诊断 → 根因 → 方案。返回一段长文本（喂回主循环）。"""
    try:
        agents = make_pipeline_agents(model, model_name)
        r = run_pipeline(agents, problem, data_dir, service_name)
        if not r["ok"]:
            return f"{TAG_PIPELINE} 中断（{r.get('stage')}）：{r.get('error')}"
        parts = [
            f"{TAG_PIPELINE} 问题：{problem}",
            "== 诊断（现场证据） ==", r["report"],
            "== 根因分析 ==", r["analysis"],
            "== 修复建议 ==", r["remedy"],
        ]
        if r["warnings"]:
            parts.append("⚠ 安全护栏：建议里出现破坏性操作，需人工确认："
                         + "、".join(r["warnings"]))
        return "\n\n".join(parts)
    except Exception as exc:
        return f"{TAG_PIPELINE} 执行失败：{exc}"


def ops_report(problem, model, model_name="fake",
               service_name=DEFAULT_SERVICE, data_dir=DEFAULT_DATA_DIR):
    """主管-工人：拆活分工，主管汇总成一份报告。返回文本。"""
    try:
        boss, workers = make_orchestrator_agents(model, model_name)
        r = run_orchestrator(boss, workers, problem, data_dir, service_name)
        if not r["ok"]:
            return f"{TAG_ORCHESTRATOR} 主管没说上话，报告出不来。"
        return f"{TAG_ORCHESTRATOR} 任务：{problem}\n\n" + r["report"]
    except Exception as exc:
        return f"{TAG_ORCHESTRATOR} 执行失败：{exc}"


def interview_prep(question, model, model_name="fake"):
    """评审团：同一道题三个专家各答，主席汇总满分答案。返回文本。"""
    try:
        chair, experts = make_debate_agents(model, model_name)
        r = run_debate(chair, experts, question)
        if not r["ok"]:
            return f"{TAG_DEBATE} 主席没说上话，汇总出不来。"
        return f"{TAG_DEBATE} 面试题：{question}\n\n" + r["summary"]
    except Exception as exc:
        return f"{TAG_DEBATE} 执行失败：{exc}"

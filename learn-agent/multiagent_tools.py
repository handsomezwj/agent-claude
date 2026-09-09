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
#
# 企业级加固（可选，agent-claude.py 用环境变量开关决定带不带）：
#   retries/timeout/breaker → reliability.py（可靠性层·第一步）：重试扛抖动、超时兜慢、熔断防雪崩
#   tracer               → observability.py（可观测性层·第二步）：每次 ask 记一段病历，
#                           谁、跑多久、成败如何。trace 是只读的账本，不掺和业务结果。
#   tier_models          → model_tiers.py（分级模型·第三步）：按角色→档位策略给每环发不同
#                           档位的模型（难环节用贵档、机械环降经济档），钱花在刀刃上
import contextlib
import os

from multi_agent import Agent
from reliability import HardenedAgent
from observability import TracedAgent
from model_tiers import resolve_role_models
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


def _harden_one(agent, retries=0, timeout=None, breaker=None):
    """给一个 Agent 包上企业级可靠性层；一项都没配就原样返回（不包 = 零开销零变化）。

    HardenedAgent 是透明门：协调器只认 .ask()/.history()，包了之后它拿到的还是
    这两个门，行为却多了 重试/超时/熔断（可靠性层的门哲学又一次兑现）。
    同一条链的 agent 共用同一个 breaker = 同一个下游，坏了一起挡（快速失败，
    不把雪崩传给用户）。retries/timeout/breaker 语义见 reliability.py。
    """
    if agent is None:
        return agent
    if retries <= 0 and timeout is None and breaker is None:
        return agent
    return HardenedAgent(agent, retries=retries, timeout=timeout, breaker=breaker)


def _trace_one(agent, tracer):
    """tracer 给了就给 Agent 套上记账门（TracedAgent）；没给 = 原样返回（零开销）。

    套的顺序有讲究：先硬化、后记账——TracedAgent(HardenedAgent(agent))。
    可靠性层先处理重试/超时/熔断，trace 记的是"最终成败"：
    抖动被重试救回来 → 记 ok；重试耗尽真挂了 → 记 error。病历反映真相。
    """
    if tracer is None or agent is None:
        return agent
    return TracedAgent(agent, tracer)


def _trace_top(tracer, label):
    """tracer 给了就开一个顶层病历段（这次协作的根）；没给 = 空段，照样跑。"""
    if tracer is not None:
        return tracer.trace(label)
    return contextlib.nullcontext()


def _pick_model_name(key, model_name, role_models):
    """查这个角色分到的 model 名；没分到（role_models 没配）就用统一的 model_name。

    分级模型（企业级加固 · 省钱路由）就在这一步落地：给每个角色发不同的模型名，
    Agent 在构造时把 model_name 定死，同一个 client 每次请求却能指定不同 model——
    协调器只认 ask() 两个门，谁用了哪档模型它一概不知（门哲学第三次兑现）。
    """
    if role_models is None:
        return model_name
    return role_models.get(key, model_name)


def make_pipeline_agents(model, model_name="fake", role_models=None):
    """流水线三环：诊断官 → 根因官 → 方案官。返回 dict，传给 run_pipeline。

    role_models  {diag/root/remedy: 模型名} —— 分级模型用的：每个角色分到
    不同档位的模型。None = 三个角色都用同一个 model_name（不分级，默认）。
    """
    return {
        "diag": Agent("诊断官", DIAG_SYSTEM, model,
                      _pick_model_name("diag", model_name, role_models)),
        "root": Agent("根因官", ROOTCAUSE_SYSTEM, model,
                      _pick_model_name("root", model_name, role_models)),
        "remedy": Agent("方案官", REMEDY_SYSTEM, model,
                        _pick_model_name("remedy", model_name, role_models)),
    }


def make_orchestrator_agents(model, model_name="fake", role_models=None):
    """主管 + 三个工人（状态 / 日志 / 风险）。返回 (boss, workers dict)。"""
    boss = Agent("主管", ORCHESTRATOR_SYSTEM, model,
                 _pick_model_name("boss", model_name, role_models))
    workers = {name: Agent(WORKER_LABELS[name], system, model,
                           _pick_model_name(name, model_name, role_models))
               for name, system in WORKER_SYSTEMS.items()}
    return boss, workers


def make_debate_agents(model, model_name="fake", role_models=None):
    """主席 + 三个专家（原理 / 工程 / 面试）。返回 (chair, experts dict)。"""
    chair = Agent("主席", CHAIR_SYSTEM, model,
                  _pick_model_name("chair", model_name, role_models))
    experts = {name: Agent(EXPERT_LABELS[name], system, model,
                           _pick_model_name(name, model_name, role_models))
               for name, system in EXPERT_SYSTEMS.items()}
    return chair, experts


def troubleshoot(problem, model, model_name="fake",
                 service_name=DEFAULT_SERVICE, data_dir=DEFAULT_DATA_DIR,
                 retries=0, timeout=None, breaker=None, tracer=None,
                 tier_models=None):
    """流水线排障：诊断 → 根因 → 方案。返回一段长文本（喂回主循环）。

    retries / timeout / breaker = 企业级加固（可靠性层）：给三环每个 Agent 包上
    重试 / 超时 / 熔断。tracer = 可观测性层：每次 ask 记一段病历（谁/多久/成败）。
    tier_models = 分级模型（省钱路由）：{档位: 模型名}，按策略表给每环发不同档位
    的模型（诊断/根因用贵档、方案官降经济档）。全没配 = 原样跑（默认）；
    agent-claude.py 配了开关就自动带上。
    """
    try:
        role_models = resolve_role_models("pipeline", model_name, tier_models)
        agents = {k: _harden_one(a, retries, timeout, breaker)
                  for k, a in make_pipeline_agents(model, model_name,
                                                   role_models).items()}
        with _trace_top(tracer, f"流水线排障：{problem[:20]}") as sp:
            traced = {k: _trace_one(a, tracer) for k, a in agents.items()}
            r = run_pipeline(traced, problem, data_dir, service_name)
        if tracer is not None:
            sp.status = "ok" if r["ok"] else "error"
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
               service_name=DEFAULT_SERVICE, data_dir=DEFAULT_DATA_DIR,
               retries=0, timeout=None, breaker=None, tracer=None,
               tier_models=None):
    """主管-工人：拆活分工，主管汇总成一份报告。返回文本。

    retries / timeout / breaker / tracer / tier_models = 企业级加固
    （可靠性层 + 可观测性层 + 分级模型），同 troubleshoot。
    """
    try:
        role_models = resolve_role_models("orchestrator", model_name, tier_models)
        boss, workers = make_orchestrator_agents(model, model_name, role_models)
        boss = _harden_one(boss, retries, timeout, breaker)
        workers = {k: _harden_one(a, retries, timeout, breaker)
                   for k, a in workers.items()}
        with _trace_top(tracer, f"主管-工人报告：{problem[:20]}") as sp:
            r = run_orchestrator(_trace_one(boss, tracer),
                                 {k: _trace_one(a, tracer)
                                  for k, a in workers.items()},
                                 problem, data_dir, service_name)
        if tracer is not None:
            sp.status = "ok" if r["ok"] else "error"
        if not r["ok"]:
            return f"{TAG_ORCHESTRATOR} 主管没说上话，报告出不来。"
        return f"{TAG_ORCHESTRATOR} 任务：{problem}\n\n" + r["report"]
    except Exception as exc:
        return f"{TAG_ORCHESTRATOR} 执行失败：{exc}"


def interview_prep(question, model, model_name="fake",
                   retries=0, timeout=None, breaker=None, tracer=None,
                   tier_models=None):
    """评审团：同一道题三个专家各答，主席汇总满分答案。返回文本。

    retries / timeout / breaker / tracer / tier_models = 企业级加固
    （可靠性层 + 可观测性层 + 分级模型），同 troubleshoot。
    """
    try:
        role_models = resolve_role_models("debate", model_name, tier_models)
        chair, experts = make_debate_agents(model, model_name, role_models)
        chair = _harden_one(chair, retries, timeout, breaker)
        experts = {k: _harden_one(a, retries, timeout, breaker)
                   for k, a in experts.items()}
        with _trace_top(tracer, f"评审团：{question[:20]}") as sp:
            r = run_debate(_trace_one(chair, tracer),
                           {k: _trace_one(a, tracer)
                            for k, a in experts.items()},
                           question)
        if tracer is not None:
            sp.status = "ok" if r["ok"] else "error"
        if not r["ok"]:
            return f"{TAG_DEBATE} 主席没说上话，汇总出不来。"
        return f"{TAG_DEBATE} 面试题：{question}\n\n" + r["summary"]
    except Exception as exc:
        return f"{TAG_DEBATE} 执行失败：{exc}"

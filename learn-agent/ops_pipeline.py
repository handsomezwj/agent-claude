# ops_pipeline.py — 运维排障流水线（多 Agent，模式 B：接力赛）
#
# 场景：用户报障 → 三个 Agent 一人一棒接力排查，每环只拿上一环的输出：
#   环1 诊断官：只读查服务状态 + 读日志 → 整理成「现场报告」（带行号证据）
#   环2 根因官：只看现场报告（不再读日志）→ 推断「根因分析」
#   环3 方案官：只看根因分析 → 出「修复建议」
#   兜底：流水线把方案官的输出用 itops_guard 的安全护栏扫一遍，
#         出现破坏性命令词就标「需人工确认」，绝不替用户做危险动作。
#
# 心法对照：
#   Agent      = 一个会说话的脑子（角色 + 自己的记忆 + ask 门，第 19 课）
#   流水线      = 只管"谁先谁后、传什么"，自己不动脑子（协调器思想）
#   接力 = 下一环的输入 = 上一环的输出，原始日志只在环1 手里
#   安全护栏    = 无论 Agent 说什么，系统最后再拦一遍（IT 运维专项的守护）

import re
from pathlib import Path

from itops_guard import (
    guard_command,
    read_log_safely,
    check_service_status,
    load_service_registry,
)
from multi_agent import Agent  # 复用第 19 课：一个 Agent = 角色 + 记忆 + ask() 门


# ---------------------- 三环人设（写进各自的大脑） ----------------------

DIAG_SYSTEM = (
    "你是运维诊断官。你的任务：把现场证据整理成清晰的排障现场报告。"
    "只做只读诊断：引用证据里的行号和事实，指出异常点，不臆测。"
    "禁止执行或建议任何破坏性操作（删除 / 杀进程 / 重启）。"
    "直接输出现场报告，不要开场白、客套话。"
)

ROOTCAUSE_SYSTEM = (
    "你是根因分析官。你只拿到上一环的现场报告，不再读任何日志。"
    "基于报告推断最可能的根因，给出证据支持（引用行号）。"
    "证据不足的假设要标明「暂不确定」，不硬编故事。"
    "直接输出根因分析，不要开场白。"
)

REMEDY_SYSTEM = (
    "你是修复方案官。基于根因分析给出修复建议。"
    "安全铁律：只给只读 / 低风险的排查动作；涉及删除、杀进程、重启、"
    "写文件的操作，一律标明「需要人工确认」，不直接执行。"
    "每条建议写清楚：做什么 / 为什么 / 怎么验证。"
    "直接输出修复建议，不要开场白。"
)


# ---------------------- 纯函数：收集现场证据（只读） ----------------------

def collect_evidence(base_dir, service_name="order-api", tail=40, keyword="ERROR"):
    """用只读纯函数把现场证据拉出来，拼成一份「证据包」文本。纯函数，可测。

    证据包 = 服务状态 + 日志尾部 N 行 + 日志里含关键词（默认 ERROR）的行。
    全程走 itops_guard 的只读护栏：路径越权、读目录外文件一律拒绝。
    """
    base = Path(base_dir)
    registry = load_service_registry(base)
    status = check_service_status(service_name, registry, base)
    tail_text = read_log_safely("app.log", base, tail_lines=tail)
    error_text = read_log_safely("app.log", base, keyword=keyword, tail_lines=20)
    return (
        f"【服务状态】\n{status}\n\n"
        f"【日志尾部 {tail} 行】\n{tail_text}\n\n"
        f"【日志中含「{keyword}」的行】\n{error_text}"
    )


# ---------------------- 纯函数：三环之间的接力 prompt ----------------------

def build_diag_prompt(problem, evidence):
    return f"用户反馈的问题：{problem}\n\n现场证据：\n{evidence}\n\n请输出排障现场报告。"


def build_rootcause_prompt(report):
    # 接力：只给现场报告，不给原始日志——根因官的世界里没有日志这回事
    return f"这是诊断官交来的现场报告，请基于它分析根因：\n【现场报告】\n{report}"


def build_remedy_prompt(analysis):
    return f"这是根因分析，请给出修复建议：\n【根因分析】\n{analysis}"


# ---------------------- 纯函数：护栏扫修复建议 ----------------------

# 中文破坏性操作词兜底：模型写建议常用中文，token 黑名单（英文命令）拦不住
# 中文「重启 / 删除」——单独扫一遍，宁可多拦，不让破坏性动作悄悄溜过去。
_CN_DANGEROUS = ("重启", "删除", "杀进程", "终止进程", "格式化", "关机")

# 拆词分隔符：空格 + 常见中英文标点。模型写建议常写「重启、kill」——中文标点
# 会把英文命令词和前一个词粘成一坨，若只按空白拆，「kill」就漏了。全拆开才不漏。
_TOKEN_SEP = re.compile(r"[\s，。、；：？！（）()「」【】\"'‘’“”,.;:]+")


def guard_remedy(text):
    """扫描方案官的输出里出现的破坏性命令词，命中 → 标记需人工确认。纯函数，可测。

    双保险：英文 token 走 itops_guard 黑名单（rm / kill / reboot…），
    中文破坏性词（重启 / 删除…）单独扫一遍。保守策略：哪怕上下文是
    "禁止 kill" 也算命中——系统级兜底不猜语义。
    返回 (是否安全, 警告列表)；安全 = 没扫出任何破坏性词。
    """
    if not text:
        return True, []
    warnings = []
    for token in _TOKEN_SEP.split(text):
        if not token:
            continue
        ok, why = guard_command(token)
        if not ok and why not in warnings:
            warnings.append(why)
    for word in _CN_DANGEROUS:
        if word in text:
            warnings.append(f"{word}（中文破坏性操作词）")
    return len(warnings) == 0, warnings


# ---------------------- 协调器：只管接力，不碰内容和质量 ----------------------

def run_pipeline(agents, problem, base_dir, service_name="order-api"):
    """三环接力跑一遍，返回结构化结果。agents = {diag, root, remedy} 三个 Agent。

    任何一环说不上话（返回 None）→ 流水线优雅中断，ok=False + stage 标出哪环挂了，
    绝不抛异常。护栏扫出破坏性词 → 挂到 warnings 里，让用户看到后再拍板。

    返回 dict：
      ok        流水线走完没（环没说上话 = 中断，不是 ok）
      stage     中断时是哪一环（诊断 / 根因 / 方案）
      error     中断原因
      evidence  证据包（排障起点，演示用）
      report    环1 输出 / analysis 环2 输出 / remedy 环3 输出
      warnings  护栏扫出的破坏性词清单；guard_ok 是否干净
    """
    evidence = collect_evidence(base_dir, service_name)

    report = agents["diag"].ask(build_diag_prompt(problem, evidence))
    if report is None:
        return {"ok": False, "stage": "诊断", "error": "诊断官没说话，流水线中断。",
                "evidence": evidence}

    analysis = agents["root"].ask(build_rootcause_prompt(report))
    if analysis is None:
        return {"ok": False, "stage": "根因", "report": report,
                "error": "根因官没说话，流水线中断。", "evidence": evidence}

    remedy = agents["remedy"].ask(build_remedy_prompt(analysis))
    if remedy is None:
        return {"ok": False, "stage": "方案", "report": report, "analysis": analysis,
                "error": "方案官没说话，拿不到修复建议。", "evidence": evidence}

    safe, warnings = guard_remedy(remedy)
    return {
        "ok": True,
        "evidence": evidence,
        "report": report,
        "analysis": analysis,
        "remedy": remedy,
        "warnings": warnings,
        "guard_ok": safe,
    }

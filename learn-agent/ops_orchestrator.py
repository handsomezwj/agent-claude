# ops_orchestrator.py — 多 Agent 主管-工人模式（模式 A）
#
# 场景：用户要一份「故障排查报告」。主管把大任务拆成几块独立小活，
# 分给三个工人（状态核查 / 日志分析 / 风险审视），工人各干各的、互不依赖，
# 主管收齐后汇总成一份完整报告。用户全程只跟主管说话（一个口子）。
#
# 和流水线（模式 B）的区别：
#   流水线   = 接力赛：A 干完 B 才干，后环依赖前环，必须按顺序。
#   主管-工人 = 项目经理带小组：工人之间互不依赖（可并行），主管负责拆活 + 收尾。
#
# 心法：主管负责"拆"和"拼"，工人负责"干"；各工人上下文独立，互不污染。
# 复用：证据包 collect_evidence 来自 ops_pipeline（只读护栏：状态+日志+ERROR 行）。

from pathlib import Path

from ops_pipeline import collect_evidence


ORCHESTRATOR_SYSTEM = (
    "你是任务主管。收到用户请求后，把大任务拆成几块独立小活分给工人，"
    "收齐后汇总成一份完整报告，给出总体结论。"
    "安全铁律：汇总里凡涉及删除、杀进程、重启等破坏性操作，一律标明『需人工确认』。"
    "直接输出最终报告，不要开场白。"
)

WORKER_SYSTEMS = {
    "status": "你是状态核查员。基于证据，报告服务当前状态，说清依据（pid 文件在不在）。",
    "log": "你是日志分析员。基于证据，列出异常日志关键点，引用行号作证据。",
    "risk": "你是风险审视员。基于证据，从安全 / 配置角度指出风险点。"
            "只做评估，不给破坏性建议；涉及危险操作只能写『需人工确认』。",
}

WORKER_LABELS = {
    "status": "状态核查员",
    "log": "日志分析员",
    "risk": "风险审视员",
}


def build_tasks(evidence):
    """主管把证据包拆成三个独立子任务（纯函数，可测）。

    每个工人拿到「自己的子任务 + 同一份证据」——工人之间互不依赖、可并行，
    但上下文各自独立（人设不同、记忆各管各的，谁也看不见谁的账本）。
    """
    return {
        "status": f"子任务·状态核查：基于下面证据，报告 order-api 当前服务状态。\n【证据】\n{evidence}",
        "log": f"子任务·日志分析：基于下面证据，列出异常日志关键点（带行号）。\n【证据】\n{evidence}",
        "risk": f"子任务·风险审视：基于下面证据，从安全 / 配置角度指出风险点，不给破坏性建议。\n【证据】\n{evidence}",
    }


def build_summary_prompt(problem, results):
    """主管把三个工人的输出拼起来，生成最终报告（纯函数，可测）。

    某工人没交结果 → 用占位符顶替，主管照常汇总（优雅降级，不崩）。
    """
    parts = []
    for key in WORKER_LABELS:
        txt = results.get(key)
        if not txt:
            txt = "（该工人未交结果）"
        parts.append(f"【{WORKER_LABELS[key]}】\n{txt}")
    return f"""用户请求：{problem}
三位工人已交来结果，请汇总成一份完整的《排查报告》，并给出总体结论。

{chr(10).join(parts)}

输出格式：
# 排查报告
## 总体结论
## 详情
## 风险与建议（破坏性操作标明『需人工确认』）"""


def run_orchestrator(boss, workers, problem, base_dir, service_name="order-api"):
    """主管-工人跑一遍。workers = {'status','log','risk'} 三个 Agent，boss 是主管 Agent。

    流程：收用户请求 → 拆任务 → 分给工人 → 收齐 → 主管汇总 → 交回。
    某工人说不上话 → 汇总里占位，主管照常汇总；主管也说不上话 → ok=False。
    """
    evidence = collect_evidence(base_dir, service_name)
    tasks = build_tasks(evidence)

    results = {}
    for key, worker in workers.items():
        results[key] = worker.ask(tasks[key])

    report = boss.ask(build_summary_prompt(problem, results))
    return {
        "ok": report is not None,
        "evidence": evidence,
        "worker_results": results,
        "report": report,
    }

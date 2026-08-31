# 多 Agent 专项演示：主管-工人模式（模式 A）
#
# 用户一句话要「故障排查报告」，主管拆成三块独立小活分给三个工人，
# 工人各干各的（独立上下文），主管收齐汇总成一份完整报告。
# 用户全程只跟主管说话（一个口子）。
#
# 带 --fake 用假剧本离线跑（一分钱不花）；不带参数连真 API。
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
from agent_loop import FakeModel, FakeResponse, text_block
from multi_agent import Agent
from ops_orchestrator import (
    ORCHESTRATOR_SYSTEM, WORKER_SYSTEMS, WORKER_LABELS,
    run_orchestrator,
)

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

DATA_DIR = Path(__file__).resolve().parent / "ops_demo"
PROBLEM = "帮我出一份 order-api 的故障排查报告"


def make_fake_agents():
    """一个主管 + 三个工人，剧本各演一句。工人之间互不依赖。"""
    def one(system, text):
        return Agent("worker", system, FakeModel([FakeResponse("end_turn", [text_block(text)])]))
    workers = {
        "status": one(WORKER_SYSTEMS["status"],
            "状态核查：order-api 当前【停止】——pid 文件不存在（服务没在跑）。"),
        "log": one(WORKER_SYSTEMS["log"],
            "日志分析：10:04:41 WARN（池 9/10 忙，checkout 980ms），"
            "10:05:01~10:05:24 连续 8 次 ERROR（第 8~15 行），10:05:30 CRITICAL 终止（第 16 行）。"),
        "risk": one(WORKER_SYSTEMS["risk"],
            "风险审视：连接池上限 10 偏低、慢查询缺索引；"
            "建议排查长事务/连接泄漏，重启需人工确认。"),
    }
    boss = Agent("boss", ORCHESTRATOR_SYSTEM, FakeModel([FakeResponse("end_turn", [text_block(
        "# 排查报告\n## 总体结论\norder-api 因数据库连接池耗尽（8 连 ERROR）触发保护性终止，当前已停止。\n"
        "## 详情\n- 状态：停止（pid 文件不存在）\n- 日志：10:04:41 池 9/10 忙，10:05:01 起 8 连池耗尽，10:05:30 CRITICAL 终止\n"
        "## 风险与建议\n- 调大连接池上限并加慢查询索引；重启需人工确认。"
    )])]))
    return boss, workers


def make_real_agents():
    import anthropic
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    workers = {name: Agent(WORKER_LABELS[name], system, client, model)
               for name, system in WORKER_SYSTEMS.items()}
    boss = Agent("主管", ORCHESTRATOR_SYSTEM, client, model)
    return boss, workers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true", help="离线用假剧本，不花钱")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="演示数据目录（默认 ops_demo/）")
    args = parser.parse_args()

    boss, workers = make_fake_agents() if args.fake else make_real_agents()
    print(f"用户 → 主管：{PROBLEM}\n")

    result = run_orchestrator(boss, workers, PROBLEM, args.data_dir)
    if not result["ok"]:
        print("⛔ 主管没说上话，报告出不来。")
        return

    print("【三个工人各干各的（你 👀 看不到，主管内部调度）】")
    for key in WORKER_LABELS:
        print(f"  - {WORKER_LABELS[key]}：{result['worker_results'][key]}")
    print("\n【主管汇总 → 交给你】")
    print(result["report"])
    print('\n  一句话收尾：主管拆活、工人干活、用户只跟主管说话——这就是「一个口子」。')


if __name__ == "__main__":
    main()

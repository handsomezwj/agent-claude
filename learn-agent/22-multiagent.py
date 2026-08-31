# 多 Agent 专项演示：运维排障流水线——三个 Agent 一人一棒接力排查
#
# 模式 B（接力赛）：
#   用户提问 → [环1] 诊断官(只读查状态+日志→现场报告)
#           → [环2] 根因官(只看报告→根因分析)
#           → [环3] 方案官(只看分析→修复建议)
#           → 流水线用安全护栏扫方案官输出 → 破坏性词标「需人工确认」→ 交给你
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
from ops_pipeline import (
    DIAG_SYSTEM, ROOTCAUSE_SYSTEM, REMEDY_SYSTEM,
    run_pipeline,
)

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

DATA_DIR = Path(__file__).resolve().parent / "ops_demo"
PROBLEM = "order-api 好像挂了，帮我排查一下为什么"


def make_fake_agents():
    """三环各一个假模型，剧本各演一句——输出会顺着接力自然传下去。"""
    diag_model = FakeModel([FakeResponse("end_turn", [text_block(
        "现场报告：order-api 状态【停止】（pid 文件不存在）。日志 08-24 10:04:41 起连接池紧张，"
        "10:05:01~10:05:24 连续 8 次连接池耗尽（第 8~15 行 ERROR），10:05:30 CRITICAL 终止（第 16 行），"
        "随后停止（第 17 行）。异常点：连接池上限 10 被打满且持续约 1 分钟。"
    )])])
    root_model = FakeModel([FakeResponse("end_turn", [text_block(
        "根因：数据库连接池（上限 10）被打满且连接不归还，8 次 checkout 连续失败触发保护性终止。"
        "最可能是慢查询 / 长事务占住连接，证据：10:04:41 checkout 已变慢 980ms（第 7 行 WARN）。"
        "次要怀疑：连接泄漏。"
    )])])
    remedy_model = FakeModel([FakeResponse("end_turn", [text_block(
        "修复建议：1) 临时：由运维手动拉起服务，重启需人工确认；"
        "2) 短期：排查慢查询 / 长事务，给高频 SQL 加索引；"
        "3) 验证：观察日志池占用回落、请求恢复 200。涉及重启、kill 等操作一律需人工确认，不自动执行。"
    )])])
    return {
        "diag": Agent("诊断官", DIAG_SYSTEM, diag_model),
        "root": Agent("根因官", ROOTCAUSE_SYSTEM, root_model),
        "remedy": Agent("方案官", REMEDY_SYSTEM, remedy_model),
    }


def make_real_agents():
    import anthropic
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    return {
        "diag": Agent("诊断官", DIAG_SYSTEM, client, model),
        "root": Agent("根因官", ROOTCAUSE_SYSTEM, client, model),
        "remedy": Agent("方案官", REMEDY_SYSTEM, client, model),
    }


def show(result):
    print(f"\n① 证据包（{len(result['evidence'])} 字）")
    print("② 诊断官 → 现场报告：")
    print(result["report"])
    print("\n③ 根因官 → 根因分析：")
    print(result["analysis"])
    print("\n④ 方案官 → 修复建议：")
    print(result["remedy"])
    if result.get("warnings"):
        print(f"\n🛡 安全护栏扫描：建议里出现破坏性词 {result['warnings']}")
        print("   → 这些动作一律需人工确认，不自动执行！")
    else:
        print("\n🛡 安全护栏扫描：干净，无破坏性操作。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true", help="离线用假剧本，不花钱")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="演示数据目录（默认 ops_demo/）")
    args = parser.parse_args()

    agents = make_fake_agents() if args.fake else make_real_agents()
    print(f"用户提问：{PROBLEM}\n")
    result = run_pipeline(agents, PROBLEM, args.data_dir)
    if not result["ok"]:
        print(f"⛔ 流水线中断（{result.get('stage')}）：{result.get('error')}")
        return
    show(result)
    print("\n  一句话收尾：多 Agent 接力 = 每环只看上一层，安全护栏 = 最后一道闸，谁也别想越权。")


if __name__ == "__main__":
    main()

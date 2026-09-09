# 25-enterprise.py —— 企业级加固 · 可靠性层演示（重试 / 超时 / 熔断）
#
# 跑法：
#   python 25-enterprise.py --fake   离线五幕（推荐，零成本）
#   python 25-enterprise.py          连真 API，演示硬化层对真模型透明生效
#
# 五幕：
#   幕1 重试   下游前 2 次限流 → 指数退避后第 3 次成功（不再一挂就认）
#   幕2 超时   下游睡 2 秒 → timeout=0.5 快速失败，不傻等卡死整条链
#   幕3 熔断   连败 3 次 → 保险丝跳闸（快速失败）→ 冷却 → HALF_OPEN 试探恢复
#   幕4 组合   HardenedAgent 包在流水线「诊断官」上：同样的故障，重试+熔断后
#              整条流水线照样跑完——协调器完全无感（门哲学兑现）
#   幕5 对照   同样会挂的诊断官，没硬化：一次故障，整条流水线中断
#
# 心法：真实世界里下游会挂。重试扛瞬时抖动、超时防傻等、熔断防雪崩。
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_loop import FakeModel, FakeResponse, text_block
from multi_agent import Agent
from ops_pipeline import (
    DIAG_SYSTEM, ROOTCAUSE_SYSTEM, REMEDY_SYSTEM,
    run_pipeline, collect_evidence,
)
from reliability import (
    retry_with_backoff, with_timeout, CircuitBreaker, HardenedAgent,
)

# 数据目录复用 IT 运维的假现场（服务注册表 + 故障日志）
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ops_demo")
PROBLEM = "order-api 好像挂了，帮我排查一下"


# ---------------------- 一个"会挂的下游"（模拟真实世界的故障） ----------------------

class FlakyAgent:
    """前 fail_times 次 ask 都说不上话（返回 None，模拟 Agent 挂掉），之后恢复。

    为什么用 None 而不是抛异常：multi_agent.Agent 的优雅降级就是"挂了返回 None"，
    协调器看到 None 判定"这环没说话"。所以用 None 模拟最真实。
    """

    def __init__(self, role, fail_times, answer):
        self.role = role
        self.fail_times = fail_times
        self.answer = answer
        self.calls = 0

    def ask(self, text):
        self.calls += 1
        if self.calls <= self.fail_times:
            return None          # 模拟：这环挂了（网络抖动 / 模型超时 / 限流）
        return self.answer

    def history(self):
        return []


# ---------------------- 幕1：重试（指数退避） ----------------------

def act_retry():
    print("=" * 60)
    print("幕1 · 重试：下游前 2 次限流，第 3 次成功")
    print("-" * 60)
    count = {"n": 0}
    waits = []

    def flaky_downstream():
        count["n"] += 1
        if count["n"] < 3:
            raise RuntimeError("下游 429 限流，请稍后重试")
        return f"第 {count['n']} 次调用成功了"

    def fake_sleep(seconds):
        waits.append(round(seconds, 3))
        # 不真等，只记录——离线演示要的就是快

    result = retry_with_backoff(flaky_downstream, retries=3, base_delay=0.01,
                                sleep=fake_sleep)
    print(f"调用次数：{count['n']}（第 1、2 次失败，第 3 次成功）")
    print(f"等待序列（指数退避，秒）：{waits}  ← 越等越久，别连着撞墙")
    print(f"最终结果：{result!r}")


# ---------------------- 幕2：超时 ----------------------

def act_timeout():
    print()
    print("=" * 60)
    print("幕2 · 超时：下游睡 2 秒，timeout=0.5 快速失败")
    print("-" * 60)

    def slow_downstream():
        time.sleep(2.0)          # 模拟：模型一直不吐字 / 网络黑洞
        return "迟到的回答"

    start = time.monotonic()
    result = with_timeout(slow_downstream, timeout=0.5)
    elapsed = round(time.monotonic() - start, 2)
    print(f"只等了 {elapsed} 秒就放弃（而不是傻等 2 秒）")
    print(f"结果：{result!r}（超时 → None，优雅降级，不卡死整条链）")


# ---------------------- 幕3：熔断 ----------------------

def act_breaker():
    print()
    print("=" * 60)
    print("幕3 · 熔断：连败 3 次跳闸 → 快速失败 → 冷却后试探恢复")
    print("-" * 60)
    breaker = CircuitBreaker(fail_threshold=3, recovery_time=0.2)
    # 前 3 次失败触发跳闸；第 4 次用于 HALF_OPEN 试探（此时下游已恢复 → 成功）
    downstream = FlakyAgent("下游服务", fail_times=3, answer="我恢复了")

    events = []
    for i in range(1, 8):
        before = breaker.state
        r = breaker.ask(lambda: downstream.ask("ping"))
        after = breaker.state
        flag = "（快速失败，没真调）" if (before == "OPEN" and r is None) else ""
        events.append(f"第{i}次: 调用前状态={before} → 结果={r!r}{flag} → 调用后状态={after}")
        if i == 4:
            print("  …… 冷却 0.2 秒，让保险丝能重新试探 ……")
            time.sleep(0.25)
    print("调用前状态 记录：")
    for e in events:
        print(f"  {e}")
    print("结论：跳闸后不再打坏下游；冷却一到只放一个试探，成功了就全线恢复。")


# ---------------------- 幕4：组合（硬化诊断官，流水线照样跑完） ----------------------

def act_hardened(data_dir):
    print()
    print("=" * 60)
    print("幕4 · 组合：HardenedAgent 包住会挂的诊断官，流水线照样跑完")
    print("-" * 60)
    # 剧本：诊断官（root/remedy）正常作答；诊断官本身前 2 次挂
    diag = FlakyAgent("诊断官", fail_times=2, answer="现场报告：order-api 连接池耗尽")
    root = Agent("根因官", ROOTCAUSE_SYSTEM, FakeModel([
        FakeResponse("end_turn", [text_block("根因：连接池耗尽导致拒绝服务")]),
    ]))
    remedy = Agent("方案官", REMEDY_SYSTEM, FakeModel([
        FakeResponse("end_turn", [text_block("建议：扩容连接池并重启，需人工确认")]),
    ]))

    # 关键：把会挂的诊断官包进 HardenedAgent，协调器无感
    hardened = HardenedAgent(
        diag,
        retries=3,          # 前 2 次挂 → 重试 2 次后第 3 次成功
        timeout=1.0,        # 单次调用超时兜底
        breaker=CircuitBreaker(fail_threshold=3, recovery_time=0.1),
    )
    agents = {"diag": hardened, "root": root, "remedy": remedy}
    r = run_pipeline(agents, PROBLEM, data_dir)
    print(f"诊断官实际被调 {diag.calls} 次（前 2 次挂，重试扛住了）")
    print(f"流水线走完：ok={r['ok']}（没中断！协调器只看到 ask/history 两个门）")
    print(f"最终修复建议：{r['remedy'][:50]}…")


# ---------------------- 幕5：对照（没硬化 = 一挂就断） ----------------------

def act_control(data_dir):
    print()
    print("=" * 60)
    print("幕5 · 对照：同样会挂的诊断官，不硬化 → 一次故障整条链断")
    print("-" * 60)
    diag = FlakyAgent("诊断官", fail_times=2, answer="现场报告：一切正常")
    root = Agent("根因官", ROOTCAUSE_SYSTEM, FakeModel([
        FakeResponse("end_turn", [text_block("根因分析")]),
    ]))
    remedy = Agent("方案官", REMEDY_SYSTEM, FakeModel([
        FakeResponse("end_turn", [text_block("修复建议")]),
    ]))
    r = run_pipeline({"diag": diag, "root": root, "remedy": remedy}, PROBLEM, data_dir)
    print(f"诊断官被调 {diag.calls} 次（第 1 次就挂，没有重试直接中断）")
    print(f"流水线结果：ok={r['ok']}，stage={r.get('stage')}，error={r.get('error')}")
    print("同一套故障，幕4 扛过去了，幕5 断在起跑线——这就是可靠层的价值。")


# ---------------------- 真 API 分支：硬化层对真模型透明生效 ----------------------

def act_real(data_dir):
    print()
    print("=" * 60)
    print("真 API 演示：把真模型 Agent 包进 HardenedAgent，流水线跑一遍")
    print("-" * 60)
    try:
        import anthropic
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), ".env"))
        client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        )
        model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    except Exception as exc:
        print(f"连不上真 API（{exc}）。用 --fake 跑离线五幕。")
        return

    agents = {
        "diag": HardenedAgent(
            Agent("诊断官", DIAG_SYSTEM, client, model),
            retries=2, timeout=30, breaker=CircuitBreaker(fail_threshold=3),
        ),
        "root": Agent("根因官", ROOTCAUSE_SYSTEM, client, model),
        "remedy": Agent("方案官", REMEDY_SYSTEM, client, model),
    }
    r = run_pipeline(agents, PROBLEM, data_dir)
    if r["ok"]:
        print("流水线 ok。硬化层在真实环境下透明生效（重试/超时/熔断都在暗处守着）。")
        print(f"根因：{r['analysis'][:80]}…")
        print(f"建议：{r['remedy'][:80]}…")
    else:
        print(f"中断于 {r.get('stage')}：{r.get('error')}")


# ---------------------- 入口 ----------------------

def main():
    parser = argparse.ArgumentParser(description="企业级加固 · 可靠性层演示")
    parser.add_argument("--fake", action="store_true", help="离线五幕（推荐）")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                        help="ops_demo 数据目录")
    args = parser.parse_args()

    if args.fake:
        act_retry()
        act_timeout()
        act_breaker()
        act_hardened(args.data_dir)
        act_control(args.data_dir)
        print()
        print("=" * 60)
        print("五幕演完。一句话总结：")
        print("  重试 = 掉水里爬起来再跳，超时 = 没人应就挂电话，熔断 = 跳闸别烧楼。")
        print("  组合起来，同一个会挂的下游，从「一挂就断」变成「扛过去照样跑完」。")
    else:
        act_real(args.data_dir)


if __name__ == "__main__":
    main()

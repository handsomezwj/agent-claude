# 26-trace.py —— 企业级加固 · 可观测性层演示（trace：多 Agent 的病历本）
#
# 跑法：
#   python 26-trace.py --fake   离线五幕（推荐，零成本）
#   python 26-trace.py          连真 API，演示 trace 对真模型透明生效
#
# 问题：多 Agent 一次调 3~4 次模型，哪一环慢 / 哪一环挂 / 被重试救没救回来，
#       用户只看到一句"中断"。黑盒里的运行过程，全靠猜。
#
# 答案：可观测性。日志是流水账、指标是计数器，trace 是"一条请求从进来到出去，
#       每一段花在哪"——像医院病历：谁、什么时候、跑了多久、成败如何，一笔一笔记。
#
# 五幕：
#   幕1 病历长啥样   手动围三步（嵌套），看缩进病历 + 一行速览 + JSON 导出
#   幕2 接上流水线   troubleshoot 跑一趟，病历自动记出诊断官/根因官/方案官
#   幕3 重试救回     诊断官前 2 次抽风 + retries=2 → 病历记 ok（真相：救回来了）
#   幕4 重试耗尽     一直抽风 + 熔断 → 病历秒定位是哪个环挂、熔断挡了几发
#   幕5 存档回放     病历导出成 JSON，模拟重启后用 format_text 复盘——病历还在
#
# 心法：观测是只读的账本，不掺和业务。trace 只记录、不拦事、不污染返回文本。
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_loop import FakeModel, FakeResponse, text_block
from observability import Tracer, TracedAgent, format_text
import multiagent_tools as mt

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ops_demo")
PROBLEM = "order-api 好像挂了，帮我排查一下"


def script(*texts):
    """按调用顺序排的剧本：每个文本 = 一次 ask 的回答（给多 Agent 工具用）。"""
    return FakeModel([FakeResponse("end_turn", [text_block(t)]) for t in texts])


# ---------------------- 一个"会抽风的下游"（模拟真实世界的网络抖动） ----------------------

class FlakyModel:
    """前 fail_first 次调用抛网络错误（模拟下游暂时不可用），之后交给内层 FakeModel。

    跟可靠性层（幕3/幕4）搭配：重试能不能救回来、熔断挡了几发，trace 全记下来。
    """

    def __init__(self, inner_model, fail_first=0, always_fail=False):
        self._inner = inner_model
        self.fail_first = fail_first
        self.always_fail = always_fail
        self.failed = 0
        self.calls = 0

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.calls += 1
        if self.always_fail or self.failed < self.fail_first:
            self.failed += 1
            raise ConnectionError("下游暂时不可用（模拟网络抖动）")
        return self._inner.create(**kwargs)


# ---------------------- 假时钟（幕1：让"耗时"可控，不等真时间） ----------------------

class FakeClock:
    """假装自己是 time.monotonic；advance() 拨一下时间，测试/演示里精确控制耗时。"""

    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


# ---------------------- 幕1：病历长啥样 ----------------------

def act_basic():
    print("=" * 60)
    print("幕1 · 病历长啥样：手动围三步（诊断 → 根因 → 方案）")
    print("-" * 60)
    clock = FakeClock()                     # 注入假时钟 → 耗时可控
    tr = Tracer(clock=clock)
    with tr.trace("整次排障") as top:       # 顶层 = 这次任务
        with tr.trace("诊断官") as sp:
            clock.advance(0.40)
            sp.note = "拿到现场报告"        # ok 段：手动补一句人话
        with tr.trace("根因官") as sp:
            clock.advance(1.20)
            sp.status = "error"             # 挂段：标 error + 写为什么
            sp.note = "模型超时，没说出根因"
        with tr.trace("方案官") as sp:
            clock.advance(0.30)             # 这环正常，什么都不用标
    print("病历（缩进 = 嵌套，谁包着谁一目了然）：")
    print(tr.as_text())
    print()
    print("一行速览（只看最细的叶子动作）：")
    print("  " + tr.summary())
    print()
    print("导出成 JSON（能存文件，长这样）：")
    print("  " + json.dumps(tr.export(), ensure_ascii=False))


# ---------------------- 幕2：接上流水线（trace 自动记账） ----------------------

def act_pipeline():
    print()
    print("=" * 60)
    print("幕2 · 接上流水线：troubleshoot 跑一趟，trace 自动记出三环病历")
    print("-" * 60)
    tr = Tracer()
    # 只要传 tracer=tr，工具内部每次 ask 自动记一段——工具/协调器一行没改
    out = mt.troubleshoot(PROBLEM, script("现场报告：连接池耗尽",
                                          "根因：连接池耗尽导致拒绝服务",
                                          "建议：扩容连接池，需人工确认"),
                          tracer=tr)
    print("返回给用户的文本（干净答案，不含病历）：")
    print("  " + out.splitlines()[0] + "  …")
    print()
    print("终端运维看到的病历（多 Agent 调了 4 次模型，每段都留痕）：")
    print(tr.as_text())
    print("一行速览：" + tr.summary())


# ---------------------- 幕3：重试救回 → 病历记 ok ----------------------

def act_saved(data_dir):
    print()
    print("=" * 60)
    print("幕3 · 重试救回：诊断官前 2 次抽风，retries=2 救回来")
    print("-" * 60)
    flaky = FlakyModel(script("现场报告：连接池耗尽",
                              "根因：连接池耗尽",
                              "建议：扩容并重启，需人工确认"),
                       fail_first=2)
    tr = Tracer()
    out = mt.troubleshoot(PROBLEM, flaky, retries=2, data_dir=data_dir, tracer=tr)
    # 调用账：诊断官那环 前2次抽风→重试到第3次成功(3次)；根因官/方案官各1次 = 共5次
    print(f"整趟共真实调用模型 {flaky.calls} 次（诊断官那环 3 次：前 2 次抽风，"
          f"重试扛到第 3 次成功；后两环各 1 次）")
    print("病历（诊断官记 ok——trace 只记最终成败，重试的过程在硬化层内部，不吵你）：")
    print(tr.as_text())
    print("没开 trace 之前，这一趟过程黑盒——你只看到结果文本，猜不到它「救」过自己。")


# ---------------------- 幕4：重试耗尽 + 熔断 → 病历秒定位 ----------------------

def act_dead(data_dir):
    print()
    print("=" * 60)
    print("幕4 · 重试耗尽 + 熔断：下游一直坏，病历一眼定位雪崩点")
    print("-" * 60)
    # 为什么用 ops_report（主管-工人）而不是流水线？流水线第一环挂就停，
    # 熔断没机会跳闸。主管-工人会按顺序问完所有工人 → 熔断的"连败跳闸"才现形。
    from reliability import CircuitBreaker
    flaky = FlakyModel(script("状态S", "日志L", "风险R", "总报告"),
                       always_fail=True)
    breaker = CircuitBreaker(fail_threshold=2, recovery_time=1e9)
    tr = Tracer()
    mt.ops_report("出一份排查报告", flaky, retries=2, breaker=breaker,
                  data_dir=data_dir, tracer=tr)
    # 调用账：状态核查员 3 次(1+2重试)→连败1；日志分析员 3 次→连败2跳闸；
    #          风险审视员/主管 被熔断快速失败 0 次 = 共 6 次。
    saved = 4 * 3 - flaky.calls          # 4 环各最多试 3 次 = 12；熔断只放出去 6
    print(f"4 环每人最多试 3 次，不熔断会打 {4 * 3} 发；"
          f"熔断只放出去 {flaky.calls} 发（连败 2 环后跳闸），挡下 {saved} 发")
    print(f"熔断器状态：{breaker.state}（保险丝跳闸，后两环根本没碰模型）")
    print("病历（注意后两环只花 ~0ms——那是熔断在快速失败，不是它们真跑了）：")
    print(tr.as_text())
    print("一行速览：" + tr.summary())
    print("（答案断了不可怕——可怕的是断在哪、为什么断，你不知道。现在病历说得清清楚楚。）")


# ---------------------- 幕5：存档回放 ----------------------

def act_replay():
    print()
    print("=" * 60)
    print("幕5 · 存档回放：病历导出存盘，模拟重启后 format_text 复盘")
    print("-" * 60)
    tr = Tracer()
    mt.ops_report("出一份排查报告", script("状态S", "日志L", "风险R", "主管总报告"),
                  tracer=tr)
    archive = json.dumps(tr.export(), ensure_ascii=False)   # 一行 = 一次运行存档
    print(f"存档（一行 JSON，{len(archive)} 字符）…… 模拟进程重启 ……")
    restored = format_text(json.loads(archive))             # 从存档回放成病历
    print("重启后回放，病历还在：")
    print(restored)


# ---------------------- 真 API 分支：trace 对真模型透明生效 ----------------------

def act_real(data_dir):
    print()
    print("=" * 60)
    print("真 API 演示：真模型跑 troubleshoot，trace 记录每一次真实模型调用")
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
    tr = Tracer()
    out = mt.troubleshoot(PROBLEM, client, model, retries=2, data_dir=data_dir,
                          tracer=tr)
    print(out[:400])
    print()
    print("病历（每一环真实调了模型多久、成败如何）：")
    print(tr.as_text())


# ---------------------- 入口 ----------------------

def main():
    parser = argparse.ArgumentParser(description="企业级加固 · 可观测性层演示")
    parser.add_argument("--fake", action="store_true", help="离线五幕（推荐）")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                        help="ops_demo 数据目录")
    args = parser.parse_args()

    if args.fake:
        act_basic()
        act_pipeline()
        act_saved(args.data_dir)
        act_dead(args.data_dir)
        act_replay()
        print()
        print("=" * 60)
        print("五幕演完。一句话总结：")
        print("  多 Agent 是黑盒？给每次协作配一本病历（trace），")
        print("  哪环慢/哪环挂/被重试救没救回来，一查便知。观测只记录，不掺和。")
    else:
        act_real(args.data_dir)


if __name__ == "__main__":
    main()

# 27-model-tiers.py —— 企业级加固 · 分级模型演示（省钱路由）
#
# 跑法：
#   python 27-model-tiers.py --fake   离线演示（推荐，零成本）
#   python 27-model-tiers.py          连真 API，演示按档位发不同模型名
#
# 五幕：
#   幕1 策略   三种协作模式里每个角色配哪档，为什么（判断依据：思考深度 + 有没有护栏兜底）
#   幕2 生效   同一个流水线，不配 tier vs 配了 tier：诊断官/根因官发旗舰模型名、
#              方案官发经济模型名——协调器无感，只在"发哪个模型"上不同
#   幕3 省钱   同样 3 环产出，无脑全用旗舰 vs 分级路由：账单差多少（成本 ∝ 输出字符 × 档位单价）
#   幕4 组合   分级 + 可靠性（重试）+ 可观测性（trace）三层叠一起，还是一场调用全兼容
#   幕5 对照   评审团为什么省得少（专家一个都不能降）→ 省钱要打在"有机器的活"上
#
# 心法：不是每次调用都值得顶配。客厅 100W、走廊 5W——亮度刚好的地方不浪费电。
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_loop import FakeModel, FakeResponse, text_block
from model_tiers import (
    TIERS, role_tier_map, resolve_role_models,
    estimate_cost, savings_report, RecordingModel,
)
from observability import Tracer
from reliability import CircuitBreaker
import multiagent_tools as mt

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ops_demo")


def _texts(*texts):
    """按调用顺序排的假剧本：每个文本 = 一次 ask 的回答。"""
    return FakeModel([FakeResponse("end_turn", [text_block(t)]) for t in texts])


# ---------------------- 幕1：策略表 ----------------------

def act_policy():
    print("=" * 60)
    print("幕1 · 分级策略：每个角色配哪档？为什么？")
    print("-" * 60)
    for mode, label in [("pipeline", "流水线（诊断→根因→方案）"),
                        ("orchestrator", "主管-工人"),
                        ("debate", "评审团")]:
        print(f"\n【{label}】")
        for role, tier in role_tier_map(mode).items():
            print(f"  · {role:<12} → {tier:<5}（{TIERS[tier]['desc']}）")
    print("\n判断依据：思考越深的用贵档；半机械整理 + 有护栏兜底的才敢降档。")
    print("（护栏兜底 = 省钱的底气：方案官说危险词有 guard 拦着，糙一点翻不了天）")


# ---------------------- 幕2：分级真的生效 ----------------------

def act_effective():
    print()
    print("=" * 60)
    print("幕2 · 分级生效：每个角色真发了不同档位的模型名")
    print("-" * 60)
    # 三档各配一个"真实模型名"（假模型不在乎名字，RecordingModel 会记下来）
    tier_models = {"cheap": "claude-haiku-4-5", "mid": "claude-sonnet-4-5",
                   "top": "claude-opus-5"}
    print(f"档位 → 模型名：{tier_models}")

    # 对照：不配 tier（所有角色都用同一个默认模型）
    plain = RecordingModel(_texts("现场报告X", "根因Y", "方案Z"))
    mt.troubleshoot("服务好像挂了", plain, model_name="claude-opus-5")
    print("\n对照（不分级）：三个角色都发同一个模型名")
    print("  " + " → ".join(plain.model_names))

    # 分级：诊断/根因 = 旗舰，方案 = 经济档
    rec = RecordingModel(_texts("现场报告X", "根因Y", "方案Z"))
    mt.troubleshoot("服务好像挂了", rec, model_name="claude-opus-5",
                    tier_models=tier_models)
    print("\n分级后：三个角色各发各档的模型名")
    print("  " + " → ".join(rec.model_names))
    print("协调器无感：同一条流水线、同一个 run_pipeline，只是发的模型名不一样。")


# ---------------------- 幕3：省钱账 ----------------------

def act_saving():
    print()
    print("=" * 60)
    print("幕3 · 省钱：同样 3 环产出，无脑全旗舰 vs 分级路由")
    print("-" * 60)
    # 真实感的产出长度：诊断官写证据报告最长，方案官给步骤最短
    lens = {"diag": 4000, "root": 3000, "remedy": 2000}
    print(f"产出字符（成本 ∝ 输出）：{lens}")
    tiered_total, per_role = estimate_cost(lens, "pipeline")
    print(f"\n分级路由：{per_role}")
    print(f"  总账单 {tiered_total} 成本单位")
    report = savings_report(lens, "pipeline")
    print(f"对照全用旗舰：{report['baseline_cost']} 成本单位")
    print(f"省了 {report['saved']} 单位 = {report['pct']}%")
    print("钱省在哪：方案官这种『把根因翻成步骤』的机械活，旗舰模型能干的活")
    print("         经济档也能干——降档不掉质量，账单立刻瘦身。")


# ---------------------- 幕4：组合（分级 + 可靠性 + 可观测性） ----------------------

def act_combo(data_dir):
    print()
    print("=" * 60)
    print("幕4 · 组合：分级 + 重试/熔断 + trace 三层叠一起")
    print("-" * 60)
    tier_models = {"cheap": "claude-haiku-4-5", "mid": "claude-sonnet-4-5",
                   "top": "claude-opus-5"}

    # 会抽风的下游：前 2 次调用抛连接错误 → retries 扛住
    class _Flaky:
        def __init__(self, inner, fail_first):
            self._inner = inner
            self.fail_first = fail_first
            self.failed = 0

        @property
        def messages(self):
            return self

        def create(self, **kwargs):
            if self.failed < self.fail_first:
                self.failed += 1
                raise ConnectionError("下游暂时不可用")
            return self._inner.create(**kwargs)

    flaky = _Flaky(RecordingModel(
        _texts("现场报告X", "根因Y", "方案Z")), fail_first=2)
    tr = Tracer()
    breaker = CircuitBreaker(fail_threshold=3, recovery_time=1e9)
    out = mt.troubleshoot("服务好像挂了", flaky, model_name="claude-opus-5",
                          retries=2, breaker=breaker, tracer=tr,
                          tier_models=tier_models)
    print("返回结果照常（trace/重试没污染业务文本）：")
    print("  " + out.splitlines()[0])
    print("\n模型名记录（重试把前 2 次抽风扛掉后，各环仍发各档模型名）：")
    print("  " + " → ".join(flaky._inner.model_names))
    print("\ntrace 病历（谁 / 状态 / 耗时）：")
    print(tr.as_text())
    print("\n三层叠一起谁都不用改：重试在暗处守、分级在构造时定、trace 只记账。")


# ---------------------- 幕5：评审团为什么省得少 ----------------------

def act_debate_contrast():
    print()
    print("=" * 60)
    print("幕5 · 对照：评审团省得少——专家一个都不能降")
    print("-" * 60)
    lens = {"chair": 2000, "theory": 3000, "eng": 3000, "interviewer": 2500}
    report = savings_report(lens, "debate")
    print(f"评审团产出：{lens}")
    print(f"全旗舰 {report['baseline_cost']} 单位 → 分级 {report['tiered_cost']} 单位"
          f"（只省 {report['pct']}%）")
    print("为什么省不动：三个专家都在深度作答（理论/实现/考察点），降谁的档都掉质量；")
    print("只有主席是『装裱』→ 降到 mid。省钱要打在有机器的活上，烧脑的活省不得。")


# ---------------------- 真 API 分支 ----------------------

def act_real(data_dir):
    print()
    print("=" * 60)
    print("真 API 演示：按档位发不同模型名跑一遍流水线")
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
        base = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
    except Exception as exc:
        print(f"连不上真 API（{exc}）。用 --fake 跑离线五幕。")
        return
    from model_tiers import tier_models_from_env
    tier_models = tier_models_from_env(base)
    print(f"默认模型 {base}，档位→模型映射：{tier_models}")
    print("（若你的端点没有三个不同档位模型，可只设 CLAUDE_MODEL_CHEAP 指向便宜的、")
    print("  CLAUDE_MODEL_TOP 指向贵的；全不设 = 三档都用默认模型，不分级）")
    roles = resolve_role_models("pipeline", base, tier_models)
    print(f"本机将发给：诊断官={roles['diag']} 根因官={roles['root']} "
          f"方案官={roles['remedy']}")
    out = mt.troubleshoot("order-api 好像挂了，帮我排查一下", client, base,
                          data_dir=data_dir, tier_models=tier_models)
    print(out[:300])


# ---------------------- 入口 ----------------------

def main():
    parser = argparse.ArgumentParser(description="企业级加固 · 分级模型演示")
    parser.add_argument("--fake", action="store_true", help="离线演示（推荐）")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                        help="ops_demo 数据目录")
    args = parser.parse_args()

    if args.fake:
        act_policy()
        act_effective()
        act_saving()
        act_combo(args.data_dir)
        act_debate_contrast()
        print()
        print("=" * 60)
        print("五幕演完。一句话总结：")
        print("  分级 = 客厅 100W 走廊 5W——难环节用贵档、机械环节降经济档，")
        print("  省下的每一分钱都不掉质量；护栏兜底的地方，才敢放心降档。")
    else:
        act_real(args.data_dir)


if __name__ == "__main__":
    main()

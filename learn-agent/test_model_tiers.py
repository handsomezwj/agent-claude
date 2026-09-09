# model_tiers 测试：model_tiers.py（企业级加固 · 分级模型）
#
# 测什么（全离线、零模型）：
#   档位表       三个档位单价有梯度（cheap < mid < top）
#   策略表       每个模式里各角色配哪档、未知角色保守回退顶配、自定义策略可覆盖
#   模型名解析   档位 → 真实模型名：配了的档用配置、没配的档退回默认模型
#   RecordingModel 透明记录门：每次 create 记下 model 名，验证分级真的生效
#   成本估算     按"字符数 × 档位单价"算账，全旗舰 vs 分级的省钱比例可断言
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model_tiers import (
    TIERS, DEFAULT_POLICY, DEFAULT_TIER, MODE_ROLES,
    tier_for_role, role_tier_map, resolve_role_models,
    tier_models_from_env, estimate_cost, savings_report,
    RecordingModel,
)
from agent_loop import FakeModel, FakeResponse, text_block


def _model(*texts):
    return FakeModel([FakeResponse("end_turn", [text_block(t)]) for t in texts])


class TestTiers(unittest.TestCase):
    """档位目录：三档单价有梯度。"""

    def test_three_tiers_price_gradient(self):
        # cheap 必须比 mid 便宜，mid 必须比 top 便宜——省钱才有意义
        self.assertLess(TIERS["cheap"]["price"], TIERS["mid"]["price"])
        self.assertLess(TIERS["mid"]["price"], TIERS["top"]["price"])

    def test_every_tier_has_desc(self):
        for tier, info in TIERS.items():
            self.assertTrue(info["desc"], f"{tier} 缺人话描述")


class TestPolicy(unittest.TestCase):
    """角色 → 档位策略表：该贵的贵、该省的省。"""

    def test_pipeline_remedy_is_cheap(self):
        # 方案官是"把根因翻成步骤"的机械活 + 有护栏兜底 → 降经济档
        self.assertEqual(tier_for_role("pipeline", "remedy"), "cheap")

    def test_pipeline_reasoning_roles_are_top(self):
        # 诊断/根因是推理主场 → 旗舰档
        self.assertEqual(tier_for_role("pipeline", "diag"), "top")
        self.assertEqual(tier_for_role("pipeline", "root"), "top")

    def test_orchestrator_mechanical_workers_cheap(self):
        # 工人查窄维度是模板化核查 → cheap；风险审视/主管要判断 → mid
        self.assertEqual(tier_for_role("orchestrator", "status"), "cheap")
        self.assertEqual(tier_for_role("orchestrator", "log"), "cheap")
        self.assertEqual(tier_for_role("orchestrator", "risk"), "mid")
        self.assertEqual(tier_for_role("orchestrator", "boss"), "mid")

    def test_debate_experts_cannot_be_downgraded(self):
        # 专家都在深度作答，一个都不能降 → top；主席是"装裱"→ mid
        for role in ("theory", "eng", "interviewer"):
            self.assertEqual(tier_for_role("debate", role), "top",
                             f"{role} 不该降档")
        self.assertEqual(tier_for_role("debate", "chair"), "mid")

    def test_unknown_role_conservatively_top(self):
        # 策略表里没有的角色 → 保守按顶配算（别为省钱悄悄降了该用旗舰的环）
        self.assertEqual(tier_for_role("pipeline", "not_a_role"), DEFAULT_TIER)
        self.assertEqual(tier_for_role("unknown_mode", "diag"), DEFAULT_TIER)

    def test_custom_policy_overrides_default(self):
        # 档位是"业务判断"，允许调用方用自己的表覆盖默认
        custom = {"pipeline": {"diag": "cheap", "root": "cheap", "remedy": "top"}}
        self.assertEqual(tier_for_role("pipeline", "diag", custom), "cheap")
        self.assertEqual(tier_for_role("pipeline", "remedy", custom), "top")

    def test_role_tier_map_covers_all_roles(self):
        # 三种模式的完整映射：覆盖这个模式的所有角色、且都是合法档位
        for mode, roles in MODE_ROLES.items():
            mapping = role_tier_map(mode)
            self.assertEqual(set(mapping), set(roles))
            for tier in mapping.values():
                self.assertIn(tier, TIERS)


class TestResolveModels(unittest.TestCase):
    """档位 → 真实模型名：配了的档用配置，没配的退回默认。"""

    TIER_MODELS = {"cheap": "claude-haiku-4-5", "top": "claude-opus-5"}

    def test_tiered_roles_get_their_tier_model(self):
        names = resolve_role_models("pipeline", "claude-opus-5", self.TIER_MODELS)
        self.assertEqual(names["diag"], "claude-opus-5")     # top 档 → 旗舰
        self.assertEqual(names["root"], "claude-opus-5")
        self.assertEqual(names["remedy"], "claude-haiku-4-5")  # cheap 档 → 经济

    def test_missing_tier_falls_back_to_default(self):
        # 只配了 top、没配 cheap → 方案官不该拿到空/错模型，退回默认模型
        names = resolve_role_models("pipeline", "claude-opus-5", {"top": "claude-opus-5"})
        self.assertEqual(names["remedy"], "claude-opus-5")

    def test_no_tier_models_means_all_default(self):
        # 没传 tier_models（默认不分级）→ 所有角色同一个默认模型名
        names = resolve_role_models("pipeline", "claude-opus-5", None)
        self.assertEqual(set(names.values()), {"claude-opus-5"})

    def test_orchestrator_role_names(self):
        names = resolve_role_models("orchestrator", "claude-opus-5", self.TIER_MODELS)
        self.assertEqual(names["boss"], "claude-opus-5")    # mid 没配 → 默认
        self.assertEqual(names["status"], "claude-haiku-4-5")
        self.assertEqual(names["risk"], "claude-opus-5")


class TestTierModelsFromEnv(unittest.TestCase):
    """从环境变量读三档模型名；没设的档位退回默认。"""

    def tearDown(self):
        for key in ("CLAUDE_MODEL_CHEAP", "CLAUDE_MODEL_MID", "CLAUDE_MODEL_TOP"):
            os.environ.pop(key, None)

    def test_unset_env_means_all_default(self):
        result = tier_models_from_env("claude-opus-5")
        self.assertEqual(result, {"cheap": "claude-opus-5", "mid": "claude-opus-5",
                                  "top": "claude-opus-5"})

    def test_partial_env_only_overrides_set_tier(self):
        os.environ["CLAUDE_MODEL_CHEAP"] = "claude-haiku-4-5"
        result = tier_models_from_env("claude-opus-5")
        self.assertEqual(result["cheap"], "claude-haiku-4-5")
        self.assertEqual(result["top"], "claude-opus-5")
        self.assertEqual(result["mid"], "claude-opus-5")


class TestRecordingModel(unittest.TestCase):
    """透明记录门：记下每次调用发的 model 名。"""

    def test_records_model_name_per_call(self):
        rec = RecordingModel(_model("A", "B"))
        fake_agent_ask = lambda: rec.create(model="claude-opus-5", max_tokens=1)
        fake_agent_ask()
        fake_agent_ask()
        self.assertEqual(rec.model_names, ["claude-opus-5", "claude-opus-5"])

    def test_result_passthrough(self):
        inner = _model("回答文本")
        rec = RecordingModel(inner)
        resp = rec.create(model="claude-haiku-4-5")
        self.assertEqual("".join(b.text for b in resp.content
                                 if getattr(b, "type", None) == "text"), "回答文本")


class TestCost(unittest.TestCase):
    """成本估算：字符数 × 档位单价，全旗舰对照能算出省钱比例。"""

    LENS = {"diag": 4000, "root": 3000, "remedy": 2000}

    def test_estimate_cost_matches_formula(self):
        # diag 4000字×top单价9/1000 = 36；remedy 2000字×cheap单价1/1000 = 2
        total, per_role = estimate_cost(self.LENS, "pipeline")
        self.assertEqual(per_role["diag"], 36.0)
        self.assertEqual(per_role["remedy"], 2.0)
        self.assertEqual(total, 65.0)

    def test_savings_report_pipeline_saves(self):
        report = savings_report(self.LENS, "pipeline")
        self.assertEqual(report["baseline_cost"], 81.0)   # 全 top：9 的 9 倍…全 4000·9/1000 之和
        self.assertGreater(report["saved"], 0)
        self.assertEqual(report["pct"], 19.8)

    def test_savings_report_zero_when_all_top(self):
        # 把策略全设成 top → 分级跟基线一样，省 0%
        report = savings_report(self.LENS, "pipeline",
                                {"pipeline": {r: "top" for r in MODE_ROLES["pipeline"]}})
        self.assertEqual(report["saved"], 0.0)
        self.assertEqual(report["pct"], 0.0)

    def test_debate_saves_less_than_pipeline(self):
        # 评审团只有主席能降 → 省钱比例应该明显小于流水线
        pipe = savings_report(self.LENS, "pipeline")
        debate_lens = {"chair": 2000, "theory": 3000, "eng": 3000, "interviewer": 2500}
        debate = savings_report(debate_lens, "debate")
        self.assertLess(debate["pct"], pipe["pct"])


if __name__ == "__main__":
    unittest.main()

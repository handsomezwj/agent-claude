# model_tiers.py —— 多 Agent 企业级加固 · 分级模型（省钱路由）
#
# 问题：多 Agent 一次要调 3~4 次模型，每次都调最贵最强的模型？未必。
#       「诊断官」读原始日志做推理，值贵的；「方案官」把根因翻成修复步骤，
#       是半机械的整理活，且输出还被安全护栏扫一遍——用便宜的也够。
#       全用最贵 = 每单都按顶配付钱，钱花在不需要的地方。
#
# 答案：分级模型（也叫模型路由 / model routing）——给不同环节配不同档位的模型。
#       需要强推理的环用旗舰档（贵但准），机械/模板化的环用经济档（便宜够用）。
#       这不是拍脑袋：档位由一张「角色 → 档位」策略表决定，纯数据、可配、可换。
#
# 心法对照（面试可讲）：
#   一次调用全用顶配   = 家里所有灯泡都装 100W，走廊厕所也用不着
#   分级路由            = 客厅 100W、走廊 5W——亮度刚好的地方不浪费电
#   护栏兜底 = 省钱底气  = 敢给「方案官」降档，是因为它说危险词有安全护栏拦着，
#                          模型糙一点也翻不了天——用便宜模型前先想清楚"谁兜底"
#
# 关键机制：Agent 的 model_name 在构造时定死，而同一个 client 每次请求
#   都能指定不同 model 名 → 分级发生在"造 Agent"那一步：谁该用哪档，就在
#   构造时给它发哪个模型名。协调器只认 ask()，完全无感（门哲学第三次兑现）。
#
# 测试哲学（老规矩）：纯数据 + 纯函数，注入假模型随便测，零成本。
#   成本估算按「输出字符数 × 档位单价」——真实 LLM 成本 = 输出 token 数 × 单价，
#   离线没法数 token，用字符数当代理量，相对省钱比例照样算得准。
import os


# ---------------------- 档位目录（纯数据） ----------------------
# 单价是"相对单位"（每 1000 字符），真实价格按模型厂商表走，这里只比相对贵贱。
TIERS = {
    "cheap": {"price": 1, "desc": "经济档：机械/模板化整理活，便宜够用"},
    "mid":   {"price": 3, "desc": "标准档：常规推理，性价比之选"},
    "top":   {"price": 9, "desc": "旗舰档：强推理/高价值环节，贵但准"},
}

# ---------------------- 角色 → 档位 策略表（纯数据，可配） ----------------------
# 三种协作模式各有一张表：哪个角色配哪档。档位是"业务判断"——
# 判断依据 = 这环思考有多深 + 这环说错了有没有别的机制兜底。
#   · 推理主战场（读证据下判断）→ top
#   · 需要判断但不烧脑             → mid
#   · 半机械整理、且有护栏兜底     → cheap
DEFAULT_POLICY = {
    # 流水线：诊断/根因是推理主场（top）；方案官把根因"翻译"成步骤、机械，
    #   且输出被 guard_remedy 安全护栏兜底 → 放心降 cheap（护栏 = 省钱底气）。
    "pipeline": {
        "diag": "top",
        "root": "top",
        "remedy": "cheap",
    },
    # 主管-工人：工人每人只查一个窄维度（状态在不在/日志有没有错/风险点），
    #   是模板化核查 → status/log 用 cheap；risk 与 boss 要做判断 → mid。
    "orchestrator": {
        "boss": "mid",
        "status": "cheap",
        "log": "cheap",
        "risk": "mid",
    },
    # 评审团：三个专家各自深度作答（理论/实现/考察点都是烧脑的）→ top 一个都不能降；
    #   主席是把好答案整合成结构，用 mid 就够——专家答得好是上限，主席只是"装裱"。
    "debate": {
        "chair": "mid",
        "theory": "top",
        "eng": "top",
        "interviewer": "top",
    },
}

# 每种模式下都有哪些角色（构造 Agent 时按这个清单逐人发 model 名）
MODE_ROLES = {
    "pipeline": ("diag", "root", "remedy"),
    "orchestrator": ("boss", "status", "log", "risk"),
    "debate": ("chair", "theory", "eng", "interviewer"),
}

# 没配策略的角色默认档位：top（保守——不认识的环节按贵的算，
# 别为了省钱把该用旗舰的环节悄悄降了档）
DEFAULT_TIER = "top"

# 环境变量：真 API 模式下，每个档位实际发哪个模型名（可关可换）
ENV_TIER_MODELS = {
    "cheap": "CLAUDE_MODEL_CHEAP",
    "mid": "CLAUDE_MODEL_MID",
    "top": "CLAUDE_MODEL_TOP",
}


# ---------------------- 纯函数①：角色配哪档 ----------------------

def tier_for_role(mode, role_key, policy=None):
    """问策略表：这个角色（在这套协作模式里）配哪个档位。纯函数，可测。

    mode      协作模式：pipeline / orchestrator / debate
    role_key  角色名：diag / root / remedy / boss / status / log / risk /
              chair / theory / eng / interviewer
    policy    自定义策略表（默认用 DEFAULT_POLICY）。
    """
    table = (policy or DEFAULT_POLICY).get(mode, {})
    return table.get(role_key, DEFAULT_TIER)   # 表里没有 → 保守按顶配算


def role_tier_map(mode, policy=None):
    """把这套模式所有角色 → 档位 的完整映射拉出来（演示/打印用）。"""
    return {role: tier_for_role(mode, role, policy)
            for role in MODE_ROLES[mode]}


# ---------------------- 纯函数②：档位 → 真实模型名 ----------------------

def resolve_role_models(mode, default_model, tier_models=None):
    """决定这套模式里，每个角色实际发给哪个模型名。纯函数，可测。

    规则：查该角色的档位 → 查 tier_models 里这个档位配的真实模型名；
          某档没配 → 全用 default_model（不会因配置不全而发错模型）。
    tier_models   {档位: 模型名}，如 {"cheap": "claude-haiku-4-5",
                                     "top": "claude-opus-5"}
    """
    tier_models = tier_models or {}
    names = {}
    for role in MODE_ROLES[mode]:
        tier = tier_for_role(mode, role)
        names[role] = tier_models.get(tier, default_model)
    return names


def tier_models_from_env(default_model):
    """从环境变量读三个档位各自的模型名（没配的档位 = 默认模型）。

    真 API 下 agent-claude.py 用它把 CLAUDE_MODEL_CHEAP/MID/TOP
    读进来；全没配 = 三档都退回默认模型（行为与不分级完全一致）。
    """
    return {tier: os.environ.get(env, "").strip() or default_model
            for tier, env in ENV_TIER_MODELS.items()}


# ---------------------- 纯函数③：成本估算（谁贵谁便宜） ----------------------

def estimate_cost(role_lengths, mode, policy=None):
    """估算这套模式跑一次花了多少"成本单位"。

    role_lengths  {角色: 输出字符数}——真实成本 ∝ 输出 token，离线用字符数当代理量。
    成本单位 = Σ 字符数 × 该角色档位单价 / 1000（单价按 TIERS 的每 1000 字符算）。
    返回 (总成本, {角色: 单项成本})。纯函数，可测。
    """
    total = 0.0
    per_role = {}
    for role, length in (role_lengths or {}).items():
        tier = tier_for_role(mode, role, policy)
        cost = length * TIERS[tier]["price"] / 1000.0
        per_role[role] = cost
        total += cost
    return round(total, 3), per_role


def savings_report(role_lengths, mode, policy=None, all_top="top"):
    """拿「全用旗舰档」当基线，算分级路由省了多少。纯函数，可测。

    返回 {baseline_cost 全用 top 的账单, tiered_cost 分级后的账单,
          saved 省了多少单位, pct 省了百分之几}。
    演示里对比一看：同样的活，省钱路由 vs 无脑全顶配。
    """
    baseline_total, _ = estimate_cost(role_lengths, mode,
                                      _all_top_policy(mode, all_top))
    tiered_total, _ = estimate_cost(role_lengths, mode, policy)
    saved = round(baseline_total - tiered_total, 3)
    pct = round(saved / baseline_total * 100, 1) if baseline_total else 0.0
    return {"baseline_cost": baseline_total, "tiered_cost": tiered_total,
            "saved": saved, "pct": pct}


def _all_top_policy(mode, tier):
    """内部：生成一张"所有角色都是旗舰档"的对照策略表。"""
    return {mode: {role: tier for role in MODE_ROLES[mode]}}


# ---------------------- 记录门：看每个 Agent 真发了哪个模型名 ----------------------

class RecordingModel:
    """透明记录门：包住任何 .messages.create 的对象，记下每次调用发的 model 名。

    为什么需要它：分级发生在构造时（model_name 定死），普通 FakeModel 只看得到
    "被调了几次"，看不到"用哪个档位调的"。包一层 RecordingModel，每次 create
    都把 kwargs["model"] 记进 model_names，就能验证「诊断官真用了旗舰、方案官真用了
    经济档」——分级没有悄悄失效。测试/演示都能用，真 API 不用包它。
    """

    def __init__(self, inner):
        self._inner = inner
        self.model_names = []       # 每次调用发的 model 名，按顺序记录

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.model_names.append(kwargs.get("model"))
        return self._inner.create(**kwargs)

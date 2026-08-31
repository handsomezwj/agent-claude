# 测"你自己的 agent"的护栏：把真 client 换成假模型，一分钱不花
# 跑：python learn-agent/test_real_agent.py
#
# 它证明：agent-claude.py 新抽出的 handle_user_turn，跟 agent_loop 里测的
# handle_turn 一样能被剧本驱动、护栏真的会拦。
import os
import sys
import importlib.util

# 1) 借用 agent_loop 里的假模型
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent_loop import FakeModel, FakeResponse, tool_block, text_block

# 2) 加载带连字符的文件名（agent-claude.py 没法直接 import，用 importlib 借道）
agent_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "agent-claude.py"
)
spec = importlib.util.spec_from_file_location("agent_claude", agent_path)
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def run(title, script, user_msg):
    print(f"\n===== {title} =====")
    agent.client = FakeModel(script)   # 换心：真 client → 假模型
    outcome = agent.handle_user_turn([{"role": "user", "content": user_msg}])
    print(f"→ 这轮结束：{outcome}   （假模型被调了 {agent.client.calls} 次）")
    return outcome, agent.client.calls


# 剧本 1：正常问答
o1, c1 = run("剧本 1 · 正常问答", [
    FakeResponse("end_turn", [text_block("你好，我是 lcc。")]),
], "你好")

# 剧本 2：工具循环（load_skill 是读本地文件，无副作用）
o2, c2 = run("剧本 2 · 工具循环", [
    FakeResponse("tool_use", [tool_block("load_skill", {"skill_name": "python"})]),
    FakeResponse("end_turn", [text_block("已加载 Python 知识。")]),
], "讲讲 Python")

# 剧本 3：坏模型连点 3 次同一工具 → 打转护栏刹车，不用等第 4 次
o3, c3 = run("剧本 3 · 原地打转", [
    FakeResponse("tool_use", [tool_block("load_skill", {"skill_name": "python"})]) for _ in range(3)
], "讲讲 Python")

# 剧本 4：每次换参数 → 不打转，6 圈兜底，第 7 圈检查拦住
o4, c4 = run("剧本 4 · 绕不出来", [
    FakeResponse("tool_use", [tool_block("load_skill", {"skill_name": s})])
    for s in ["python", "git", "shell", "python", "git", "shell"]
], "挨个加载")

# 剧本 5：裁判打分（第九课）——END_TURN 后 judge_last_turn 用假裁判给 4/5
print("\n===== 剧本 5 · 裁判打分 =====")
agent.client = FakeModel([
    FakeResponse("end_turn", [text_block("你好，我是 lcc。")]),  # ① agent 的回答
    FakeResponse("end_turn", [text_block("4/5\n不错")]),          # ② 裁判的分数
])
msgs = [{"role": "user", "content": "你好"}]
o5 = agent.handle_user_turn(msgs)
s5 = agent.judge_last_turn(msgs)
print(f"→ 这轮结束：{o5}，裁判打分：{s5}/5（假模型共被调 {agent.client.calls} 次）")

# 3) 裁判：护栏必须真的拦住
assert o1 == "END_TURN", f"剧本1 应 END_TURN，实际 {o1}"
assert o2 == "END_TURN" and c2 == 2, f"剧本2 应 2 次结束，实际 {o2}/{c2}"
assert o3 == "STUCK" and c3 == 3, f"剧本3 应第 3 次刹车，实际 {o3}/{c3}"
assert o4 == "MAX_ITERS" and c4 == 6, f"剧本4 应 6 圈兜底，实际 {o4}/{c4}"
assert o5 == "END_TURN" and s5 == 4, f"剧本5 应 END_TURN 且裁判给 4 分，实际 {o5}/{s5}"

print("\n✅ 五个剧本全部符合预期——你真正的 agent 现在有护栏和裁判了。")

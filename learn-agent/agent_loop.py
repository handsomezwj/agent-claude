# 被测对象：整个 agent 循环（假模型 + handle_turn）
# 第八课的核心：把"循环"也变成能测的东西。
# 做法：真实模型换成"按剧本演出的假模型"，接口一模一样，循环一行不改。
from agent_tools import run_tool
from spin_guard import make_fingerprint, track_repeat

MAX_ITERS = 5      # 兜底：最多 5 圈
MAX_REPEATS = 3    # 聪明：同一道菜连点 3 次 = 打转


# ---------------------- 假模型 ----------------------

class FakeBlock:
    """模拟 API 返回的 content block，只留我们用到的字段"""
    def __init__(self, btype, **fields):
        self.type = btype
        for k, v in fields.items():
            setattr(self, k, v)


def tool_block(name, args):
    """造一个"模型想调工具"的块"""
    return FakeBlock("tool_use", name=name, input=args, id=f"id-{name}")


def text_block(text):
    """造一个"模型开口说话"的块"""
    return FakeBlock("text", text=text)


class FakeResponse:
    """模拟一次 API 返回：stop_reason 决定循环走哪条路"""
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class FakeModel:
    """假模型 = 一个剧本列表 + 一个计数器。

    真实模型每次答案都不一样、几乎不打转 → 没法测护栏。
    剧本写死、还能演"坏模型" → 护栏每个角落都能测到。
    """
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        if self.calls >= len(self.script):
            raise RuntimeError(f"剧本演完了！被调 {self.calls} 次，剧本只有 {len(self.script)} 句。")
        resp = self.script[self.calls]
        self.calls += 1
        return resp


# ---------------------- 循环（抽成函数） ----------------------

def handle_turn(model, user_input, history):
    """跑完一轮对话，返回这轮怎么结束的：'ANSWER:...' / 'STUCK' / 'MAX_ITERS'"""
    history.append({"role": "user", "content": user_input})

    last_call = None
    repeat_count = 0
    turn = 0

    while True:
        turn += 1
        if turn > MAX_ITERS:   # 兜底护栏
            print("AI：我绕不出来了，请换个说法再试。")
            return "MAX_ITERS"

        resp = model.messages.create(model="fake", max_tokens=1000, messages=history)

        if resp.stop_reason == "tool_use":
            history.append({"role": "assistant", "content": resp.content})
            results = []
            stuck = False
            for block in resp.content:
                if block.type == "tool_use":
                    # 打转判断：借被测试保护的逻辑
                    this_call = make_fingerprint(block.name, block.input)
                    repeat_count, stuck_now = track_repeat(
                        last_call, repeat_count, this_call, MAX_REPEATS
                    )
                    last_call = this_call

                    if stuck_now:
                        print(f"  [检测到打转] 连续 {MAX_REPEATS} 次调用同一工具：{block.name}")
                        stuck = True
                        break

                    result = run_tool(block.name, block.input)
                    print(f"  [执行工具] {block.name}({block.input}) -> {result}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            if stuck:
                print("AI：我在原地打转，请换个说法再试。")
                return "STUCK"

            history.append({"role": "user", "content": results})

        else:
            # 模型开口说话 → 这轮结束
            answer = "".join(b.text for b in resp.content if b.type == "text")
            print("AI：", answer)
            history.append({"role": "assistant", "content": resp.content})
            return f"ANSWER:{answer}"

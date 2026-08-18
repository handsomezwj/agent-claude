# 第八课：用假模型测整个循环——一分钱 API 都不花
# 跑起来看四个剧本：python 05-mock-loop.py
from agent_loop import FakeModel, FakeResponse, tool_block, text_block, handle_turn


def show(title, script, user_input):
    print(f"\n===== {title} =====")
    fake = FakeModel(script)
    outcome = handle_turn(fake, user_input, history=[])
    print(f"→ 这轮结束：{outcome}   （假模型被调了 {fake.calls} 次）")


if __name__ == "__main__":
    # 剧本 1：正常问答
    show("剧本 1 · 正常问答", [
        FakeResponse("end_turn", [text_block("今天天气不错！")]),
    ], "你好")

    # 剧本 2：问天气 → 模型点菜 → 程序做菜 → 模型复述结果
    show("剧本 2 · 工具循环", [
        FakeResponse("tool_use", [tool_block("get_weather", {"city": "北京"})]),
        FakeResponse("end_turn", [text_block("北京今天晴，32°C。")]),
    ], "北京天气怎么样")

    # 剧本 3：坏模型连点 3 次同一道菜 → 打转护栏刹车
    show("剧本 3 · 原地打转", [
        FakeResponse("tool_use", [tool_block("get_weather", {"city": "北京"})]),
        FakeResponse("tool_use", [tool_block("get_weather", {"city": "北京"})]),
        FakeResponse("tool_use", [tool_block("get_weather", {"city": "北京"})]),
    ], "查北京天气")

    # 剧本 4：坏模型每次都调工具但每次换城市 → 不打转，5 圈兜底收尾
    show("剧本 4 · 绕不出来", [
        FakeResponse("tool_use", [tool_block("get_weather", {"city": "北京"})]),
        FakeResponse("tool_use", [tool_block("get_weather", {"city": "上海"})]),
        FakeResponse("tool_use", [tool_block("get_weather", {"city": "广州"})]),
        FakeResponse("tool_use", [tool_block("get_weather", {"city": "深圳"})]),
        FakeResponse("tool_use", [tool_block("get_weather", {"city": "武汉"})]),
    ], "挨个查天气")

# 从循环里"抽出来的纯逻辑"：判断一次工具调用是否"原地打转"
def make_fingerprint(name: str, args: dict) -> tuple:
    """给一次工具调用做指纹：(工具名, 排序后的参数)"""
    return (name, str(sorted(args.items())))


def track_repeat(prev_call, repeat_count, this_call, max_repeats=3):
    """喂它三个数：(上一次指纹, 连数, 这次指纹) → 返回 (新连数, 是否打转)
    和 04 文件里那几行 if 完全一样的逻辑，只是抽成了函数。
    """
    if this_call == prev_call:
        repeat_count += 1
    else:
        repeat_count = 1
    return repeat_count, repeat_count >= max_repeats

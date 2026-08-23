# async_utils.py — 异步编程学习模块（被测对象）
#
# 门（door）：fake_call 模拟一次"真实 API 调用"（等 seconds 秒才返回结果）。
# 所有 run_* 函数都接收"协程列表"，调用方给什么就跑什么——测试可控、可计时、不联网。
#
# 三个核心概念复习：
#   async def  定义能暂停的协程
#   await      暂停点（把控制权交回事件循环）
#   gather     把多个协程"同时挂上去"的并发工具
#
# 一句话：异步不让你变快，只让"等待"不再互相等。

import asyncio


async def fake_call(name, seconds=0.1):
    """模拟一次 API 调用：等 seconds 秒后返回 f"{name}:{seconds}"。
    注意用的是 asyncio.sleep——它会暂停自己、把控制权交回事件循环，
    让同一时刻的其他协程趁机跑。这是和 time.sleep（霸占整个线程）的本质区别。
    """
    await asyncio.sleep(seconds)
    return f"{name}:{seconds}"


async def run_serial(calls):
    """串行：一个 await 完才轮到下一个。
    总耗时 = 每个协程时长相加（等待没有叠起来）。
    """
    return [await c for c in calls]


async def run_concurrent(calls):
    """并发：用 gather 把协程同时挂上去。
    总耗时 ≈ 最慢的那个（等待被叠起来）。
    注意：返回顺序 = 传入顺序，跟谁先完成无关（gather 保证保序）。
    """
    return await asyncio.gather(*calls)


async def run_limited(calls, max_concurrent):
    """限流：同一时刻最多 max_concurrent 个协程在跑。
    模拟真实 API 的"并发配额"——一次性冲太多请求会被限流/打爆。
    用 Semaphore（信号量）当"收费站"：闸口放行 N 个，满了排队。
    """
    sem = asyncio.Semaphore(max_concurrent)

    async def one(call):
        async with sem:
            return await call

    return await asyncio.gather(*(one(c) for c in calls))

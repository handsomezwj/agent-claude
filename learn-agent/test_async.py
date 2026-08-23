# test_async.py — 异步编程单元测试
# 不需要 pytest-asyncio：每个测试里用 asyncio.run() 把协程跑完，unittest 就能测。
# 测点：串行耗时为和 / 并发耗时为最大 / 保序 / 限流上限 / 边界。
import asyncio
import time
import unittest

import async_utils


def tracked_call(name, seconds, state):
    """包装 fake_call：记录『同时有几个协程在跑』，用来验证并发数和限流上限。"""
    async def wrapped():
        state["current"] += 1
        state["max"] = max(state["max"], state["current"])
        try:
            return await async_utils.fake_call(name, seconds)
        finally:
            state["current"] -= 1
    return wrapped()   # ← 返回协程对象（调用 wrapped），不是函数


class TestSerial(unittest.TestCase):
    def test_serial_takes_sum(self):
        """串行：3 个 0.1s 请求，总耗时 ≈ 0.3s（等待相加，没叠起来）"""
        calls = [async_utils.fake_call(f"t{i}", 0.1) for i in range(3)]
        t = time.time()
        asyncio.run(async_utils.run_serial(calls))
        elapsed = time.time() - t
        self.assertGreaterEqual(elapsed, 0.25)

    def test_serial_runs_one_at_a_time(self):
        """串行：同一时刻最多 1 个协程在跑"""
        state = {"current": 0, "max": 0}
        calls = [tracked_call(f"t{i}", 0.05, state) for i in range(3)]
        asyncio.run(async_utils.run_serial(calls))
        self.assertEqual(state["max"], 1)

    def test_serial_returns_in_order(self):
        calls = [async_utils.fake_call(f"t{i}", 0.01) for i in range(3)]
        result = asyncio.run(async_utils.run_serial(calls))
        self.assertEqual(result, ["t0:0.01", "t1:0.01", "t2:0.01"])


class TestConcurrent(unittest.TestCase):
    def test_concurrent_takes_max_not_sum(self):
        """并发：3 个 0.1s 请求，总耗时明显 < 0.3s（≈ 0.1s，叠起来了）"""
        calls = [async_utils.fake_call(f"t{i}", 0.1) for i in range(3)]
        t = time.time()
        asyncio.run(async_utils.run_concurrent(calls))
        elapsed = time.time() - t
        self.assertLess(elapsed, 0.25)

    def test_concurrent_all_at_once(self):
        """并发：4 个协程同一时刻全在跑（并发数 = 调用数）"""
        state = {"current": 0, "max": 0}
        calls = [tracked_call(f"t{i}", 0.05, state) for i in range(4)]
        asyncio.run(async_utils.run_concurrent(calls))
        self.assertEqual(state["max"], 4)

    def test_concurrent_returns_in_order(self):
        """保序：gather 返回顺序 = 传入顺序，跟谁先完成无关"""
        calls = [async_utils.fake_call(f"t{i}", 0.05) for i in range(3)]
        result = asyncio.run(async_utils.run_concurrent(calls))
        self.assertEqual(result, ["t0:0.05", "t1:0.05", "t2:0.05"])


class TestLimited(unittest.TestCase):
    def test_limited_never_exceeds_max(self):
        """限流：max=2，4 个任务 → 同时最多 2 个在跑"""
        state = {"current": 0, "max": 0}
        calls = [tracked_call(f"t{i}", 0.05, state) for i in range(4)]
        asyncio.run(async_utils.run_limited(calls, max_concurrent=2))
        self.assertEqual(state["max"], 2)

    def test_limited_still_parallel_to_cap(self):
        """限流不是退化成串行：max=2，4 个 0.1s → 总耗时 ~0.2s 而非 0.4s"""
        calls = [async_utils.fake_call(f"t{i}", 0.1) for i in range(4)]
        t = time.time()
        asyncio.run(async_utils.run_limited(calls, max_concurrent=2))
        elapsed = time.time() - t
        self.assertGreaterEqual(elapsed, 0.15)   # 至少分两批
        self.assertLess(elapsed, 0.35)           # 但远小于串行的 0.4s

    def test_limited_keeps_results_and_order(self):
        calls = [async_utils.fake_call(f"t{i}", 0.01) for i in range(4)]
        result = asyncio.run(async_utils.run_limited(calls, max_concurrent=2))
        self.assertEqual(result, [f"t{i}:0.01" for i in range(4)])


class TestEdges(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(asyncio.run(async_utils.run_serial([])), [])
        self.assertEqual(asyncio.run(async_utils.run_concurrent([])), [])
        self.assertEqual(asyncio.run(async_utils.run_limited([], 2)), [])

    def test_single_call(self):
        # 注意：协程对象是一次性的——await 过就不能再 await。
        # 所以两次跑都要重新调用 fake_call() 新建协程，不能复用同一个对象。
        self.assertEqual(
            asyncio.run(async_utils.run_serial([async_utils.fake_call("one", 0.01)])),
            ["one:0.01"],
        )
        self.assertEqual(
            asyncio.run(async_utils.run_concurrent([async_utils.fake_call("one", 0.01)])),
            ["one:0.01"],
        )

    def test_max_concurrent_equals_n(self):
        """限流上限给足到 N 时，效果等同全并发"""
        state = {"current": 0, "max": 0}
        calls = [tracked_call(f"t{i}", 0.05, state) for i in range(4)]
        asyncio.run(async_utils.run_limited(calls, max_concurrent=4))
        self.assertEqual(state["max"], 4)


if __name__ == "__main__":
    unittest.main()

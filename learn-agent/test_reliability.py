# 企业级加固 · 可靠性层测试：重试 / 超时 / 熔断 / HardenedAgent
#
# 全零成本：假门注入（会失败/会睡觉的函数）、假时钟（免真等）。
# 跑：python -m unittest test_reliability -v
import time
import unittest

from reliability import (
    retry_with_backoff, with_timeout, CircuitBreaker, HardenedAgent,
)


# ---------------------- 工具：一个会挂 / 会恢复的假下游 ----------------------

class Flaky:
    """前 fail_times 次返回 None（模拟 Agent 挂掉），之后返回 answer。"""

    def __init__(self, fail_times, answer="好了"):
        self.fail_times = fail_times
        self.answer = answer
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            return None
        return self.answer


class FakeClock:
    """假时钟：手动推进，测熔断冷却不用真等。"""

    def __init__(self, start=0.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class FakeSleep:
    """假 sleep：只记每次等多久，不真等。"""

    def __init__(self):
        self.waits = []

    def __call__(self, seconds):
        self.waits.append(round(seconds, 6))


# ---------------------- ① retry_with_backoff ----------------------

class TestRetry(unittest.TestCase):

    def test_success_no_retry(self):
        calls = []
        def fn():
            calls.append(1)
            return "ok"
        r = retry_with_backoff(fn, retries=3, base_delay=0.01)
        self.assertEqual(r, "ok")
        self.assertEqual(len(calls), 1)          # 一次就成，绝不重试

    def test_retry_after_exception(self):
        flaky = Flaky(2, answer="第三次成功")
        def fn():
            flaky.calls += 1
            if flaky.calls <= 2:
                raise RuntimeError("429 限流")
            return flaky.answer
        r = retry_with_backoff(fn, retries=3, base_delay=0.01)
        self.assertEqual(r, "第三次成功")
        self.assertEqual(flaky.calls, 3)         # 第 1、2 次失败，第 3 次成功

    def test_none_triggers_retry(self):
        flaky = Flaky(1, answer="第二次成功")
        r = retry_with_backoff(flaky, retries=2, base_delay=0.01)
        self.assertEqual(r, "第二次成功")         # 返回 None 也算失败，触发重试
        self.assertEqual(flaky.calls, 2)

    def test_exhausted_returns_none(self):
        flaky = Flaky(999)                       # 永远失败
        r = retry_with_backoff(flaky, retries=2, base_delay=0.01)
        self.assertIsNone(r)                     # 耗尽 → None，不抛
        self.assertEqual(flaky.calls, 3)         # 首次 + 2 次重试

    def test_backoff_is_exponential(self):
        flaky = Flaky(999)
        sleeper = FakeSleep()
        retry_with_backoff(flaky, retries=3, base_delay=0.1, sleep=sleeper)
        self.assertEqual(sleeper.waits, [0.1, 0.2, 0.4])   # 指数退避

    def test_should_retry_filter(self):
        # 只对限流类异常重试；权限错误直接放弃
        flaky = Flaky(999)
        def fn():
            flaky.calls += 1
            if flaky.calls <= 2:
                raise RuntimeError("429")
            raise PermissionError("403")
        r = retry_with_backoff(fn, retries=3, base_delay=0.01,
                               should_retry=lambda exc: "429" in str(exc))
        self.assertIsNone(r)                     # 403 不该重试
        self.assertEqual(flaky.calls, 3)         # 429 重试了 2 次，403 直接放弃


# ---------------------- ② with_timeout ----------------------

class TestTimeout(unittest.TestCase):

    def test_normal(self):
        r = with_timeout(lambda: "结果", timeout=1.0)
        self.assertEqual(r, "结果")

    def test_timeout_returns_none_fast(self):
        def slow():
            time.sleep(0.3)
            return "迟到的回答"
        start = time.monotonic()
        r = with_timeout(slow, timeout=0.05)
        elapsed = time.monotonic() - start
        self.assertIsNone(r)
        self.assertLess(elapsed, 0.2)            # 快速放弃，不傻等

    def test_timeout_none_runs_direct(self):
        r = with_timeout(lambda: "ok", timeout=None)
        self.assertEqual(r, "ok")

    def test_exception_swallowed(self):
        def boom():
            raise ValueError("炸了")
        r = with_timeout(boom, timeout=1.0)
        self.assertIsNone(r)                     # 异常吞成 None，不抛


# ---------------------- ③ CircuitBreaker ----------------------

class TestBreaker(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.breaker = CircuitBreaker(fail_threshold=3, recovery_time=5.0,
                                      clock=self.clock)

    def test_initial_closed(self):
        self.assertEqual(self.breaker.state, "CLOSED")
        self.assertEqual(self.breaker.fail_count, 0)

    def test_opens_after_threshold(self):
        flaky = Flaky(999)
        for _ in range(2):
            self.breaker.ask(flaky)              # 失败 2 次
        self.assertEqual(self.breaker.state, "CLOSED")
        self.breaker.ask(flaky)                  # 第 3 次失败
        self.assertEqual(self.breaker.state, "OPEN")

    def test_open_does_not_call_downstream(self):
        flaky = Flaky(999)
        for _ in range(3):
            self.breaker.ask(flaky)              # 连败 3 次 → OPEN
        calls_before = flaky.calls
        r = self.breaker.ask(flaky)
        self.assertIsNone(r)
        self.assertEqual(flaky.calls, calls_before)   # OPEN 时根本不调下游

    def test_recovers_after_recovery_time(self):
        flaky = Flaky(3, answer="恢复")           # 前 3 次失败，之后成功
        for _ in range(3):
            self.breaker.ask(flaky)              # 触发 OPEN
        self.clock.advance(5.0)                  # 冷却期过了
        self.assertEqual(self.breaker.state, "HALF_OPEN")
        r = self.breaker.ask(flaky)              # HALF_OPEN 试探
        self.assertEqual(r, "恢复")
        self.assertEqual(self.breaker.state, "CLOSED")   # 试探成功 → 恢复

    def test_half_open_failure_reopens(self):
        flaky = Flaky(999)
        for _ in range(3):
            self.breaker.ask(flaky)              # 触发 OPEN
        self.clock.advance(5.0)
        self.assertEqual(self.breaker.state, "HALF_OPEN")
        r = self.breaker.ask(flaky)              # 试探仍失败
        self.assertIsNone(r)
        self.assertEqual(self.breaker.state, "OPEN")     # 回 OPEN
        self.assertEqual(self.breaker.fail_count, 4)

    def test_success_resets_fail_count(self):
        # 连续失败语义：中间成功一次，计数清零
        self.breaker.ask(lambda: None)           # 失败 1
        self.breaker.ask(lambda: "ok")           # 成功 → 清零
        self.assertEqual(self.breaker.fail_count, 0)
        self.assertEqual(self.breaker.state, "CLOSED")

    def test_threshold_must_be_positive(self):
        with self.assertRaises(ValueError):
            CircuitBreaker(fail_threshold=0)
        with self.assertRaises(ValueError):
            CircuitBreaker(fail_threshold=-1)


# ---------------------- ④ HardenedAgent ----------------------

class FlakyAgent:
    """带 role/history 的假 Agent：前 fail_times 次 ask 返回 None。"""

    def __init__(self, role, fail_times, answer="答案"):
        self.role = role
        self.fail_times = fail_times
        self.answer = answer
        self.calls = 0

    def ask(self, text):
        self.calls += 1
        if self.calls <= self.fail_times:
            return None
        return self.answer

    def history(self):
        return [("user", "x"), ("assistant", self.answer)]


class TestHardenedAgent(unittest.TestCase):

    def test_retry_flaky_agent(self):
        agent = FlakyAgent("诊断官", fail_times=2, answer="现场报告")
        hardened = HardenedAgent(agent, retries=3, timeout=1.0)
        r = hardened.ask("排查一下")
        self.assertEqual(r, "现场报告")
        self.assertEqual(agent.calls, 3)         # 挂 2 次，第 3 次成功

    def test_exhausted_returns_none(self):
        agent = FlakyAgent("诊断官", fail_times=999)
        hardened = HardenedAgent(agent, retries=1, timeout=1.0)
        self.assertIsNone(hardened.ask("排查一下"))   # 耗尽 → None，不崩

    def test_breaker_short_circuits(self):
        agent = FlakyAgent("诊断官", fail_times=999)
        breaker = CircuitBreaker(fail_threshold=2, recovery_time=0.05)
        hardened = HardenedAgent(agent, retries=0, timeout=None, breaker=breaker)
        hardened.ask("a")
        hardened.ask("b")                        # 连败 2 次 → 熔断
        calls_before = agent.calls
        self.assertIsNone(hardened.ask("c"))
        self.assertEqual(agent.calls, calls_before)    # OPEN 时不再调真 Agent

    def test_history_forwarded(self):
        agent = FlakyAgent("诊断官", 0)
        hardened = HardenedAgent(agent, retries=0)
        self.assertEqual(hardened.history(), agent.history())

    def test_role_forwarded(self):
        agent = FlakyAgent("诊断官", 0)
        hardened = HardenedAgent(agent, retries=0)
        self.assertEqual(hardened.role, "诊断官")     # 协调器/演示打印照常可用

    def test_healthy_agent_untouched(self):
        # 正常的 Agent 包上硬化层，行为不变
        agent = FlakyAgent("根因官", 0, answer="正常回答")
        hardened = HardenedAgent(agent, retries=2, timeout=1.0)
        self.assertEqual(hardened.ask("hi"), "正常回答")
        self.assertEqual(agent.calls, 1)         # 没触发任何重试


if __name__ == "__main__":
    unittest.main()

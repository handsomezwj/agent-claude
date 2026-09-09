# reliability.py —— 多 Agent 企业级加固 · 可靠性层（第一步）
#
# 问题：真实世界里下游会挂。网络抖动、限流、模型超时、服务暂时不可用——
# 多 Agent 一个环挂，整条链就断。前面课程里 Agent 挂掉只做了「优雅降级」
# （返回 None 不崩），但那是"被动挨打"：挂了就认，不挣扎。
#
# 企业级要做的是「主动扛」：重试扛瞬时抖动、超时防止傻等、熔断防止把
# 已经坏掉的下游打到雪崩。三步合起来，叫可靠性（Reliability）。
#
# 心法对照：
#   重试  = 掉水里了，爬起来再跳一次（指数退避 = 越摔越慢，别连着撞墙）
#   超时  = 喊了半天没人应，不无限等，直接挂电话（防止傻等卡死整条链）
#   熔断  = 保险丝：电路坏了就跳闸，等冷却再试探，别把整栋楼烧了
#
# 组合顺序（面试可讲）：熔断先挡（快速失败）→ 超时兜住慢调用 →
# 重试扛瞬时抖动 → 最后才到真模型。任一环节失败，延续「优雅降级」哲学，
# 返回 None，绝不抛异常、绝不让协调器崩。
#
# 测试哲学（老规矩）：全部是纯函数/纯状态机，注入假门随便测，零成本。
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout

# 同步调用加超时需要一个"能打断"的执行器。Windows 没有 signal.alarm，
# 标准做法是借一个线程去跑，主线程限时等结果。全局单例线程池，
# 程序退出自然清理（演示/测试不会堆积太多线程）。
_EXECUTOR = ThreadPoolExecutor(max_workers=8)


# ---------------------- ① 通用重试：指数退避 ----------------------

def retry_with_backoff(fn, retries=2, base_delay=0.1, should_retry=None,
                       sleep=time.sleep):
    """调 fn()，没拿到结果（返回 None 或抛异常）就退避重试。

    retries      重试次数（不含首次）。比如 retries=2 = 最多尝试 3 次。
    base_delay   首次等待基准；第 n 次重试等 base_delay * 2**(n-1) 秒（指数退避）。
    should_retry 可选的"这次失败要不要重试"判定：fn(result_or_exc) → bool。
                 默认：结果为 None 或抛异常 → 重试。
    sleep        可注入的等待函数（测试传假 sleep 免真等）。

    返回：成功那次的 fn() 结果；重试耗尽仍失败 → 返回 None（优雅降级，不抛）。
    """
    attempt = 0
    while True:
        try:
            result = fn()
        except Exception as exc:
            result = None
            if should_retry is not None and not should_retry(exc):
                return None
        else:
            if should_retry is not None and not should_retry(result):
                return result
            if result is not None:
                return result
        # 到这里 = 这次没拿到结果，决定还要不要重试
        if attempt >= retries:
            return None
        sleep(base_delay * (2 ** attempt))
        attempt += 1


# ---------------------- ② 同步调用加超时 ----------------------

def with_timeout(fn, timeout=5.0):
    """同步调用 fn() 加超时上限：超时 / 抛异常 → 返回 None（优雅降级）。

    Windows 没有 signal.alarm，同步代码要"限时"只能借线程：
    把 fn 丢给线程池，主线程限时等 future.result(timeout)。
    超时 → cancel 掉（线程还在后台跑完，但结果我们不要了）。
    """
    if timeout is None or timeout <= 0:
        # 不设超时：直接跑。异常也吞成 None，保持"绝不抛"的契约。
        try:
            return fn()
        except Exception:
            return None
    future = _EXECUTOR.submit(fn)
    try:
        return future.result(timeout=timeout)
    except _FutTimeout:
        future.cancel()
        return None
    except Exception:
        return None


# ---------------------- ③ 熔断器：状态机 ----------------------

class CircuitBreaker:
    """熔断器：CLOSED → OPEN → HALF_OPEN → CLOSED 的保险丝。

    状态机（面试可画）：
      CLOSED   正常放行。每次成功把连续失败计数清零；连续失败 ≥ fail_threshold → OPEN
      OPEN     直接快速失败（不再调下游），防止把已坏的下游打到雪崩。
               等 recovery_time 秒冷却 → HALF_OPEN
      HALF_OPEN 放一个试探请求。成功 → CLOSED（恢复）；失败 → 回 OPEN，重置冷却
    纯状态机，不碰模型。clock 可注入（测试用假时钟免真等）。
    """

    def __init__(self, fail_threshold=3, recovery_time=1.0, clock=time.monotonic):
        if fail_threshold <= 0:
            raise ValueError("fail_threshold 必须大于 0")
        self.fail_threshold = fail_threshold
        self.recovery_time = recovery_time
        self._clock = clock
        self._fail_count = 0
        self._state = "CLOSED"        # CLOSED / OPEN / HALF_OPEN
        self._open_since = None       # 何时进入 OPEN（用于算冷却）

    # --- 状态查询（演示/测试可读） ---
    @property
    def state(self):
        # 若 OPEN 且已过冷却 → 转入 HALF_OPEN（放行试探）。惰性转换。
        if self._state == "OPEN" and self._clock() - self._open_since >= self.recovery_time:
            self._state = "HALF_OPEN"
        return self._state

    @property
    def fail_count(self):
        return self._fail_count

    # --- 对外唯一入口 ---
    def ask(self, fn):
        """根据状态放行或拦截一次调用。成功 → True，失败 → None。"""
        if self.state == "OPEN":
            return None                     # 快速失败：根本不调下游

        try:
            result = fn()
        except Exception:
            result = None

        if result is None:
            return self._record_failure()
        self._fail_count = 0                # 成功：连续失败清零
        self._state = "CLOSED"
        return result

    # --- 内部：记一笔失败，按状态转移 ---
    def _record_failure(self):
        self._fail_count += 1
        if self._state == "HALF_OPEN":
            # 试探失败：电路又坏了，回 OPEN 并重置冷却
            self._state = "OPEN"
            self._open_since = self._clock()
        elif self._fail_count >= self.fail_threshold:
            self._state = "OPEN"
            self._open_since = self._clock()
        return None


# ---------------------- ④ 包装类：把 Agent 包上可靠性 ----------------------

class HardenedAgent:
    """把任意有 .ask()/.history() 的对象包上可靠性，协调器完全无感。

    协调器只认 ask() 和 history() 两个门——包了 HardenedAgent 之后
    它拿到的还是这两个门，行为却多了"重试/超时/熔断"。这就是
    「门哲学」的又一次兑现：换一个更硬的脑子，谁都不用改。

    组合顺序（内→外）：真模型 → 重试 → 超时 → 熔断。
    外层熔断先挡快速失败，内层重试扛瞬时抖动。
    """

    def __init__(self, agent, retries=2, timeout=None, breaker=None):
        self._inner = agent
        self.retries = retries
        self.timeout = timeout
        self.breaker = breaker

    def ask(self, text):
        def _call():
            if self.timeout:
                return with_timeout(lambda: self._inner.ask(text), self.timeout)
            return self._inner.ask(text)

        retried = lambda: retry_with_backoff(_call, retries=self.retries)
        if self.breaker is not None:
            return self.breaker.ask(retried)
        return retried()

    def history(self):
        return self._inner.history()

    def __getattr__(self, name):
        # 没定义的属性转发给内层（role / calls 等），演示打印照常可用
        return getattr(self._inner, name)

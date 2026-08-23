"""
异步编程专项演示：为什么异步 / 串行 vs 并发 / 保序 / 限流 / 依赖

核心矛盾：程序等网络（I/O）时 CPU 在干等。异步把"等待"叠起来。
完全离线：用 asyncio.sleep 模拟 API 延迟，不需要真 API、不花钱。
（--fake 保留是跟老 demo 习惯，这课全离线，带不带都一样）

五幕：
1. 串行 —— 3 个请求挨个等，总耗时相加
2. 并发 —— gather 同时等，总耗时 ≈ 最慢那个
3. 保序 —— 返回顺序 = 传入顺序
4. 限流 —— 并发太猛会打爆 API，用 Semaphore 限住
5. 依赖 —— 能并行的先并行，有依赖的必须等（实战套路）
"""
import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from async_utils import fake_call, run_serial, run_concurrent, run_limited


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true", help="保留参数：这课全离线，不需要真 API")
    args = parser.parse_args()

    # ---------- 第 1 幕 · 串行：3 个请求挨个等 ----------
    print("===== 第 1 幕 · 串行：3 个请求挨个等（总耗时相加） =====")
    calls = [fake_call("诊断", 0.5), fake_call("改写", 0.5), fake_call("面试", 0.5)]
    t = time.time()
    asyncio.run(run_serial(calls))
    print(f"  串行 3 个 0.5s 请求：耗时 {time.time() - t:.2f} 秒 → 约 1.5s（三个加起来）")
    print("  就像办事大厅一件一件排队：A 排完才轮 B。")

    # ---------- 第 2 幕 · 并发：3 个请求同时等 ----------
    print("\n===== 第 2 幕 · 并发：3 个请求同时等（gather） =====")
    calls = [fake_call("诊断", 0.5), fake_call("改写", 0.5), fake_call("面试", 0.5)]
    t = time.time()
    asyncio.run(run_concurrent(calls))
    print(f"  并发 3 个 0.5s 请求：耗时 {time.time() - t:.2f} 秒 → 约 0.5s（等待叠起来了）")
    print("  3 个号同时取，最慢那个 0.5s 完事就全部完事。")

    # ---------- 第 3 幕 · 保序 ----------
    print("\n===== 第 3 幕 · 保序：gather 返回顺序 = 传入顺序 =====")
    calls = [fake_call("先发", 0.2), fake_call("后发", 0.1), fake_call("最后", 0.05)]
    result = asyncio.run(run_concurrent(calls))
    print(f"  传入顺序：先发/后发/最后（耗时 0.2/0.1/0.05）")
    print(f"  返回顺序：{result}")
    print("  → 即使『最后』最快完成，返回还是按传入顺序排好——放心用索引取结果。")

    # ---------- 第 4 幕 · 限流 ----------
    print("\n===== 第 4 幕 · 限流：并发太猛会打爆 API（Semaphore 收费站） =====")
    calls = [fake_call(f"req{i}", 0.3) for i in range(8)]
    t = time.time()
    asyncio.run(run_limited(calls, max_concurrent=2))
    print(f"  8 个 0.3s 请求、限 2 并发：耗时 {time.time() - t:.2f} 秒 → 约 1.2s（4 批 × 0.3s）")
    print("  如果全放开 8 个同时飞，真实 API 会拒绝你（限流报错）——收费站帮你排队。")

    # ---------- 第 5 幕 · 依赖：能并行的先并行，有依赖的必须等 ----------
    print("\n===== 第 5 幕 · 依赖：能并行的先并行，有依赖的必须等 =====")
    print("  实战场景：Agent 回答前要先取两块资料（RAG 检索 + 用户资料），再生成正文。")
    print("  检索和资料互相独立 → 可并发；正文依赖它们 → 必须等两块都到。")

    async def 串行版():
        await fake_call("RAG 检索", 0.2)
        await fake_call("用户资料", 0.2)
        await fake_call("正文生成", 0.6)

    async def 优化版():
        await asyncio.gather(fake_call("RAG 检索", 0.2), fake_call("用户资料", 0.2))
        await fake_call("正文生成", 0.6)

    t = time.time()
    asyncio.run(串行版())
    s = time.time() - t
    t = time.time()
    asyncio.run(优化版())
    o = time.time() - t
    print(f"  串行版（检索→资料→正文）：{s:.2f} 秒")
    print(f"  优化版（检索+资料并发，再正文）：{o:.2f} 秒")
    print(f"  省了 {s - o:.2f} 秒 → 这就是『依赖关系』在异步里的规矩：没依赖的并发，有依赖的等。")

    print("\n  一句话收尾：异步不让你变快，只让『等待』不再互相等。")
    print("  面试答法：I/O 密集用异步叠等待；CPU 密集用多进程；有依赖的只能等。")


if __name__ == "__main__":
    main()

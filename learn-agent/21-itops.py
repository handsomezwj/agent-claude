"""
IT 运维安全护栏专项演示：只读诊断 + 破坏性命令拦截

业务场景：运维助手排查"服务为什么挂了"，但绝不执行破坏性操作。
完全离线：用 ops_demo/ 里的假服务和假日志，不需要真服务、不花一分钱。

四幕：
1. 命令护栏   —— 安全命令放行，破坏性命令（rm/kill/重启/重定向）一律拒绝
2. 查服务     —— check_service 读 pid 文件报三态（未知/停止/运行）
3. 查日志     —— 日志只能读白名单目录，../ 越权被拦；按 ERROR 过滤找故障现场
4. 完整剧本   —— 服务挂了 → 查状态 → 搜日志 ERROR/CRITICAL → 定位"连接池耗尽"
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ops_demo"))

from itops_guard import (  # noqa: E402
    guard_command,
    load_service_registry,
    check_service_status,
    read_log_safely,
)
import demo_service  # noqa: E402  (ops_demo/demo_service.py)

DATA_DIR = Path(__file__).resolve().parent / "ops_demo"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="演示数据目录（默认 ops_demo/）")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)

    # ---------- 第 1 幕 · 命令护栏 ----------
    print("===== 第 1 幕 · 命令护栏：安全放行，破坏性拦截 =====")
    for cmd in ["ls -la", "tail -n 20 app.log", "rm -rf /", "kill -9 123", "reboot", "cat a > b"]:
        ok, reason = guard_command(cmd)
        tag = "放行" if ok else f"拒绝（{reason}）"
        print(f"  {'✅' if ok else '🚫'} {cmd:22s} → {tag}")
    print("  → 只读命令放行；删/杀/重启/写文件一律拒绝，并把原因回显给模型。")

    # ---------- 第 2 幕 · 查服务 ----------
    print("\n===== 第 2 幕 · 查服务：三态判定（pid 文件在不在） =====")
    registry = load_service_registry(data_dir)
    demo_service.stop(data_dir, "order-api")  # 先停掉，模拟故障
    print(f"  stop 后：  {check_service_status('order-api', registry, data_dir)}")
    demo_service.start(data_dir, "order-api")
    print(f"  start 后：{check_service_status('order-api', registry, data_dir)}")
    print(f"  未知服务：{check_service_status('no-such-svc', registry, data_dir)}")
    demo_service.stop(data_dir, "order-api")

    # ---------- 第 3 幕 · 查日志（路径护栏 + 关键词） ----------
    print("\n===== 第 3 幕 · 查日志：路径护栏 + ERROR 过滤 =====")
    print(f"  🚫 想读 ../.env → {read_log_safely('../.env', data_dir)}")
    print("  --- 日志里的 ERROR 现场（带行号，最后 5 条） ---")
    print(read_log_safely("app.log", data_dir, keyword="ERROR", tail_lines=5))

    # ---------- 第 4 幕 · 完整剧本 ----------
    print("\n===== 第 4 幕 · 完整剧本：服务挂了怎么排查 =====")
    demo_service.stop(data_dir, "order-api")
    print("  用户：order-api 好像挂了，帮我排查一下为什么")
    print(f"  ① 查状态 → {check_service_status('order-api', registry, data_dir)}")
    err = read_log_safely("app.log", data_dir, keyword="CRITICAL", tail_lines=3)
    print(f"  ② 搜 CRITICAL →\n{err}")
    print("  ③ 诊断：日志证据显示数据库连接池耗尽（8 次 ERROR 后 CRITICAL 终止）")
    ok, reason = guard_command("rm -rf /data/order-api/logs")
    print(f"  ④ 用户让删日志 → {'拒绝' if not ok else '放行'}（{reason}）")
    print("     → 只读诊断，破坏性操作需人工确认后手动执行")

    print("\n  一句话收尾：Agent 越能干，越要敢说『不』。安全护栏 = 把能干框在该干里。")


if __name__ == "__main__":
    main()

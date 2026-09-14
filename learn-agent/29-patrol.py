"""
值班巡检专项演示：把一堆数字，变成一句结论

和 28-remote-ops.py 的区别：那一课解决"怎么把真主机的数字取回来"；
这一课解决"取回来之后，这些数字到底算好还是算坏"。
数字（负载 4.2、磁盘 92%）不是结论——**"这台机器有没有事"才是结论**。

默认离线：用假 SSH 演全套，不需要主机、不花钱、结果可复现。
想看真的：--real（要配好目标机，见 28-remote-ops.py 文件末尾）。

五幕：
1. 数字 ≠ 结论 —— 同一份 df，直接看会吓一跳，判完发现是虚惊
2. 健康主机    —— 一份"一切正常"的报告长什么样（结论先行）
3. 有病主机    —— 磁盘要满 / 内存见底 / 负载爆炸 / 服务崩了，逐条点名
4. 连不上      —— 没结论 ≠ 一切正常（这条最容易出事）
5. 尺子与门    —— 阈值是常量、清单要先过门（连探活都不做）
"""
import argparse
import os
import sys
from datetime import datetime

# --- Windows GBK 编码修复（同 agent-claude.py）：不然 ✅/⚠ 这类字符直接报错 ---
if sys.platform == "win32":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8",
                      errors="replace", buffering=1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from patrol import (  # noqa: E402
    DISK_CRIT_PCT, DISK_WARN_PCT, LOAD_PER_CORE_WARN, MEM_AVAIL_WARN_PCT,
    judge_disk, patrol_host, screen_units,
)
from remote_ops import FakeRunner, parse_df, read_df_rows, runner_from_env  # noqa: E402

# 真机抓的 df：drivers 那个 92% 是 **Windows 的 C 盘**，被 WSL 挂进来的，不是这台 Linux 的盘。
REAL_DF_WSL = (
    "Filesystem      Size  Used Avail Use% Mounted on\n"
    "none            3.4G     0  3.4G   0% /usr/lib/modules/6.18.33.2-microsoft-standard-WSL2\n"
    "none            3.4G  4.0K  3.4G   1% /mnt/wsl\n"
    "drivers         200G  182G   18G  92% /usr/lib/wsl/drivers\n"
    "tmpfs           3.4G     0  3.4G   0% /dev/shm\n"
    "/dev/sdd       1007G   12G  945G   2% /\n"
)

HEALTHY = {
    "systemctl is-active": "active\n",
    "systemctl is-enabled": "enabled\n",
    "systemctl show": "MainPID=201\nNRestarts=0\nLoadState=loaded\nSubState=running\n",
    "uptime": " 05:36:22 up 3 days,  4:12,  2 users,  load average: 0.42, 0.31, 0.28\n",
    "nproc": "8\n",
    "free -m": ("               total        used        free      shared  buff/cache   available\n"
                "Mem:            6858        2103        1204          11        3551        4488\n"
                "Swap:           2048           0        2048\n"),
    "df -h": REAL_DF_WSL,
}

SICK = {
    "systemctl is-active": "failed\n",
    "systemctl is-enabled": "disabled\n",
    "systemctl show": "MainPID=0\nNRestarts=12\nLoadState=loaded\nSubState=failed\n",
    "uptime": " 10:00:00 up 12 days,  2 users,  load average: 8.50, 7.20, 6.10\n",
    "nproc": "2\n",
    "free -m": ("               total        used        free      shared  buff/cache   available\n"
                "Mem:            4000        3900          20           0           80         100\n"
                "Swap:           2048        1800         248\n"),
    "df -h": ("Filesystem      Size  Used Avail Use% Mounted on\n"
              "/dev/sda1       200G  192G     8G  96% /\n"),
}

FIXED_NOW = datetime(2026, 9, 14, 9, 30, 0)     # 演示里写死时间，结果可复现


def act1_numbers_are_not_verdicts():
    print("===== 第 1 幕 · 数字 ≠ 结论：同一份 df，两种看法 =====")
    print("  直接看（parse_df，28 课那个）：")
    print(f"    {parse_df(REAL_DF_WSL)}")
    print("  ↑ 报出来是 92%，看着这台机器磁盘要满了——**但 92% 那是 Windows 的 C 盘**。")
    print("\n  判一下（judge_disk，这一课）：")
    findings, skipped = judge_disk(read_df_rows(REAL_DF_WSL))
    for f in findings:
        print(f"    [{f.level}] {f.item}：{f.detail}")
    print(f"    跳过的 {len(skipped)} 个不属于这台机器的挂载点：{'、'.join(skipped)}")
    print("  ↑ 这台 Linux 自己的盘只用 2%，一切正常。**差的就是「判」这一步。**")
    print("  → 坑在这里：WSL 能看到 Windows 的盘，容器能看到宿主机盘，")
    print("     snap 的只读镜像天生 100%。把别人的盘算成自己的，就是天天误报的根源。")
    print("  → 但跳过了要**明着写出来**：不能让人以为你全看过了（报告的诚实底线）。")


def act2_healthy(runner, units):
    print("\n===== 第 2 幕 · 健康主机：报告长什么样 =====")
    print(patrol_host(units, runner, now=FIXED_NOW))
    print("\n  → 注意第一行下面就是【结论】——看报告的人只想知道「有没有事」，")
    print("    细节是给要深挖的人看的。健康项合成一行，别刷屏。")


def act3_sick(runner):
    print("\n===== 第 3 幕 · 有病主机：逐条点名 =====")
    print(patrol_host("nginx", runner, now=FIXED_NOW))
    print("\n  → 四件事全是「判」出来的，不是「报」出来的：")
    print(f"    · 磁盘 96% ≥ {DISK_CRIT_PCT}% → 严重（过 {DISK_WARN_PCT}% 就该警告了）")
    print(f"    · 每核负载 4.25 ≥ {LOAD_PER_CORE_WARN} → 活儿排了几倍队")
    print(f"    · 可用内存只剩 2.5% ≤ {MEM_AVAIL_WARN_PCT}% → 随时 OOM；swap 都用了 88%")
    print("    · 服务 failed，重启过 12 次——反复崩，systemd 拉不起来")


def act4_unreachable():
    print("\n===== 第 4 幕 · 连不上：没结论 ≠ 一切正常 =====")
    print(patrol_host("ssh", FakeRunner(HEALTHY, reachable=False), now=FIXED_NOW))
    print("\n  → 这条最容易出大事：巡检脚本连不上机器，如果还算成「通过」，")
    print("    那台机器就永远没人管了。**取不到数，就必须说「没结论」。**")


def act5_ruler_and_door():
    print("\n===== 第 5 幕 · 尺子与门 =====")
    print("  尺子（阈值）是常量，能被看见、能被改、能被测：")
    print(f"    磁盘警告 {DISK_WARN_PCT}%  磁盘严重 {DISK_CRIT_PCT}%  "
          f"内存可用警告 {MEM_AVAIL_WARN_PCT}%  每核负载警告 {LOAD_PER_CORE_WARN}")
    print("\n  门：清单在**解析之前**先整体过一道，出现注入原料整条拒、连探活都不做。")
    for text in ["ssh,nginx", "ssh; rm -rf /", "ssh | cat /etc/passwd"]:
        ok, reason = screen_units(text)
        print(f"    {'✅' if ok else '🚫'} {text:24s} → {'放行' if ok else reason}")
    runner = FakeRunner(HEALTHY)
    patrol_host("ssh; rm -rf /", runner, now=FIXED_NOW)
    print(f"    → 被拒之后，真的发给主机的命令条数：{len(runner.calls)} 条")
    print("\n  一句话收尾：**取数靠门，判断靠尺子；")
    print("  数字谁都会读，能下对结论的人才是运维。**")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true",
                        help="连真主机（需配 CLAUDE_OPS_SSH_HOST 等环境变量）；默认离线演示")
    args = parser.parse_args()

    runner = runner_from_env() if args.real else FakeRunner(HEALTHY)
    if args.real and runner is None:
        print("没配远端主机（CLAUDE_OPS_SSH_HOST 为空），退回离线演示。配法见 28-remote-ops.py 末尾。\n")
        runner = FakeRunner(HEALTHY)
    elif args.real:
        print(f"真主机模式：{runner.user}@{runner.host}:{runner.port}（巡检清单用环境变量 "
              f"CLAUDE_OPS_PATROL_UNITS 配）\n")
    else:
        print("离线模式（假 SSH，结果可复现）。想看真的加 --real。\n")

    # 巡检清单跟主程序同一个环境变量（--real 时才有意义；离线演示默认就是 ssh）
    units = os.environ.get("CLAUDE_OPS_PATROL_UNITS", "ssh").strip() or "ssh"

    act1_numbers_are_not_verdicts()
    act2_healthy(runner, units)
    act3_sick(FakeRunner(SICK))
    act4_unreachable()
    act5_ruler_and_door()


if __name__ == "__main__":
    main()

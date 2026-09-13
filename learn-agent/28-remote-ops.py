"""
真主机只读巡检专项演示：走 SSH 去真 Linux 上做诊断，三道门拦住乱来

和 21-itops.py 的区别：那课查的是 ops_demo 里的假服务/假日志；这一课连真主机，
拿到的是真 systemd 状态和真 journal 日志——真环境会有"机器睡了"这种意外。

默认离线：用假 SSH（剧本回话）演全套，不需要任何主机、不花一分钱、结果可复现。
想看真的：--real（要配好目标机，见文件末尾说明）。

六幕：
1. 三道门   —— 参数白名单 / 远端命令白名单：合法只读放行，注入原料一律拒
2. 查服务   —— 真 systemd 三件事：活没活、开机自启没、重启过几次
3. 查日志   —— journalctl 拉回来在本地筛关键词（绝不在远端拼管道）
4. 机器体检 —— 系统 / 负载 / 内存 / 磁盘（按使用率倒序）/ 最吃 CPU 的进程
5. 主机睡了 —— 连不上先唤一次；唤不醒就给人话，不抛异常
6. 造什么过什么 —— 我们造的命令必须自己过得了自己的门（不然等于门写错了）
"""
import argparse
import os
import sys
from pathlib import Path

# --- Windows GBK 编码修复（同 agent-claude.py）：不然 ✅/🚫 这类字符直接报错 ---
if sys.platform == "win32":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8",
                      errors="replace", buffering=1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from remote_ops import (  # noqa: E402
    FakeRunner,
    build_health_cmds,
    build_log_cmd,
    build_service_cmds,
    remote_health,
    remote_logs,
    remote_service,
    runner_from_env,
    safe_unit,
    screen_remote_cmd,
)

# 假 SSH 的剧本：键是命令前缀，值是"远端会回什么"。样本照真机抄的。
FAKE_SCRIPT = {
    "systemctl is-active": "active\n",
    "systemctl is-enabled": "enabled\n",
    "systemctl show": (
        "MainPID=201\nNRestarts=0\nLoadState=loaded\nSubState=running\n"
        "ActiveEnterTimestamp=Mon 2026-09-14 05:36:18 CST\n"
    ),
    "journalctl -u": (
        "Sep 14 05:36:18 dev-host systemd[1]: Started ssh.service - OpenBSD Secure Shell server.\n"
        "Sep 14 05:36:19 dev-host sshd[300]: Server listening on 0.0.0.0 port 22.\n"
        "Sep 14 05:36:21 dev-host sshd[412]: error: kex_exchange_identification: Connection closed\n"
        "Sep 14 05:36:22 dev-host sshd[412]: Failed password for invalid user admin from 10.0.0.7\n"
        "Sep 14 05:36:23 dev-host sshd[412]: Connection closed by authenticating user root\n"
    ),
    "cat /etc/os-release": 'PRETTY_NAME="Ubuntu 24.04 LTS"\nNAME="Ubuntu"\n',
    "uptime": " 05:36:22 up 3 days,  4:12,  2 users,  load average: 0.42, 0.31, 0.28\n",
    "free -m": (
        "               total        used        free      shared  buff/cache   available\n"
        "Mem:            6858        2103        1204          11        3551        4488\n"
        "Swap:           2048          18        2030\n"
    ),
    "df -h": (
        "Filesystem      Size  Used Avail Use% Mounted on\n"
        "/dev/sda1       200G  182G   18G  92% /\n"
        "/dev/sda2        98G   32G   66G  33% /data\n"
        "/dev/sdb1       1.0T  120G  880G  12% /backup\n"
    ),
    "ps -eo": (
        "    PID %CPU %MEM     ELAPSED COMMAND\n"
        "    831 24.7  6.2    02:14:03 python3\n"
        "    201  3.4  0.5    03:11:40 cron\n"
        "      1  1.2  0.1    03:12:05 systemd\n"
    ),
}


def act1_doors():
    print("===== 第 1 幕 · 三道门：合法的放行，想乱来的拒 =====")
    print("  -- 第一道：服务名参数（正则白名单） --")
    for unit in ["cron", "ssh.service", "getty@tty1.service", "--help", "ssh; rm -rf /"]:
        ok, reason = safe_unit(unit)
        print(f"  {'✅' if ok else '🚫'} {unit:22s} → {'合法' if ok else reason}")
    print("  -- 第二道：远端命令（固定前缀白名单 + 禁止注入原料） --")
    for cmd in ["systemctl is-active cron", "uptime", "df -h",
                "systemctl is-active cron; rm -rf /", "journalctl -u ssh | cat /etc/passwd",
                "uptime `whoami`", "journalctl -u ssh > /etc/passwd", "ls -la"]:
        ok, reason = screen_remote_cmd(cmd)
        print(f"  {'✅' if ok else '🚫'} {cmd:38s} → {'放行' if ok else '拒'}")
    print("  → 黑名单挡『想得到的坏写法』，白名单挡『想不到的坏写法』：")
    print("    没见过的命令不管好坏一律不认——ls 也被拒，因为它不在白名单里。")


def act2_service(runner):
    print("\n===== 第 2 幕 · 查服务：真 systemd 三件事 =====")
    print(remote_service("ssh.service", runner))
    print("  → 光看『运行中』不够：还看开机自启（enabled）和重启次数（反复崩会露馅）。")


def act3_logs(runner):
    print("\n===== 第 3 幕 · 查日志：journalctl 拉回来，本地筛关键词 =====")
    print(remote_logs("ssh.service", keyword="Failed password", tail_lines=10, runner=runner))
    print("  → 远端命令里绝不拼管道：整段拉回本地再筛，注入面就小得多。")
    print("  → 拉回多少行有上限（500），防止一次把上下文撑爆。")


def act4_health(runner):
    print("\n===== 第 4 幕 · 机器体检：一眼看全局 =====")
    print(remote_health(runner))
    print("  → 磁盘按使用率倒序（最该先看的排最前）；网络不通就往这一看。")


def act5_sleeping(runner_none, dead):
    print("\n===== 第 5 幕 · 主机睡了：唤一次，唤不醒就给人话 =====")
    print(f"  没配主机时： {remote_service('cron', runner_none)}")
    print(f"  配了但连不上：{remote_service('cron', dead)}")
    print("  → 真环境最常见的故障就是『下游会挂』：连不上要返回一句能读懂的话，")
    print("    而不是把异常抛出去炸掉整个 Agent 循环。")


def act6_selfcheck():
    print("\n===== 第 6 幕 · 自洽检查：造的命令必须过得了自己的门 =====")
    all_cmds = list(build_service_cmds("cron").values()) + [build_log_cmd("ssh")]
    all_cmds += list(build_health_cmds().values())
    bad = [c for c in all_cmds if not screen_remote_cmd(c)[0]]
    for cmd in all_cmds:
        print(f"  ✅ {cmd}")
    print(f"  → 共 {len(all_cmds)} 条自造命令，过不了门的：{len(bad)} 条"
          f"{'（门写错了）' if bad else '（门是对的）'}")
    print("\n  一句话收尾：给 Agent 一台真机器，先给它三道门；")
    print("  能查的多，能改的零——这才是敢让人用的运维助手。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true",
                        help="连真主机（需配 CLAUDE_OPS_SSH_HOST 等环境变量）；默认用假 SSH 离线演示")
    args = parser.parse_args()

    runner = runner_from_env() if args.real else FakeRunner(FAKE_SCRIPT)
    if args.real and runner is None:
        print("没配远端主机（CLAUDE_OPS_SSH_HOST 为空），退回离线假 SSH 演示。")
        print("配法见本文件末尾注释。\n")
        runner = FakeRunner(FAKE_SCRIPT)
    elif args.real:
        print(f"真主机模式：{runner.user}@{runner.host}:{runner.port}\n")
    else:
        print("离线模式（假 SSH 剧本，结果可复现）。想看真的加 --real。\n")

    act1_doors()
    act2_service(runner)
    act3_logs(runner)
    act4_health(runner)
    act5_sleeping(None, FakeRunner(FAKE_SCRIPT, reachable=False))
    act6_selfcheck()


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# 接真主机怎么配（以本机 WSL Ubuntu-24.04 当靶机为例，最小权限：只认密钥）
#
#   # 1. WSL 里装 sshd、只允许密钥登录
#   wsl.exe -d Ubuntu-24.04 -u root -- apt-get install -y openssh-server
#   wsl.exe -d Ubuntu-24.04 -u root -- systemctl enable --now ssh
#
#   # 2. 本机公钥放进靶机的 authorized_keys（Windows 侧生成：ssh-keygen -t ed25519）
#   #    /root/.ssh/authorized_keys 写入 ~/.ssh/id_ed25519.pub 的内容
#
#   # 3. 告诉 agent 靶机在哪
#   export CLAUDE_OPS_SSH_HOST=localhost
#   export CLAUDE_OPS_SSH_USER=root
#   export CLAUDE_OPS_SSH_KEY="~/.ssh/id_ed25519"      # Windows 写 %USERPROFILE%\.ssh\id_ed25519
#   # WSL 空闲会被回收（distro 变 Stopped、22 端口消失），配一条唤醒命令兜底：
#   export CLAUDE_OPS_SSH_WAKE="wsl.exe -d Ubuntu-24.04 -u root -- true"
#
#   python 28-remote-ops.py --real
# ---------------------------------------------------------------------------

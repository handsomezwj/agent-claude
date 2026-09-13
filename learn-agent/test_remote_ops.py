# test_remote_ops.py — 真主机只读巡检的测试（零网络，全离线）
#
# 覆盖四件事：
#   1. 门：远端白名单（screen_remote_cmd）和参数白名单（safe_unit）拦得住注入
#   2. 造：我们造出来的命令，自己必须过得了自己的门（一致性——不然等于门写错了）
#   3. 解：systemctl / journalctl / uptime / free / df / ps 的输出解析（样本是真机抓的）
#   4. 串：三个对外查询端到端跑通（用 FakeRunner 假 ssh，不碰网络）
#
# 跑法（跟全套一起）：
#   cd learn-agent && python -m unittest discover -p "test_*.py"
import unittest

from remote_ops import (
    FakeRunner,
    build_health_cmds,
    build_log_cmd,
    build_service_cmds,
    format_log_window,
    parse_df,
    parse_free,
    parse_is_active,
    parse_show,
    parse_top_procs,
    parse_uptime,
    remote_health,
    remote_logs,
    remote_service,
    safe_unit,
    screen_remote_cmd,
)

# ---- 真机抓下来的样本（Ubuntu 24.04 / WSL2，systemd 在跑） ----
REAL_IS_ACTIVE = "active\n"
REAL_IS_ENABLED = "enabled\n"
REAL_SHOW = (
    "MainPID=201\n"
    "NRestarts=0\n"
    "LoadState=loaded\n"
    "SubState=running\n"
    "ActiveEnterTimestamp=Mon 2026-09-14 05:36:18 CST\n"
)
REAL_UPTIME = " 05:36:22 up 0 min,  2 users,  load average: 0.00, 0.00, 0.00\n"
REAL_FREE = (
    "               total        used        free      shared  buff/cache   available\n"
    "Mem:            6858         570        4697           3        1747        6288\n"
    "Swap:           2048           0        2048\n"
)
REAL_DF = (
    "Filesystem      Size  Used Avail Use% Mounted on\n"
    "none            3.4G     0  3.4G   0% /usr/lib/modules/6.18.33.2-microsoft-standard-WSL2\n"
    "none            3.4G  4.0K  3.4G   1% /mnt/wsl\n"
    "drivers         200G  182G   18G  92% /usr/lib/wsl/drivers\n"
)
REAL_PS = (
    "    PID %CPU %MEM     ELAPSED COMMAND\n"
    "      1  7.3  0.1       00:06 systemd\n"
    "    208  3.4  0.5       00:04 snapd\n"
    "    139  2.5  0.0       00:05 (udev-worker)\n"
)
REAL_JOURNAL = (
    "Sep 14 05:36:18 DESKTOP-LC9P25O systemd[1]: Started cron.service - Regular background program processing daemon.\n"
    "Sep 14 05:36:19 DESKTOP-LC9P25O cron[201]: (CRON) INFO (pidfile fd = 3)\n"
    "Sep 14 05:36:20 DESKTOP-LC9P25O systemd[1]: ssh.service: Deactivated successfully.\n"
    "Sep 14 05:36:21 DESKTOP-LC9P25O sshd[300]: error: kex_exchange_identification: Connection closed\n"
    "Sep 14 05:36:22 DESKTOP-LC9P25O sshd[300]: Failed password for root\n"
)


class RemoteDoorTest(unittest.TestCase):
    """第三道门：远端白名单。只认"单条、只读、在白名单里"的命令。"""

    def test_allows_whitelisted_readonly_commands(self):
        for cmd in ("systemctl is-active cron", "journalctl -u ssh -n 20 --no-pager",
                    "uptime", "free -m", "df -h", "cat /etc/os-release",
                    "ps -eo pid,pcpu,comm --sort=-pcpu"):
            ok, reason = screen_remote_cmd(cmd)
            self.assertTrue(ok, f"{cmd} 应放行，却被拦：{reason}")

    def test_blocks_anything_outside_whitelist(self):
        """白名单的狠处：没见过的命令，不管好坏，一律不认。"""
        for cmd in ("ls -la", "whoami", "cat /etc/shadow", "curl http://x",
                    "python3 -c 'print(1)'", "systemctl start ssh"):
            ok, _ = screen_remote_cmd(cmd)
            self.assertFalse(ok, f"{cmd} 不该放行")

    def test_blocks_shell_metacharacters(self):
        """拼接注入的原料：分号/管道/与号/变量/反引号/重定向/换行——合法只读命令一个都不需要。"""
        for cmd in ("systemctl is-active cron; rm -rf /",
                    "systemctl is-active cron | cat /etc/passwd",
                    "uptime && reboot",
                    "uptime $HOME",
                    "uptime `whoami`",
                    "journalctl -u ssh > /etc/passwd",
                    "uptime < /etc/shadow",
                    "systemctl is-active cron\nrm -rf /"):
            ok, _ = screen_remote_cmd(cmd)
            self.assertFalse(ok, f"{cmd!r} 不该放行（含注入原料）")

    def test_blocks_empty_and_non_string(self):
        for bad in ("", "   ", None, 123):
            ok, _ = screen_remote_cmd(bad)
            self.assertFalse(ok)

    def test_unit_name_whitelist(self):
        for good in ("cron", "ssh.service", "systemd-journald", "getty@tty1.service",
                     "snapd.seeded.service"):
            ok, _ = safe_unit(good)
            self.assertTrue(ok, f"{good} 应是合法服务名")
        for bad in ("--help", "-p", "ssh; rm -rf /", "ssh /etc/passwd", "a b", "", None,
                    "x" * 65):
            ok, _ = safe_unit(bad)
            self.assertFalse(ok, f"{bad!r} 不该通过服务名校验")


class CommandShapeTest(unittest.TestCase):
    """造命令的规矩：我们造出来的每一条，自己都必须过得了自己的门。"""

    def test_service_cmds_pass_own_door(self):
        for cmd in build_service_cmds("cron").values():
            ok, reason = screen_remote_cmd(cmd)
            self.assertTrue(ok, f"自己造的命令过不了自己的门：{cmd}（{reason}）")

    def test_log_cmd_passes_own_door_and_clamps_lines(self):
        cmd = build_log_cmd("ssh", fetch_lines=99999)
        ok, _ = screen_remote_cmd(cmd)
        self.assertTrue(ok)
        self.assertIn("-n 500", cmd)          # 钳到上限，防一次拉爆上下文
        self.assertNotIn("|", cmd)            # 绝不在远端拼管道

    def test_health_cmds_pass_own_door(self):
        for cmd in build_health_cmds().values():
            ok, reason = screen_remote_cmd(cmd)
            self.assertTrue(ok, f"自己造的命令过不了自己的门：{cmd}（{reason}）")


class ParseTest(unittest.TestCase):
    """解析：样本全是从真机抓的，不是编的。"""

    def test_parse_is_active_maps_to_chinese(self):
        self.assertIn("运行中", parse_is_active(REAL_IS_ACTIVE))
        self.assertIn("停止", parse_is_active("inactive\n"))
        self.assertIn("崩溃", parse_is_active("failed\n"))
        self.assertIn("未知", parse_is_active(""))
        self.assertIn("未知", parse_is_active("weird-state\n"))

    def test_parse_show_reads_key_values(self):
        info = parse_show(REAL_SHOW)
        self.assertEqual(info["MainPID"], "201")
        self.assertEqual(info["LoadState"], "loaded")
        self.assertEqual(info["NRestarts"], "0")

    def test_parse_uptime(self):
        text = parse_uptime(REAL_UPTIME)
        self.assertIn("已运行", text)
        self.assertIn("负载", text)
        self.assertIn("0.00", text)

    def test_parse_free(self):
        text = parse_free(REAL_FREE)
        self.assertIn("6858", text)           # 总量
        self.assertIn("6288", text)           # available（有就报可用，不报 free）
        self.assertIn("可用", text)

    def test_parse_df_picks_fullest_mount(self):
        text = parse_df(REAL_DF)
        self.assertIn("92%", text)            # 最满的排最前
        self.assertLess(text.find("92%"), text.find("1%"))

    def test_parse_top_procs(self):
        text = parse_top_procs(REAL_PS)
        self.assertIn("systemd", text)
        self.assertIn("7.3", text)

    def test_format_log_window_filters_and_numbers(self):
        text = format_log_window(REAL_JOURNAL, keyword="sshd")
        self.assertIn("命中", text)
        self.assertIn("kex_exchange_identification", text)
        self.assertNotIn("Started cron.service", text)   # 没命中的行不该出现
        self.assertIn("4:", text)                        # 标的是本窗口内的行号（ssh 那两条在第 4、5 行）

    def test_format_log_window_keyword_miss(self):
        self.assertIn("没找到", format_log_window(REAL_JOURNAL, keyword="OutOfMemory"))

    def test_format_log_window_tail_and_clamp(self):
        text = format_log_window(REAL_JOURNAL, tail_lines=2)
        self.assertIn("Failed password", text)           # 尾部两行之一
        self.assertNotIn("Started cron.service", text)   # 头部的行被截掉
        self.assertIn("最后 2 行", text)


class EndToEndWithFakeSshTest(unittest.TestCase):
    """串起来：真主机查询走假 ssh（不碰网络）。假 ssh 也过白名单——护栏自己也要被测。"""

    def _runner(self, **kw):
        return FakeRunner({
            "systemctl is-active": REAL_IS_ACTIVE,
            "systemctl is-enabled": REAL_IS_ENABLED,
            "systemctl show": REAL_SHOW,
            "journalctl -u": REAL_JOURNAL,
            "cat /etc/os-release": 'PRETTY_NAME="Ubuntu 24.04 LTS"\nNAME="Ubuntu"\n',
            "uptime": REAL_UPTIME,
            "free -m": REAL_FREE,
            "df -h": REAL_DF,
            "ps -eo": REAL_PS,
        }, **kw)

    def test_remote_service_reports_real_facts(self):
        text = remote_service("cron", self._runner())
        self.assertIn("运行中", text)
        self.assertIn("201", text)            # 真 pid
        self.assertIn("enabled", text)        # 开机自启
        self.assertIn("CST", text)            # 进入该状态的时间

    def test_remote_service_warns_on_restart_loop(self):
        """重启次数 > 0 要主动告警——进程反复崩，光看"运行中"会漏。"""
        runner = FakeRunner({
            "systemctl is-active": "active\n",
            "systemctl is-enabled": "enabled\n",
            "systemctl show": "MainPID=42\nNRestarts=7\nLoadState=loaded\nSubState=running\n",
        })
        text = remote_service("nginx", runner)
        self.assertIn("重启过 7 次", text)
        self.assertIn("⚠", text)

    def test_remote_service_rejects_bad_unit_name(self):
        runner = self._runner()
        text = remote_service("cron; rm -rf /", runner)
        self.assertIn("不合法", text)
        self.assertEqual(runner.calls, [])    # 根本没往远端发

    def test_remote_logs_filters_by_keyword(self):
        text = remote_logs("ssh", keyword="Failed password", runner=self._runner())
        self.assertIn("Failed password", text)
        self.assertIn("命中", text)

    def test_remote_health_summarizes_all(self):
        text = remote_health(self._runner())
        self.assertIn("Ubuntu 24.04", text)
        self.assertIn("内存", text)
        self.assertIn("磁盘", text)
        self.assertIn("CPU", text)

    def test_unreachable_host_reports_clearly(self):
        """下游会挂（WSL 空闲就被回收）：连不上要给人话，不是堆栈。"""
        text = remote_service("cron", self._runner(reachable=False))
        self.assertIn("不可达", text)
        text = remote_logs("ssh", runner=self._runner(reachable=False))
        self.assertIn("不可达", text)
        text = remote_health(self._runner(reachable=False))
        self.assertIn("不可达", text)

    def test_no_host_configured_says_so(self):
        """没配远端主机 = 只有本地演示数据，要明说，别装作查到了。"""
        for text in (remote_service("cron", None), remote_logs("ssh", runner=None),
                     remote_health(None)):
            self.assertIn("没配远端主机", text)

    def test_fake_runner_enforces_door_itself(self):
        """假 runner 也过门：说明"拦"是门在拦，不是查表查不到。"""
        runner = self._runner()
        rc, out = runner.run("cat /etc/shadow")
        self.assertEqual(rc, 255)
        self.assertIn("远端护栏", out)

    def test_fake_runner_records_calls_for_assertions(self):
        runner = self._runner()
        remote_service("cron", runner)
        self.assertEqual(len(runner.calls), 3)          # 三条查询各问一次
        self.assertTrue(all(c.startswith(("systemctl", "journalctl", "uptime", "free",
                                          "df", "ps", "cat")) for c in runner.calls))


class SshRunnerUnitTest(unittest.TestCase):
    """SSH 命令行怎么拼（不真连，只看参数）。"""

    def test_probe_wakes_host_then_gives_up_gracefully(self):
        """主机睡着时（WSL 空闲就被回收）：唤一次，还不通就老实返回 False，绝不抛异常。

        靶机是真的连不上（127.0.0.1:1 没人听），但唤醒命令是真的会跑——留印记证明跑过。
        """
        import sys
        import tempfile
        from pathlib import Path

        from remote_ops import SshRunner
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "woke.txt"
            runner = SshRunner(host="127.0.0.1", port=1, timeout=1,
                               wake_cmd=f'"{sys.executable}" -c "open(r\'{marker}\',\'w\').close()"')
            self.assertFalse(runner.probe())        # 唤了也还是连不上 → False
            self.assertTrue(marker.exists())        # 但唤醒命令确实执行过

    def test_probe_without_wake_cmd_does_not_wake(self):
        from remote_ops import SshRunner
        runner = SshRunner(host="127.0.0.1", port=1, timeout=1, wake_cmd="")
        self.assertFalse(runner.probe())

    def test_undecodable_remote_bytes_do_not_leak_surrogates(self):
        """远端回来的字节解不成 UTF-8 时，绝不能让"孤立代理字符"漏到下游。

        真机上踩过：Windows 按本地码页解码远端 UTF-8，解不出的字节变成 \\udcxx，
        往下传给裁判护栏直接炸（surrogates not allowed）。这里让一个真子进程吐
        非法字节，验证解码这一层兜得住。
        """
        import sys
        from remote_ops import SshRunner

        class _BadBytesRunner(SshRunner):
            def _ssh_argv(self, cmd):            # 冒充 ssh：换成"吐非法字节"的本机命令
                return [sys.executable, "-c",
                        r"import sys; sys.stdout.buffer.write(b'\xff\xfe bad \x80\n')"]

        rc, out = _BadBytesRunner(host="x", timeout=5).run("uptime")
        self.assertEqual(rc, 0)
        self.assertIn("bad", out)                # 好字节照常读出来
        self.assertFalse(any(0xD800 <= ord(ch) <= 0xDFFF for ch in out))  # 没有代理字符
        out.encode("utf-8")                      # 能编码 = 下游不会炸


    def test_ssh_argv_has_safety_options(self):
        from pathlib import Path as _P

        from remote_ops import SshRunner
        r = SshRunner(host="10.0.0.9", user="ops", key="/tmp/k", port=2222)
        argv = r._ssh_argv("uptime")
        joined = " ".join(argv)
        self.assertIn("BatchMode=yes", joined)                     # 不弹密码
        self.assertIn("StrictHostKeyChecking=accept-new", joined)  # 记指纹
        self.assertIn("IdentitiesOnly=yes", joined)                # 只用指定密钥，别乱试
        self.assertIn("ops@10.0.0.9", joined)
        # 私钥路径会被 Path 规范化（Windows 上 / 变 \），所以比规范化后的值
        self.assertIn(f"-i {_P('/tmp/k')}", joined)
        self.assertEqual(argv[-1], "uptime")                       # 远端命令是独立一个参数

    def test_key_path_expands_tilde(self):
        """环境变量里写 ~/.ssh/id_ed25519 是自然写法，但 ssh 不认波浪号（那是 shell 的活），
        必须由我们展开——不然报 no such identity，还以为是自己密钥配错了。"""
        from pathlib import Path

        from remote_ops import SshRunner
        r = SshRunner(host="h", key="~/.ssh/id_ed25519")
        self.assertNotIn("~", r.key)
        self.assertEqual(r.key, str(Path.home() / ".ssh" / "id_ed25519"))

    def test_runner_from_env_off_by_default(self):
        import os
        from remote_ops import runner_from_env
        old = os.environ.pop("CLAUDE_OPS_SSH_HOST", None)
        try:
            self.assertIsNone(runner_from_env())     # 没配 = 不启用，行为跟以前完全一样
        finally:
            if old is not None:
                os.environ["CLAUDE_OPS_SSH_HOST"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)

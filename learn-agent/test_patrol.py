# test_patrol.py — 值班巡检的测试（零网络，全离线）
#
# 覆盖五块：
#   1. 判：每个 judge_* 纯函数的四档结论（正常/提示/警告/严重）和阈值边界
#   2. 坑：三个最容易判错的地方——负载除核数、内存看 available、别人的盘不算
#   3. 报：报告结论先行、严重的排前面、跳过的盘要明写出来
#   4. 串：一次完整巡检用假 SSH 跑通（健康机器 / 有病机器 / 连不上）
#   5. 门：巡检取数也得过 remote_ops 那三道门，服务名注入进不去
#
# 跑法（跟全套一起）：
#   cd learn-agent && python -m unittest discover -p "test_*.py"
import unittest
from datetime import datetime

from patrol import (
    DISK_CRIT_PCT,
    DISK_WARN_PCT,
    LEVEL_CRIT,
    LEVEL_INFO,
    LEVEL_OK,
    LEVEL_WARN,
    MEM_AVAIL_CRIT_PCT,
    Finding,
    build_report,
    judge_disk,
    judge_load,
    judge_memory,
    judge_service,
    parse_units,
    patrol_host,
    screen_units,
)
from remote_ops import FakeRunner, read_df_rows, read_load, read_mem, screen_remote_cmd

# ---- 真机抓下来的样本（Ubuntu 24.04 / WSL2） ----
# 注意这份 df：drivers 那个 92% 是 **Windows 的 C 盘**，被 WSL 挂进来的，
# 不是这台 Linux 自己的盘。新手最容易在这儿误报——本套测试专门盯这个。
REAL_DF_WSL = (
    "Filesystem      Size  Used Avail Use% Mounted on\n"
    "none            3.4G     0  3.4G   0% /usr/lib/modules/6.18.33.2-microsoft-standard-WSL2\n"
    "none            3.4G  4.0K  3.4G   1% /mnt/wsl\n"
    "drivers         200G  182G   18G  92% /usr/lib/wsl/drivers\n"
    "tmpfs           3.4G     0  3.4G   0% /dev/shm\n"
    "/dev/sdd       1007G   12G  945G   2% /\n"
)
REAL_UPTIME = " 05:36:22 up 3 days,  4:12,  2 users,  load average: 0.42, 0.31, 0.28\n"
REAL_FREE = (
    "               total        used        free      shared  buff/cache   available\n"
    "Mem:            6858        2103        1204          11        3551        4488\n"
    "Swap:           2048           0        2048\n"
)
REAL_SHOW_OK = "MainPID=201\nNRestarts=0\nLoadState=loaded\nSubState=running\n"


def _ts():
    return datetime(2026, 9, 14, 9, 30, 0)


# ---------------------- ① 清单解析 ----------------------

class ParseUnitsTest(unittest.TestCase):
    def test_splits_on_commas_spaces_newlines(self):
        self.assertEqual(parse_units("ssh,nginx cron\nredis"), ["ssh", "nginx", "cron", "redis"])

    def test_accepts_chinese_comma(self):
        self.assertEqual(parse_units("ssh，nginx"), ["ssh", "nginx"])

    def test_dedupes_and_keeps_order(self):
        self.assertEqual(parse_units("ssh nginx ssh"), ["ssh", "nginx"])

    def test_accepts_list_and_handles_junk(self):
        self.assertEqual(parse_units(["ssh", "", "  ", "nginx"]), ["ssh", "nginx"])
        self.assertEqual(parse_units(None), [])
        self.assertEqual(parse_units("   "), [])


# ---------------------- ② 磁盘：三个坑里最狠的一个 ----------------------

class DiskTest(unittest.TestCase):
    def test_windows_drive_is_not_counted_as_our_disk(self):
        """WSL 里的 92% 是 Windows 的盘——不该判成"这台机器磁盘快满了"。"""
        findings, skipped = judge_disk(read_df_rows(REAL_DF_WSL))
        self.assertEqual([f.level for f in findings], [LEVEL_OK])     # 只有一条"正常"
        self.assertIn("2%", findings[0].detail)                       # 说的是真·根分区
        self.assertNotIn("92", findings[0].detail)                    # 92% 不该出现在结论里
        self.assertEqual(len(skipped), 4)      # none×2 + drivers + tmpfs，四条全不是本机的盘
        self.assertTrue(any("drivers" in s for s in skipped))

    def test_tmpfs_and_loop_mounts_are_skipped(self):
        df = ("Filesystem      Size  Used Avail Use% Mounted on\n"
              "tmpfs           1.6G     0  1.6G   0% /run\n"
              "/dev/loop3      128M  128M     0 100% /snap/core/1\n"
              "/dev/sda1        50G   10G   38G  21% /\n")
        findings, skipped = judge_disk(read_df_rows(df))
        self.assertEqual([f.level for f in findings], [LEVEL_OK])
        self.assertEqual(len(skipped), 2)                 # 100% 的 snap 镜像不该报警

    def test_warn_and_crit_thresholds_and_boundaries(self):
        def one(pct):
            df = ("Filesystem      Size  Used Avail Use% Mounted on\n"
                  f"/dev/sda1       100G   {pct}G   {100 - pct}G  {pct}% /\n")
            return judge_disk(read_df_rows(df))[0][0].level
        self.assertEqual(one(DISK_WARN_PCT - 1), LEVEL_OK)       # 边界下：正常
        self.assertEqual(one(DISK_WARN_PCT), LEVEL_WARN)         # 边界上：警告
        self.assertEqual(one(DISK_CRIT_PCT - 1), LEVEL_WARN)
        self.assertEqual(one(DISK_CRIT_PCT), LEVEL_CRIT)

    def test_healthy_mounts_get_one_summary_line(self):
        df = ("Filesystem      Size  Used Avail Use% Mounted on\n"
              "/dev/sda1       100G   30G   70G  30% /\n"
              "/dev/sdb1       500G  100G  400G  20% /data\n")
        findings, _ = judge_disk(read_df_rows(df))
        self.assertEqual(len(findings), 1)                        # 两条正常合成一条，别刷屏
        self.assertIn("2 个挂载点都正常", findings[0].detail)

    def test_no_local_filesystem_says_cannot_judge(self):
        """满屏都是别人的盘时，老实说"判不了"，别硬给个结论。"""
        df = ("Filesystem      Size  Used Avail Use% Mounted on\n"
              "none            3.4G     0  3.4G   0% /mnt/wsl\n")
        findings, skipped = judge_disk(read_df_rows(df))
        self.assertEqual(findings[0].level, LEVEL_INFO)
        self.assertIn("判不了", findings[0].detail)
        self.assertEqual(len(skipped), 1)

    def test_empty_input_does_not_crash(self):
        findings, skipped = judge_disk([])
        self.assertEqual(skipped, [])
        self.assertEqual(findings[0].level, LEVEL_INFO)


# ---------------------- ③ 内存：看 available，不看 free ----------------------

class MemoryTest(unittest.TestCase):
    def test_healthy_host(self):
        findings = judge_memory(read_mem(REAL_FREE))
        self.assertEqual(findings[0].level, LEVEL_OK)
        self.assertIn("4488", findings[0].detail)          # 报的是 available
        self.assertEqual(len(findings), 1)                 # swap 用了 0 就不占篇幅

    def test_low_available_triggers_warn_then_crit(self):
        def one(avail):
            text = ("               total        used        free      shared  buff/cache   available\n"
                    f"Mem:            1000         700         100           0         200        {avail}\n")
            return judge_memory(read_mem(text))[0].level
        self.assertEqual(one(int(1000 * MEM_AVAIL_CRIT_PCT / 100)), LEVEL_CRIT)   # 边界上
        self.assertEqual(one(int(1000 * MEM_AVAIL_CRIT_PCT / 100) + 1), LEVEL_WARN)
        self.assertEqual(one(500), LEVEL_OK)

    def test_small_free_but_large_cache_is_not_an_alarm(self):
        """经典误判：free 只剩 100MB 看着要死了，其实那 3000MB 都拿去做缓存了，随时能还。"""
        text = ("               total        used        free      shared  buff/cache   available\n"
                "Mem:            4000         600         100           0        3300        3400\n")
        self.assertEqual(judge_memory(read_mem(text))[0].level, LEVEL_OK)

    def test_swap_in_use_is_reported(self):
        def swap(used):
            text = ("               total        used        free      shared  buff/cache   available\n"
                    "Mem:            4000        1000        2000           0        1000        2500\n"
                    f"Swap:           1000        {used}        {1000 - used}\n")
            return judge_memory(read_mem(text))
        self.assertEqual(len(swap(0)), 1)                                   # 没用就不报
        self.assertEqual(swap(100)[-1].level, LEVEL_OK)                     # 10% 还不用管
        self.assertEqual(swap(300)[-1].level, LEVEL_WARN)                   # 30%
        self.assertEqual(swap(800)[-1].level, LEVEL_CRIT)                   # 80%

    def test_missing_info_says_cannot_judge(self):
        for bad in ({}, {"total": 0}):
            self.assertEqual(judge_memory(bad)[0].level, LEVEL_INFO)


# ---------------------- ④ 负载：不除以核数就是耍流氓 ----------------------

class LoadTest(unittest.TestCase):
    def test_same_load_means_opposite_things_on_different_core_counts(self):
        """同一个负载 4.0：2 核机器是严重过载，16 核机器是清闲。"""
        load = read_load(" 10:00 up 1 day,  1 user,  load average: 4.00, 3.00, 2.00\n")
        self.assertEqual(judge_load(load, 2)[0].level, LEVEL_CRIT)
        self.assertEqual(judge_load(load, 16)[0].level, LEVEL_OK)
        self.assertIn("每核 2.00", judge_load(load, 2)[0].detail)

    def test_no_cores_means_no_verdict(self):
        """拿不到核数就老实说"判不了"，绝不硬给一个听着专业的结论。"""
        load = read_load(" 10:00 up 1 day,  load average: 4.00, 3.00, 2.00\n")
        finding = judge_load(load, None)[0]
        self.assertEqual(finding.level, LEVEL_INFO)
        self.assertIn("不下结论", finding.detail)

    def test_unreadable_load(self):
        self.assertEqual(judge_load(None, 4)[0].level, LEVEL_INFO)
        self.assertEqual(read_load(""), None)
        self.assertEqual(read_load("garbage"), None)


# ---------------------- ⑤ 服务：运行中 ≠ 没事 ----------------------

class ServiceTest(unittest.TestCase):
    def test_healthy_service(self):
        f = judge_service("ssh", "active\n", "enabled\n", REAL_SHOW_OK)
        self.assertEqual(f.level, LEVEL_OK)
        self.assertIn("运行中", f.detail)
        self.assertIn("201", f.detail)

    def test_not_running_is_critical(self):
        """清单上的服务 = 本该活着的，没活就是问题。"""
        for state in ("inactive\n", "failed\n", "activating\n"):
            f = judge_service("nginx", state, "enabled\n", "LoadState=loaded\n")
            self.assertEqual(f.level, LEVEL_CRIT, f"{state!r} 应判严重")

    def test_missing_service_is_critical(self):
        f = judge_service("nosuch", "unknown\n", "enabled\n", "LoadState=not-found\n")
        self.assertEqual(f.level, LEVEL_CRIT)
        self.assertIn("不存在", f.detail)

    def test_active_but_restart_looping_is_warned(self):
        """最值钱的一条：反复崩被 systemd 拉起来，is-active 永远显示运行中。"""
        f = judge_service("nginx", "active\n", "enabled\n",
                          "MainPID=42\nNRestarts=7\nLoadState=loaded\n")
        self.assertEqual(f.level, LEVEL_WARN)
        self.assertIn("运行中", f.detail)          # 状态本身确实是对的
        self.assertIn("重启过 7 次", f.detail)     # 但这个才是真相

    def test_not_enabled_is_info_not_alarm(self):
        f = judge_service("ssh", "active\n", "disabled\n", REAL_SHOW_OK)
        self.assertEqual(f.level, LEVEL_INFO)
        self.assertIn("开机不自启", f.detail)

    def test_static_unit_is_not_reported_as_a_problem(self):
        """真机踩过的假警报：systemd-journald 的 is-enabled 是 static。

        static 的意思不是"忘了开自启"，而是**这个 unit 根本 enable 不了**——
        它的 unit 文件里没有 [Install] 段（真机验过：grep -c '\\[Install\\]' 输出 0，
        而 cron 输出 1）。它是启动过程中被 systemd 直接拉起来的，不靠 enable。
        报它"不自启"就是纯假警报——狼来了喊多了，真有问题的反而没人信。
        """
        f = judge_service("systemd-journald", "active\n", "static\n", REAL_SHOW_OK)
        self.assertEqual(f.level, LEVEL_OK)
        self.assertNotIn("不自启", f.detail)

    def test_other_non_actionable_enabled_states_stay_quiet(self):
        for state in ("static", "indirect", "alias", "generated", "enabled-runtime"):
            f = judge_service("x", "active\n", state + "\n", REAL_SHOW_OK)
            self.assertEqual(f.level, LEVEL_OK, f"{state} 不该报警")

    def test_masked_unit_is_worse_than_disabled(self):
        """masked = 被屏蔽了，连手工 start 都失败——比单纯没自启严重。"""
        f = judge_service("x", "active\n", "masked\n", REAL_SHOW_OK)
        self.assertEqual(f.level, LEVEL_WARN)
        self.assertIn("屏蔽", f.detail)

    def test_worst_level_wins_when_both_apply(self):
        """既没在跑又重启过：报更严重的那个（严重），不是被警告盖住。"""
        f = judge_service("x", "failed\n", "disabled\n", "NRestarts=9\nLoadState=loaded\n")
        self.assertEqual(f.level, LEVEL_CRIT)


# ---------------------- ⑥ 报告：结论先行 ----------------------

class ReportTest(unittest.TestCase):
    def _report(self, service_findings=(), host_findings=(), skipped=()):
        return build_report("假SSH", "2026-09-14 09:30:00", list(service_findings),
                            list(host_findings), list(skipped), 1)

    def test_verdict_comes_before_everything(self):
        text = self._report(host_findings=[Finding(LEVEL_CRIT, "磁盘 /", "96%")])
        self.assertLess(text.index("结论："), text.index("【服务】") if "【服务】" in text else len(text))
        self.assertLess(text.index("结论："), text.index("【主机】"))

    def test_verdict_wording_per_severity(self):
        self.assertIn("一切正常", self._report(host_findings=[Finding(LEVEL_OK, "a", "b")]))
        self.assertIn("严重", self._report(host_findings=[Finding(LEVEL_CRIT, "a", "b")]))
        self.assertIn("警告", self._report(host_findings=[Finding(LEVEL_WARN, "a", "b")]))

    def test_crit_dominates_verdict(self):
        text = self._report(host_findings=[Finding(LEVEL_WARN, "a", "b"), Finding(LEVEL_CRIT, "c", "d")])
        self.assertIn("发现 1 项严重问题", text)

    def test_worst_finding_printed_first(self):
        text = self._report(host_findings=[Finding(LEVEL_OK, "好的", "x"),
                                           Finding(LEVEL_CRIT, "坏的", "y")])
        self.assertLess(text.index("坏的"), text.index("好的"))

    def test_skipped_mounts_are_disclosed(self):
        """跳过了必须说出来——不然看报告的人以为你全看过了。"""
        text = self._report(host_findings=[Finding(LEVEL_OK, "磁盘", "正常")],
                            skipped=["/mnt/wsl（1%）", "drivers（92%）"])
        self.assertIn("不属于这台机器", text)
        self.assertIn("drivers", text)


# ---------------------- ⑦ 端到端：一次完整巡检 ----------------------

HEALTHY = {
    "systemctl is-active": "active\n",
    "systemctl is-enabled": "enabled\n",
    "systemctl show": REAL_SHOW_OK,
    "uptime": REAL_UPTIME,
    "nproc": "8\n",
    "free -m": REAL_FREE,
    "df -h": REAL_DF_WSL,
}

SICK = {
    "systemctl is-active": "failed\n",
    "systemctl is-enabled": "disabled\n",
    "systemctl show": "MainPID=0\nNRestarts=12\nLoadState=loaded\nSubState=failed\n",
    "uptime": " 10:00:00 up 12 days,  load average: 8.50, 7.20, 6.10\n",
    "nproc": "2\n",
    "free -m": ("               total        used        free      shared  buff/cache   available\n"
                "Mem:            4000        3900          20           0           80         100\n"
                "Swap:           2048        1800         248\n"),
    "df -h": ("Filesystem      Size  Used Avail Use% Mounted on\n"
              "/dev/sda1       200G  192G     8G  96% /\n"),
}


class EndToEndTest(unittest.TestCase):
    def test_healthy_host_reports_all_clear(self):
        text = patrol_host("ssh", FakeRunner(HEALTHY), now=_ts())
        self.assertIn("一切正常", text)
        self.assertIn("8 核", text)
        self.assertIn("2026-09-14 09:30:00", text)
        self.assertNotIn("严重", text)

    def test_sick_host_surfaces_every_problem(self):
        text = patrol_host("nginx", FakeRunner(SICK), now=_ts())
        self.assertIn("严重", text)
        self.assertIn("96%", text)                     # 磁盘
        self.assertIn("每核 4.25", text)               # 负载 8.5 / 2 核
        self.assertIn("Swap", text)                    # swap 用了 88%
        self.assertIn("崩溃", text)                    # 服务 failed

    def test_unreachable_host_has_no_verdict(self):
        """连不上 ≠ 一切正常。要明说"这次巡检没有结论"。"""
        text = patrol_host("ssh", FakeRunner(HEALTHY, reachable=False), now=_ts())
        self.assertIn("没跑成", text)
        self.assertIn("不能当成", text)
        self.assertNotIn("结论：✅", text)      # 别在结论那一行给出"没事"的错觉（正文里提到"一切正常"这四个字没关系，那是在提醒别当成它）

    def test_midway_disconnect_still_returns_a_report(self):
        runner = FakeRunner(HEALTHY)
        calls = {"n": 0}

        def flaky(cmd):
            calls["n"] += 1
            if calls["n"] > 2:
                return 255, "[模拟] 连接中断"
            return runner.run(cmd)

        runner.run = flaky
        text = patrol_host("ssh", runner, now=_ts())
        self.assertIn("没跑完", text)
        self.assertIn("重跑", text)

    def test_no_host_configured_says_so(self):
        text = patrol_host("ssh", None)
        self.assertIn("没配远端主机", text)

    def test_default_units_come_from_caller(self):
        runner = FakeRunner(HEALTHY)
        patrol_host(None, runner, now=_ts())
        self.assertEqual(sum(1 for c in runner.calls if c.startswith("systemctl")), 0)

    def test_multiple_units_each_checked(self):
        runner = FakeRunner(HEALTHY)
        text = patrol_host("ssh, cron", runner, now=_ts())
        self.assertIn("巡检了 2 个", text)
        self.assertEqual(sum(1 for c in runner.calls if c.startswith("systemctl is-active")), 2)


# ---------------------- ⑧ 门：巡检取数也必须过三道门 ----------------------

class PatrolDoorTest(unittest.TestCase):
    def test_injected_unit_list_is_refused_whole(self):
        """清单里塞命令 → 整条拒掉，**一个字节都不发**，连探活都不做。

        反面教材（真踩过）：`"ssh; rm -rf /"` 按空格拆是 ["ssh;","rm","-rf","/"]，
        其中 "rm" 居然通过了服务名正则 → 会真的发出 `systemctl is-active rm`。
        那条命令无害（只读且在白名单里），但**"拆开后有一段碰巧合法"这种路子不能开**。
        所以这里断言的是 runner.calls 完全为空——不是"没发出危险命令"，是"什么都没发"。
        """
        runner = FakeRunner(HEALTHY)
        text = patrol_host("ssh; rm -rf /", runner, now=_ts())
        self.assertIn("不合法", text)
        self.assertIn("没有向主机发出任何命令", text)
        self.assertEqual(runner.calls, [])
        self.assertEqual(text.count("结论："), 1)       # 一份报告一个结论，不重复

    def test_single_bad_unit_name_among_good_ones_only_skips_that_one(self):
        """单个坏名字（没带注入字符）不该搞崩整份报告：标出来，继续巡检其余的。"""
        runner = FakeRunner(HEALTHY)
        text = patrol_host("ssh, bad-name!", runner, now=_ts())
        self.assertIn("不合法", text)
        self.assertIn("已跳过", text)
        self.assertIn("ssh", runner.calls[0])           # 好名字照常巡检
        self.assertNotIn("坏", runner.calls[0])

    def test_units_screen_allows_real_separators(self):
        """换行和空格是清单的合法分隔符，不能因为防注入把它们也禁了。"""
        ok, _ = screen_units("ssh nginx\ncron,redis")
        self.assertTrue(ok)
        self.assertEqual(parse_units("ssh nginx\ncron,redis"), ["ssh", "nginx", "cron", "redis"])
        for bad in ("ssh; rm -rf /", "ssh | cat /etc/passwd", "ssh && reboot",
                    "ssh `id`", "ssh > /etc/passwd"):
            ok, reason = screen_units(bad)
            self.assertFalse(ok, f"{bad!r} 该被拒")
            self.assertIn("禁止字符", reason)

    def test_screen_units_accepts_list_form(self):
        self.assertTrue(screen_units(["ssh", "nginx"])[0])

    def test_every_command_patrol_sends_passes_the_remote_door(self):
        """自洽检查：巡检自己发的每一条命令，都得过得了自己的远端白名单。"""
        runner = FakeRunner(HEALTHY)
        patrol_host("ssh,nginx", runner, now=_ts())
        self.assertTrue(runner.calls, "应该真的发过命令")
        for cmd in runner.calls:
            ok, reason = screen_remote_cmd(cmd)
            self.assertTrue(ok, f"自己发的命令过不了自己的门：{cmd}（{reason}）")

    def test_new_nproc_command_is_in_the_whitelist(self):
        ok, _ = screen_remote_cmd("nproc")
        self.assertTrue(ok, "nproc 是只读查询，该在白名单里")

    def test_healthy_and_sick_paths_send_the_same_command_set(self):
        """巡检发什么命令不取决于机器好坏（不然就是"看人下菜碟"）。"""
        a, b = FakeRunner(HEALTHY), FakeRunner(SICK)
        patrol_host("ssh", a, now=_ts())
        patrol_host("ssh", b, now=_ts())
        self.assertEqual(sorted(a.calls), sorted(b.calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)

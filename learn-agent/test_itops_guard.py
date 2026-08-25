# test_itops_guard.py — IT 运维安全护栏单元测试
# 跑：python learn-agent/test_itops_guard.py
# 测点：命令黑名单放行/拦截、路径护栏、日志过滤、服务三态。
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from itops_guard import (
    DANGEROUS_CMDS,
    guard_command,
    read_log_safely,
    load_service_registry,
    check_service_status,
)


class TestGuardAllow(unittest.TestCase):
    """只读命令应该放行"""

    def test_common_read_commands(self):
        """常见只读命令：ls/ps/tail/grep/df/cat/free/uptime 全部放行"""
        for cmd in [
            "ls",
            "ls -la",
            "ps aux",
            "tail -n 20 app.log",
            "grep ERROR app.log",
            "df -h",
            "cat config.yml",
            "free -m",
            "uptime",
        ]:
            ok, reason = guard_command(cmd)
            self.assertTrue(ok, f"{cmd} 应放行，实际 {reason}")

    def test_script_execution(self):
        """跑脚本本身是只读的（脚本内部动作不归这里管）"""
        ok, reason = guard_command("python check_health.py")
        self.assertTrue(ok)


class TestGuardBlock(unittest.TestCase):
    """破坏性命令必须拦截"""

    def test_delete_commands(self):
        """删除类：rm/del/erase/rd 全拦"""
        for cmd in ["rm app.log", "rm -rf /", "rmdir logs", "del app.log", "erase app.log", "rd logs"]:
            ok, reason = guard_command(cmd)
            self.assertFalse(ok, f"{cmd} 应拦截，实际 {reason}")

    def test_kill_commands(self):
        """杀进程类：kill/taskkill/pkill/killall 全拦"""
        for cmd in ["kill -9 123", "taskkill /F /PID 123", "pkill order-api", "killall java"]:
            ok, reason = guard_command(cmd)
            self.assertFalse(ok, f"{cmd} 应拦截，实际 {reason}")

    def test_system_commands(self):
        """系统级：重启/关机/格式化/改防火墙 全拦"""
        for cmd in [
            "reboot",
            "shutdown -h now",
            "halt",
            "poweroff",
            "mkfs.ext4 /dev/sda",
            "dd if=/dev/zero of=/dev/sda",
            "iptables -F",
            "systemctl stop order-api",
            "service nginx restart",
            "format c:",
        ]:
            ok, reason = guard_command(cmd)
            self.assertFalse(ok, f"{cmd} 应拦截，实际 {reason}")

    def test_write_redirect(self):
        """写重定向：覆盖/追加 都拒绝"""
        for cmd in ["cat a > b", "echo x >> f.log", "grep x a > out.txt"]:
            ok, reason = guard_command(cmd)
            self.assertFalse(ok, f"{cmd} 应拦截，实际 {reason}")

    def test_no_space_redirect(self):
        """不带空格的 `>b` 也被兜住"""
        ok, reason = guard_command("cat a >b")
        self.assertFalse(ok)

    def test_chained_destructive(self):
        """管道/分号拼接的破坏性命令也能拦（rm 是独立 token）"""
        for cmd in ["ls | rm -rf /", "ls; rm app.log", "ps aux | kill -9 1"]:
            ok, reason = guard_command(cmd)
            self.assertFalse(ok, f"{cmd} 应拦截，实际 {reason}")

    def test_uppercase_is_blocked(self):
        """大小写归一：RM 一样拦"""
        ok, reason = guard_command("RM -rf /")
        self.assertFalse(ok)

    def test_all_dangerous_tokens_present(self):
        """黑名单覆盖了演示要用的几个破坏性动词"""
        for tok in ["rm", "kill", "reboot", "systemctl", "dd", ">"]:
            self.assertIn(tok, DANGEROUS_CMDS)


class TestReadLogSafely(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "app.log").write_text(
            "line1 ok\n"
            "line2 ERROR pool exhausted\n"
            "line3 ok\n"
            "line4 ERROR pool exhausted\n"
            "line5 ok\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file(self):
        """文件不存在：优雅返回提示，不抛异常"""
        out = read_log_safely("nope.log", self.tmp)
        self.assertIn("日志不存在", out)

    def test_path_escape_relative(self):
        """../ 越权路径：拒绝"""
        out = read_log_safely("../secret.txt", self.tmp)
        self.assertIn("拒绝读取", out)
        out = read_log_safely("../../.env", self.tmp)
        self.assertIn("拒绝读取", out)

    def test_absolute_path_escape(self):
        """绝对路径超出 base：拒绝"""
        out = read_log_safely(str(Path.home() / ".bashrc"), self.tmp)
        self.assertIn("拒绝读取", out)

    def test_directory_rejected(self):
        """目标是目录：拒绝"""
        out = read_log_safely(".", self.tmp)
        self.assertIn("拒绝读取", out)

    def test_keyword_filter(self):
        """关键词过滤 + 原行号：命中第 2、4 行"""
        out = read_log_safely("app.log", self.tmp, keyword="ERROR")
        lines = out.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("2:"))
        self.assertTrue(lines[1].startswith("4:"))

    def test_keyword_case_insensitive(self):
        """关键词忽略大小写：error 一样命中"""
        out = read_log_safely("app.log", self.tmp, keyword="error")
        self.assertEqual(len(out.splitlines()), 2)

    def test_keyword_no_match(self):
        """关键词无命中：明说没找到，不装"""
        out = read_log_safely("app.log", self.tmp, keyword="NOTHERE")
        self.assertIn("没找到", out)

    def test_tail_lines(self):
        """只回末尾 N 条，行号跟着走"""
        out = read_log_safely("app.log", self.tmp, tail_lines=2)
        lines = out.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("4:"))
        self.assertTrue(lines[1].startswith("5:"))

    def test_tail_lines_clamped(self):
        """tail_lines 钳制在 [1,100]：999 不炸、-1 按 1 处理"""
        out = read_log_safely("app.log", self.tmp, tail_lines=999)
        self.assertEqual(len(out.splitlines()), 5)
        out = read_log_safely("app.log", self.tmp, tail_lines=-1)
        self.assertEqual(len(out.splitlines()), 1)

    def test_empty_file(self):
        """空文件返回空串"""
        (self.tmp / "empty.log").write_text("", encoding="utf-8")
        out = read_log_safely("empty.log", self.tmp)
        self.assertEqual(out, "")


class TestServiceStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "services.json").write_text(
            json.dumps({
                "order-api": {
                    "description": "订单查询服务",
                    "pid_file": "order-api.pid",
                    "log_file": "app.log",
                    "port": 8080,
                }
            }),
            encoding="utf-8",
        )
        self.registry = load_service_registry(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unknown_service(self):
        out = check_service_status("nope", self.registry, self.tmp)
        self.assertIn("未知服务", out)

    def test_stopped(self):
        out = check_service_status("order-api", self.registry, self.tmp)
        self.assertIn("停止", out)

    def test_running(self):
        (self.tmp / "order-api.pid").write_text("1234", encoding="utf-8")
        out = check_service_status("order-api", self.registry, self.tmp)
        self.assertIn("运行中", out)
        self.assertIn("1234", out)
        self.assertIn("8080", out)

    def test_missing_registry(self):
        reg = load_service_registry(Path(tempfile.mkdtemp()))
        self.assertEqual(reg, {})


if __name__ == "__main__":
    unittest.main()

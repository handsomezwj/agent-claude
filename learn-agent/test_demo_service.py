# test_demo_service.py — 假服务启停生命周期测试
# 跑：python learn-agent/test_demo_service.py
# 测点：start/stop/status 的状态迁移、幂等、未知服务；全部在临时目录里跑，不碰演示数据。
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ops_demo"))
import demo_service


def make_env():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "services.json").write_text(
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
    (tmp / "app.log").write_text(
        "2026-08-24 10:00:01 INFO [startup] boot\n", encoding="utf-8"
    )
    return tmp


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = make_env()
        self.pid_file = self.tmp / "order-api.pid"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_initial_stopped(self):
        """刚建好时：未运行"""
        out = demo_service.status(self.tmp, "order-api")
        self.assertIn("停止", out)

    def test_start_writes_pid_and_log(self):
        """start：写 pid 文件 + 追加日志"""
        demo_service.start(self.tmp, "order-api")
        self.assertTrue(self.pid_file.exists())
        log = (self.tmp / "app.log").read_text(encoding="utf-8")
        self.assertIn("started", log)

    def test_start_is_idempotent(self):
        """重复 start：不覆盖 pid、明确提示已在运行"""
        demo_service.start(self.tmp, "order-api")
        first = self.pid_file.read_text(encoding="utf-8")
        out = demo_service.start(self.tmp, "order-api")
        self.assertIn("已经在运行", out)
        self.assertEqual(self.pid_file.read_text(encoding="utf-8"), first)

    def test_stop_removes_pid(self):
        """stop：删 pid 文件 + 追加日志"""
        demo_service.start(self.tmp, "order-api")
        out = demo_service.stop(self.tmp, "order-api")
        self.assertFalse(self.pid_file.exists())
        self.assertIn("已停止", out)

    def test_stop_when_not_running(self):
        """没在跑时 stop：优雅提示，不炸"""
        out = demo_service.stop(self.tmp, "order-api")
        self.assertIn("本来就没在运行", out)

    def test_status_after_start(self):
        """start 后 status：运行中"""
        demo_service.start(self.tmp, "order-api")
        out = demo_service.status(self.tmp, "order-api")
        self.assertIn("运行中", out)

    def test_unknown_service(self):
        """未知服务：任何操作都提示"""
        self.assertIn("未知服务", demo_service.start(self.tmp, "nope"))
        self.assertIn("未知服务", demo_service.stop(self.tmp, "nope"))
        self.assertIn("未知服务", demo_service.status(self.tmp, "nope"))


if __name__ == "__main__":
    unittest.main()

# eval：测"原地打转"的逻辑
# 运行方式：python test_spin_guard.py
import unittest
from spin_guard import make_fingerprint, track_repeat


class TestSpinGuard(unittest.TestCase):

    def test_first_call_not_stuck(self):
        """第一次调用：连数=1，不打转"""
        fp = make_fingerprint("get_weather", {"city": "北京"})
        count, stuck = track_repeat(None, 0, fp)
        self.assertEqual(count, 1)
        self.assertFalse(stuck)

    def test_two_same_not_stuck(self):
        """连点 2 次相同的：连数=2，还没触发"""
        fp = make_fingerprint("get_weather", {"city": "北京"})
        c, _ = track_repeat(None, 0, fp)       # 第 1 次
        c, stuck = track_repeat(fp, c, fp)     # 第 2 次
        self.assertEqual(c, 2)
        self.assertFalse(stuck)

    def test_three_same_triggers(self):
        """连点 3 次相同的：触发打转"""
        fp = make_fingerprint("get_weather", {"city": "北京"})
        c, _ = track_repeat(None, 0, fp)
        c, _ = track_repeat(fp, c, fp)
        c, stuck = track_repeat(fp, c, fp)     # 第 3 次
        self.assertTrue(stuck)
        self.assertEqual(c, 3)

    def test_different_tool_resets(self):
        """中间换了一道菜：连数重置回 1"""
        a = make_fingerprint("get_weather", {"city": "北京"})
        b = make_fingerprint("get_weather", {"city": "上海"})
        c, _ = track_repeat(None, 0, a)        # A
        c, _ = track_repeat(a, c, a)           # A，连数=2
        c, _ = track_repeat(a, c, b)           # B，重置 → 1
        self.assertEqual(c, 1)

    def test_full_sequence_A_A_B_A_A_A(self):
        """完整序列 A A B A A A：第 6 次触发——你上一课手算的答案"""
        seq = [
            ("get_weather", {"city": "北京"}),
            ("get_weather", {"city": "北京"}),
            ("get_weather", {"city": "上海"}),
            ("get_weather", {"city": "北京"}),
            ("get_weather", {"city": "北京"}),
            ("get_weather", {"city": "北京"}),
        ]
        prev, count, triggered_at = None, 0, None
        for i, (name, args) in enumerate(seq, start=1):
            fp = make_fingerprint(name, args)
            count, stuck = track_repeat(prev, count, fp)
            prev = fp
            if stuck:
                triggered_at = i
                break
        self.assertEqual(triggered_at, 6)


if __name__ == "__main__":
    unittest.main()

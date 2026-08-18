# 普适性测试：不测"某个序列"，测"规则本身"
# 运行：python test_spin_property.py
import random
import unittest
from spin_guard import make_fingerprint, track_repeat


class TestSpinGuardUniversal(unittest.TestCase):

    def test_rule_holds_on_500_random_sequences(self):
        """规则：触发 ⟺ 序列里存在连续 3 个相同的调用。
        随机生成 500 个序列，逐个验证；任何一个违反就算失败。"""
        cities = ["北京", "上海", "广州"]
        random.seed(42)  # 固定种子：每次跑用同一批序列，结果可复现

        for _ in range(500):
            n = random.randint(0, 30)
            seq = [("get_weather", {"city": random.choice(cities)}) for _ in range(n)]

            # ① 让守卫跑一遍，记录它到底触没触发
            prev, count, ever_stuck = None, 0, False
            for name, args in seq:
                fp = make_fingerprint(name, args)
                count, stuck = track_repeat(prev, count, fp)
                prev = fp
                if stuck:
                    ever_stuck = True

            # ② 不靠守卫，独立地算"真实该不该触发"
            #    （存在连续3个相同调用 = 该触发）
            real_spin = any(
                seq[i] == seq[i + 1] == seq[i + 2] for i in range(len(seq) - 2)
            )

            self.assertEqual(ever_stuck, real_spin, f"序列 {seq} 时规则被打破")


if __name__ == "__main__":
    unittest.main()

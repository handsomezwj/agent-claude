# 第 21 课 eval：测 Agent 记忆系统（记事本 + 事实提取 + 自动记 + 拼 prompt）
# 全部离线：MemoryStore 只用临时文件，不读 .env、不调 API。
import json
import os
import tempfile
import unittest

from agent_loop import text_block
from memory_store import (
    MEMORY_HEADER,
    MemoryStore,
    build_memory_prompt,
    extract_facts,
    remember_last_turn,
)


class TestMemoryStore(unittest.TestCase):
    """测记事本本身：增 / 查 / 去重 / 上限 / 存盘读回 / 读坏文件不崩"""

    def test_add_and_all(self):
        store = MemoryStore()
        store.add("我叫小张")
        store.add("我在杭州工作")
        self.assertEqual(store.all(), ["我叫小张", "我在杭州工作"])

    def test_duplicate_skipped(self):
        store = MemoryStore()
        self.assertTrue(store.add("我叫小张"))
        self.assertFalse(store.add("我叫小张"))   # 重复 → 不记，返回 False
        self.assertEqual(store.all(), ["我叫小张"])

    def test_blank_skipped(self):
        store = MemoryStore()
        self.assertFalse(store.add("   "))
        self.assertFalse(store.add(""))
        self.assertEqual(store.all(), [])

    def test_max_items_drops_oldest(self):
        store = MemoryStore(max_items=2)
        store.add("记忆1")
        store.add("记忆2")
        store.add("记忆3")            # 超了 → 最老的被挤掉
        self.assertEqual(store.all(), ["记忆2", "记忆3"])

    def test_roundtrip_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nb.json")
            store = MemoryStore(path)
            store.add("我叫小张")
            store.add("我喜欢吃火锅")
            store.save()
            store2 = MemoryStore(path)     # 模拟"程序重启"：new 一个，从同一文件读回
            store2.load()
            self.assertEqual(store2.all(), ["我叫小张", "我喜欢吃火锅"])

    def test_remember_saves_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nb.json")
            store = MemoryStore(path)
            store.remember("我叫小张")
            self.assertTrue(os.path.exists(path))
            store2 = MemoryStore(path)
            store2.load()
            self.assertEqual(store2.all(), ["我叫小张"])

    def test_load_missing_file_empty(self):
        store = MemoryStore("/no/such/file.json")
        self.assertEqual(store.load(), [])

    def test_load_corrupt_file_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("这不是 JSON{{{")
            store = MemoryStore(path)
            self.assertEqual(store.load(), [])   # 读坏文件 → 空，不崩

    def test_load_caps_to_max(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nb.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(["a", "b", "c"], f)
            store = MemoryStore(path, max_items=2)
            store.load()
            self.assertEqual(store.all(), ["b", "c"])


class TestExtractFacts(unittest.TestCase):
    """测规则提取：常见"关于用户的事实"句式要能抽出来，不该记的别误伤"""

    def test_identity(self):
        self.assertEqual(extract_facts("我叫小张"), ["我叫小张"])

    def test_location_job(self):
        out = extract_facts("我在杭州工作，每天骑车上班")
        self.assertEqual(out, ["我在杭州工作，每天骑车上班"])

    def test_preference(self):
        self.assertEqual(extract_facts("我喜欢吃火锅"), ["我喜欢吃火锅"])

    def test_explicit_command(self):
        # "记住：X" → 记的是 X，不是整句（有标点 / 没标点都得认）
        self.assertEqual(extract_facts("记住：我周五要交简历"), ["我周五要交简历"])
        self.assertEqual(extract_facts("别忘了周四开会"), ["周四开会"])

    def test_acknowledgement_not_recorded(self):
        # "我记住了"是应答不是命令，不该被当成要记的事实
        self.assertEqual(extract_facts("好的，我记住了"), [])

    def test_no_fact(self):
        self.assertEqual(extract_facts("杭州今天下雨"), [])
        self.assertEqual(extract_facts("今天天气不错"), [])

    def test_multiple_sentences(self):
        out = extract_facts("我叫小张。今天天气不错。我在杭州工作。")
        self.assertEqual(out, ["我叫小张", "我在杭州工作"])

    def test_empty_and_none(self):
        self.assertEqual(extract_facts(""), [])
        self.assertEqual(extract_facts(None), [])

    def test_extractor_door(self):
        # extractor 是"门"：传了就用它的返回值，规则靠边站
        fake = lambda text: [f"LLM提炼: {text[:5]}"]
        self.assertEqual(extract_facts("我叫小张，在杭州做AI开发", fake), ["LLM提炼: 我叫小张，"])


class TestBuildMemoryPrompt(unittest.TestCase):
    """测拼 prompt：有记忆按条编号、无记忆给空提示"""

    def test_has_header(self):
        self.assertIn(MEMORY_HEADER, build_memory_prompt(["我叫小张"]))

    def test_numbered(self):
        p = build_memory_prompt(["我叫小张", "我在杭州工作"])
        self.assertIn("1. 我叫小张", p)
        self.assertIn("2. 我在杭州工作", p)

    def test_empty(self):
        self.assertIn("还没有记忆", build_memory_prompt([]))


class TestRememberLastTurn(unittest.TestCase):
    """测自动记：一轮对话结束，从"最近一问 + 最近一答"里抽事实写进记事本"""

    def test_learns_from_user_message(self):
        msgs = [
            {"role": "user", "content": "我叫小张，在杭州做 AI 开发。"},
            {"role": "assistant", "content": [text_block("好的，小张！")]},
        ]
        store = MemoryStore()
        self.assertEqual(remember_last_turn(store, msgs), 1)
        self.assertIn("我叫小张，在杭州做 AI 开发", store.all())

    def test_learns_from_reply_too(self):
        msgs = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": [text_block("你好，我住在西湖边。")]},
        ]
        store = MemoryStore()
        self.assertEqual(remember_last_turn(store, msgs), 1)
        self.assertEqual(store.all(), ["你好，我住在西湖边"])

    def test_ignores_tool_result_messages(self):
        # 工具结果不是"真问题"，不该被当成要记的对话
        msgs = [
            {"role": "user", "content": [{"type": "tool_result", "content": "我叫小张"}]},
            {"role": "assistant", "content": [text_block("搞定。")]},
        ]
        store = MemoryStore()
        self.assertEqual(remember_last_turn(store, msgs), 0)
        self.assertEqual(store.all(), [])

    def test_duplicate_not_double_counted(self):
        msgs = [
            {"role": "user", "content": "我叫小张"},
            {"role": "assistant", "content": [text_block("好的")]},
        ]
        store = MemoryStore()
        self.assertEqual(remember_last_turn(store, msgs), 1)
        self.assertEqual(remember_last_turn(store, msgs), 0)   # 第二遍记不下重复的
        self.assertEqual(store.all(), ["我叫小张"])

    def test_empty_messages(self):
        store = MemoryStore()
        self.assertEqual(remember_last_turn(store, []), 0)

    def test_plain_string_assistant(self):
        # assistant content 有些路径是字符串（不是 content block 列表）也要兼容
        msgs = [
            {"role": "user", "content": "我叫小张"},
            {"role": "assistant", "content": "你好，小张！"},
        ]
        store = MemoryStore()
        self.assertEqual(remember_last_turn(store, msgs), 1)


if __name__ == "__main__":
    unittest.main()

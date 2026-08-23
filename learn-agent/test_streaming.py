# 第十四课 eval：测流式输出——拼字（纯函数）+ 假流跑通 + stop_reason 照常传回。
import unittest
from agent_loop import FakeResponse, FakeStream, text_block, tool_block
from streaming import assemble_text, run_stream


class TestAssembleText(unittest.TestCase):
    """测"拼字"这个纯函数"""

    def test_empty_chunks(self):
        self.assertEqual(assemble_text([]), "")

    def test_fragments_join_in_order(self):
        self.assertEqual(assemble_text(["你", "好", "！"]), "你好！")

    def test_mixed_ascii_and_cn(self):
        self.assertEqual(assemble_text(["AI ", "由", "人来写"]), "AI 由人来写")


class TestFakeStream(unittest.TestCase):
    """测假流：像真流一样能吐碎片，get_final_message 还回完整剧本"""

    def test_text_stream_splits_into_frames(self):
        resp = FakeResponse("end_turn", [text_block("abcd")])
        self.assertEqual(list(FakeStream(resp, chunk_size=2).text_stream), ["ab", "cd"])

    def test_empty_text_yields_nothing(self):
        resp = FakeResponse("end_turn", [text_block("")])
        self.assertEqual(list(FakeStream(resp).text_stream), [])

    def test_final_message_is_the_script(self):
        # get_final_message 原样还回剧本 → stop_reason/content 都在
        resp = FakeResponse("tool_use", [tool_block("load_skill", {"skill_name": "python"})])
        self.assertIs(FakeStream(resp).get_final_message(), resp)


class TestRunStream(unittest.TestCase):
    """测"跑一次流"：on_chunk 按顺序收到碎片，返回拼好的回答 + 最终消息"""

    def test_on_chunk_receives_frames_in_order(self):
        # chunk_size=1 → 逐字吐，演"打字机"
        resp = FakeResponse("end_turn", [text_block("你好")])
        seen = []
        reply, final = run_stream(lambda: FakeStream(resp, chunk_size=1), on_chunk=seen.append)
        self.assertEqual(seen, ["你", "好"])
        self.assertEqual(reply, "你好")
        self.assertEqual(final.stop_reason, "end_turn")

    def test_empty_stream_returns_empty(self):
        resp = FakeResponse("end_turn", [text_block("")])
        reply, final = run_stream(lambda: FakeStream(resp))
        self.assertEqual(reply, "")
        self.assertEqual(final.stop_reason, "end_turn")

    def test_tool_use_flows_through_unmodified(self):
        # 工具循环：吐不出字，但 stop_reason=tool_use 照常传回 → 老循环不用改
        resp = FakeResponse("tool_use", [tool_block("load_skill", {"skill_name": "python"})])
        reply, final = run_stream(lambda: FakeStream(resp))
        self.assertEqual(reply, "")
        self.assertEqual(final.stop_reason, "tool_use")


if __name__ == "__main__":
    unittest.main()

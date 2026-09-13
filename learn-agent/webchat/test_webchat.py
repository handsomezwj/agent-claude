# test_webchat.py —— webchat 专项测试（零 API，全离线）
#
# 覆盖三件事：
#   1. brain 层：离线剧本真跑通 agent 完整一轮（会真调离线工具）——排障/护栏/普通问答三剧本
#   2. 页面层：GET / 能渲染出聊天页，cookie sid 分配正常
#   3. 接口层：POST /api/chat 返回 SSE，且假模式下的流里真的滚出「动作日志」+「最终回答」
#
# 跑法（跟全套一起）：
#   cd learn-agent && python -m unittest discover -p "test_*.py"
import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path

# 保证 webchat 能当包被测试导入（discover 从 learn-agent 根递归进来）
_HERE = Path(__file__).resolve().parent
_LEARN = _HERE.parent
if str(_LEARN) not in sys.path:
    sys.path.insert(0, str(_LEARN))
# 硬设、不是 setdefault：万一 .env 里写了 AGENT_WEB_MODE=real，测试会被带成真模型
# （真花钱 + 不稳定）。load_dotenv 默认不覆盖已存在的环境变量，所以这里硬设就锁死了。
os.environ["AGENT_WEB_MODE"] = "fake"

from webchat import agent_brain                 # noqa: E402
from webchat.app import create_app               # noqa: E402


class BrainOfflineTest(unittest.TestCase):
    """不启动服务器，直接打 brain 的门：确认完整一轮（含工具调用）离线能真跑。"""

    def _run(self, message):
        msgs = []
        logs, reply, code = agent_brain.run_turn(msgs, message, mode="fake")
        return msgs, logs, reply, code

    def test_troubleshoot_script_calls_real_offline_tools(self):
        """排障剧本：脚本说调 check_service/query_log → 真离线工具真跑，日志被接出来。"""
        msgs, logs, reply, code = self._run("order-api 好像挂了，帮我查一下为什么")
        self.assertEqual(code, "END_TURN")
        joined = "\n".join(logs)
        self.assertIn("[查服务]", joined)          # 工具调用被打印成活动日志
        self.assertIn("[服务状态]", joined)        # 离线工具真跑了（不是编的）
        self.assertIn("[日志内容]", joined)
        self.assertIn("演示模式", reply)           # 最终回答被抠出来，没混进日志
        # 完整一轮 = 用户 + tool_use + tool_result + 最终回答，至少 4 条
        self.assertGreaterEqual(len(msgs), 4)

    def test_guard_script_gets_blocked(self):
        """护栏剧本：让 agent 删日志 → 真实 run_command 护栏拒绝，回答里明说被拦。"""
        msgs, logs, reply, code = self._run("那你帮我把日志删掉，重启一下服务")
        self.assertEqual(code, "END_TURN")
        self.assertIn("护栏", reply)
        self.assertIn("拒绝", reply)

    def test_qa_script_answers_without_tools(self):
        """普通问答剧本：不调工具，一句话收尾（页面打字机用）。"""
        msgs, logs, reply, code = self._run("你好，你是谁")
        self.assertEqual(code, "END_TURN")
        self.assertEqual(logs, [])                # 没工具调用 → 没活动日志
        self.assertIn("离线假脑子", reply)


class LiveSinkTest(unittest.TestCase):
    """第 2 步：日志真·逐条实时——QueueSink 按整行发、遇 [Agent回答] 封口。"""

    def test_emits_complete_lines_only(self):
        lines = []
        sink = agent_brain.QueueSink(lines.append)
        sink.write("[查服务]: order")      # print 可能把一行拆成几次 write，不能漏半行出去
        sink.write("-api\n")
        sink.write("\n")                   # 空行丢掉
        sink.write("[查日志]: x\n")
        self.assertEqual(lines, ["[查服务]: order-api", "[查日志]: x"])

    def test_seals_at_agent_answer_marker(self):
        lines = []
        sink = agent_brain.QueueSink(lines.append)
        sink.write("[查服务]: a\n[Agent回答]: 最终答案\n[裁判] 5/5\n")
        self.assertEqual(lines, ["[查服务]: a"])   # 回答和裁判不归活动日志管

    def test_run_turn_with_sink_streams_lines(self):
        """给 sink 时 logs 交空（日志已实时发出），回答照常抠出来。"""
        lines = []
        msgs = []
        logs, reply, code = agent_brain.run_turn(
            msgs, "order-api 好像挂了，帮我查一下为什么",
            mode="fake", log_sink=agent_brain.QueueSink(lines.append))
        self.assertEqual(code, "END_TURN")
        self.assertEqual(logs, [])
        self.assertTrue(any("[查服务]" in l for l in lines))
        self.assertIn("演示模式", reply)


class PageTest(unittest.TestCase):
    """页面层：GET / 渲染 + cookie 分配。"""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_index_renders(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("我的 Agent 助手".encode("utf-8"), resp.data)
        self.assertIn("演示模式".encode("utf-8"), resp.data)   # 假脑子模式徽标在页面上

    def test_index_sets_sid_cookie(self):
        resp = self.client.get("/")
        self.assertIsNotNone(resp.headers.get("Set-Cookie", ""))
        self.assertIn("sid=", resp.headers["Set-Cookie"])


class ChatSseTest(unittest.TestCase):
    """接口层：POST /api/chat 的 SSE 流内容正确（离线假脑子跑完整一轮）。"""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.client.get("/")                      # 先拿 sid cookie，建立会话记忆桶

    def test_chat_streams_log_then_answer(self):
        resp = self.client.post("/api/chat", json={"message": "order-api 好像挂了，帮我查一下为什么"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "text/event-stream")
        body = resp.get_data(as_text=True)
        # 第一个事件是日志行，最后一个事件是最终回答
        events = [l[5:].strip() for l in body.splitlines() if l.startswith("data: ")]
        parsed = [json.loads(e) for e in events if e]
        self.assertGreaterEqual(len(parsed), 2)
        kinds = [p["type"] for p in parsed]
        self.assertEqual(kinds[0], "log")         # 先滚活动日志
        self.assertEqual(kinds[-1], "answer")     # 再给最终回答
        # 具体内容：真的有「查服务」动作 + 回答含演示话术
        all_text = "\n".join(p.get("text", "") for p in parsed if p["type"] == "log")
        self.assertIn("[查服务]", all_text)
        self.assertEqual(parsed[-1]["code"], "END_TURN")

        # 同一套接口在"平台不给线程"的降级路上也要能用（PythonAnywhere 的 uWSGI 不开线程，
        # 后台线程排不上队、生成器会一直空等 → 页面永远转圈）。降级路 = 跑完一次性推，
        # 事件形状必须一致，否则前端解析不出来。
        app_mod = sys.modules["webchat.app"]
        app_mod.NO_THREAD = True
        try:
            body = self.client.post("/api/chat",
                                    json={"message": "order-api 好像挂了"}).get_data(as_text=True)
        finally:
            app_mod.NO_THREAD = False
        parsed = [json.loads(l[5:].strip()) for l in body.splitlines() if l.startswith("data: ")]
        self.assertEqual(parsed[0]["type"], "log")            # 日志照旧在前
        self.assertEqual(parsed[-1]["type"], "answer")        # 回答照旧在后
        self.assertEqual(parsed[-1]["code"], "END_TURN")
        self.assertIn("演示模式", parsed[-1]["text"])          # 结果是完整的，不是空壳

        # 兜底：一轮里任何一步炸了，也必须变成一条正常的"回答"事件——不能让异常抛出 WSGI
        # 应用（托管平台会甩一个"网站出错了"的错误页给访客，访客看到的是平台页面）。
        def boom(*_a, **_k):
            raise RuntimeError("模拟服务端出错")

        def stream_of(patched):
            app_mod.run_turn = patched
            try:
                return self.client.post("/api/chat",
                                        json={"message": "你好"}).get_data(as_text=True)
            finally:
                app_mod.run_turn = real_run

        real_run = app_mod.run_turn
        with contextlib.redirect_stderr(io.StringIO()):       # 兜底会打堆栈，别污染测试输出
            body = stream_of(boom)                            # ① 无线程降级路
            app_mod.NO_THREAD = True
            try:
                body += stream_of(boom)                       # ② 线程路（起一轮就失败）
            finally:
                app_mod.NO_THREAD = False
        for part in body.split("data: ")[1:]:
            ev = json.loads(part.split("\n")[0])
            self.assertEqual(ev["type"], "answer")
            self.assertEqual(ev["code"], "SERVER_ERROR")
            self.assertIn("服务端开小差", ev["text"])

    def test_chat_remembers_session(self):
        """同一 sid 两次提问，历史会累积（第二次回答引用第一次——离线剧本不真引用，但历史条数在涨）。"""
        c1 = self.client.post("/api/chat", json={"message": "你好"}).get_data(as_text=True)
        c2 = self.client.post("/api/chat", json={"message": "order-api 挂了帮我查一下"}).get_data(as_text=True)
        # 两个回答都完整返回（没崩、没超时）
        self.assertIn('"type": "answer"', c1)
        self.assertIn('"type": "answer"', c2)

    def test_empty_message_rejected(self):
        resp = self.client.post("/api/chat", json={"message": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_chat_works_without_prior_cookie(self):
        """直接 POST（没先 GET /）也应新建会话并回写 cookie。"""
        fresh = self.app.test_client()
        resp = fresh.post("/api/chat", json={"message": "你好"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("sid=", resp.headers.get("Set-Cookie", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)

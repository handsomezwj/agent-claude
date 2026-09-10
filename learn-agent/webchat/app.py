# app.py —— 把完整 agent 包成「像 App 的对话页」的薄壳（webchat 专项）
#
# 薄壳哲学（照 resume-advisor 的分层习惯）：页面只做两件事——
#   1. 给浏览器一张对话页（GET /）
#   2. 接住一条消息，转给 agent_brain 跑一轮完整 agent（工具 + 护栏），
#      再以 SSE 流把「活动日志 → 最终回答」一段段推给页面。
# 所有聪明都在 agent_brain 和它背后被 337 测试护着的 agent-claude 里，这层不加逻辑。
#
# 跑法：
#   python app.py            # 离线假脑子（默认，零成本，页面就能聊）
#   AGENT_WEB_MODE=real python app.py   # 连真模型（用 .env 的 key）
import json
import os
import queue
import threading
import uuid

from flask import Flask, Response, jsonify, make_response, render_template, request

try:                                            # 被测试当包导入（from .agent_brain import …）
    from .agent_brain import QueueSink, run_turn
except ImportError:                             # 直接 python app.py 跑脚本（sys.path 里有本目录）
    from agent_brain import QueueSink, run_turn

MODE = os.environ.get("AGENT_WEB_MODE", "fake").lower()     # fake（默认）/ real
SESSIONS: dict[str, list] = {}                              # sid -> 这段对话的消息历史
MAX_HISTORY = 400                                           # 兜底，防无脑膨胀
TURN_LOCK = threading.Lock()                                # 见 _run_turn_live 注释
_SENTINEL = object()                                        # 队列里的"这轮跑完了"暗号


def _run_turn_live(messages, message):
    """在后台线程里跑一轮完整 agent，日志边跑边进队列。返回 (队列, 结果字典)。

    为什么要加锁串行（TURN_LOCK）：sys.stdout 是**整个进程共用一个水龙头**。
    两轮对话同时跑就会互相抢水龙头——A 的日志可能漏进 B 的页面。Flask 开发服务器
    开了 threaded=True 理论能并发，所以这里用锁把"接管 stdout"这段串起来：一轮跑完
    再跑下一轮。本地演示够用；要真并发，得把 agent 改成"日志走回调、不 print"，
    那是更大的改造（候选的下一步）。
    """
    events: "queue.Queue" = queue.Queue()
    outcome = {}

    def worker():
        with TURN_LOCK:
            try:
                _, reply, code = run_turn(messages, message, mode=MODE,
                                          log_sink=QueueSink(events.put))
                outcome["reply"], outcome["code"] = reply, code
            except Exception as exc:            # 兜底：线程静默死掉页面会白等
                outcome["reply"] = f"（服务端出错：{exc}）"
                outcome["code"] = "SERVER_ERROR"
            finally:
                if len(messages) > MAX_HISTORY:  # 兜底：只留最近一段
                    del messages[:MAX_HISTORY // 2]
                events.put(_SENTINEL)

    threading.Thread(target=worker, daemon=True).start()
    return events, outcome


def create_app():
    app = Flask(__name__)

    def _sid_of(req, resp=None):
        sid = req.cookies.get("sid")
        if not sid:
            sid = uuid.uuid4().hex
            if resp is not None:
                resp.set_cookie("sid", sid, max_age=60 * 60 * 24 * 30)
        SESSIONS.setdefault(sid, [])
        return sid

    @app.get("/")
    def index():
        resp = make_response(render_template("index.html", mode=MODE))
        _sid_of(request, resp)
        return resp

    @app.get("/api/meta")
    def meta():
        return jsonify(mode=MODE)

    @app.post("/api/reset")
    def reset():
        # 「新对话」：清掉这个浏览器在这段会话的记忆，页面重新开聊
        sid = _sid_of(request)
        SESSIONS[sid] = []
        return jsonify(ok=True)

    @app.post("/api/chat")
    def chat():
        data = request.get_json(silent=True) or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify(error="消息是空的"), 400

        # 会话记忆按浏览器 cookie 分桶；没有 sid（比如直接 curl）就新建一个并回写
        sid = request.cookies.get("sid")
        is_new = not sid or sid not in SESSIONS
        if not sid:
            sid = uuid.uuid4().hex
        SESSIONS.setdefault(sid, [])
        messages = SESSIONS[sid]

        # agent 那一轮放到后台线程跑，它的每一行 stdout 立刻进队列；
        # 下面的生成器一边等一边把日志**实时**推给页面（真·一条条滚，不用等整轮结束）。
        events, outcome = _run_turn_live(messages, message)

        def stream():
            while True:
                item = events.get()
                if item is _SENTINEL:
                    break
                yield f"data: {json.dumps({'type': 'log', 'text': item}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'answer', 'text': outcome.get('reply', ''), 'code': outcome.get('code', '')}, ensure_ascii=False)}\n\n"

        resp = Response(stream(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no"})
        if is_new:
            resp.set_cookie("sid", sid, max_age=60 * 60 * 24 * 30)
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    mode_note = "离线假脑子（脚本，零成本）" if MODE == "fake" else "真模型"
    print(f"[webchat] 模式：{mode_note}  →  打开 http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, threaded=True)

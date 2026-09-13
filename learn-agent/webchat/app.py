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
#   AGENT_WEB_NO_THREAD=1 python app.py # 托管平台不给开线程时走降级路（见 NO_THREAD 注释）
import json
import os
import queue
import threading
import traceback
import uuid

from flask import Flask, Response, jsonify, make_response, render_template, request

try:                                            # 被测试当包导入（from .agent_brain import …）
    from .agent_brain import QueueSink, run_turn, warm_up
except ImportError:                             # 直接 python app.py 跑脚本（sys.path 里有本目录）
    from agent_brain import QueueSink, run_turn, warm_up

# .env 由 agent_brain 在导入时统一读（跟 agent-claude 同一份），所以这里 import 完环境已就绪。
MODE = os.environ.get("AGENT_WEB_MODE", "fake").lower()     # fake（默认）/ real
# 端口/网卡：云平台会注入 PORT，这时必须绑 0.0.0.0 才收得到外网请求；
# 本地没给 PORT → 仍是 127.0.0.1:5001，跟以前完全一样。
PORT = int(os.environ.get("PORT", "5001"))
HOST = os.environ.get("HOST") or ("0.0.0.0" if "PORT" in os.environ else "127.0.0.1")
# 有些托管平台的 WSGI 不开线程（PythonAnywhere 的 uWSGI 就是这样，且用户改不了）。
# 那种环境下后台线程排不上队 → 生成器一直空等队列 → 页面永远转圈。设 1 走"降级路"：
# 一轮跑完，日志和回答一次性推给页面（少了逐行滚，但结果正常出）。
NO_THREAD = os.environ.get("AGENT_WEB_NO_THREAD", "").lower() in ("1", "true", "yes")
SESSIONS: dict[str, list] = {}                              # sid -> 这段对话的消息历史
MAX_HISTORY = 400                                           # 兜底，防无脑膨胀
TURN_LOCK = threading.Lock()                                # 见 _run_turn_live 注释
_SENTINEL = object()                                        # 队列里的"这轮跑完了"暗号


def _sse(payload):
    """一条 SSE 事件：data: <json> + 空行结尾（协议要求空行才代表一条事件结束）。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _error_answer(exc):
    """兜底：一轮里任何一步炸了，都把它变成一条**正常回答事件**。

    为什么必须兜：异常要是抛出 WSGI 应用，托管平台会甩一个"网站出错了"的错误页给访客
    （PythonAnywhere 上实测过：新 worker 的第一次聊天就是这样），访客看到的是平台页面，
    既不知道发生了什么、我们也拿不到线索。兜住之后最差也是聊天框里一句"服务端开小差了"。
    同时把完整堆栈打到 stderr —— 平台会把 stderr 收进错误日志，下次一查就知道病根。
    """
    traceback.print_exc()
    return _sse({"type": "answer",
                 "text": f"（服务端开小差了：{exc}）刷新页面再试一次就好。",
                 "code": "SERVER_ERROR"})


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
                outcome["reply"] = f"（服务端开小差了：{exc}）刷新页面再试一次就好。"
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

        # 下面生成器里必须**先**把响应头带上（X-Accel-Buffering: no 是给 nginx 类反代看的：
        # 不加它会攒够一整块才转发，"实时"就没了）
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

        if NO_THREAD:
            # 降级路（无线程平台，见 NO_THREAD 注释）：跑完一轮再一次性推，事件形状跟上面一样。
            # run_turn 放在生成器**里面**跑，且自己 try 住：生成器是等服务器来迭代时才执行的，
            # 写在外面的话这里面的异常照样会冒到平台去（那就白兜了）。
            def stream_once():
                try:
                    logs, reply, code = run_turn(messages, message, mode=MODE)
                except Exception as exc:             # noqa: BLE001 —— 兜底见 _error_answer
                    yield _error_answer(exc)
                    return
                if len(messages) > MAX_HISTORY:
                    del messages[:MAX_HISTORY // 2]
                for line in logs:
                    yield _sse({"type": "log", "text": line})
                yield _sse({"type": "answer", "text": reply, "code": code})

            resp = Response(stream_once(), mimetype="text/event-stream", headers=headers)
        else:
            # agent 那一轮放到后台线程跑，它的每一行 stdout 立刻进队列；
            # 下面的生成器一边等一边把日志**实时**推给页面（真·一条条滚，不用等整轮结束）。
            # 线程里那段的 try 在 _run_turn_live 里（线程一炸页面会白等，必须兜）。
            try:
                events, outcome = _run_turn_live(messages, message)
            except Exception as exc:                 # noqa: BLE001 —— 连"起一轮"都失败了
                resp = Response(iter([_error_answer(exc)]), mimetype="text/event-stream",
                                headers=headers)
                if is_new:
                    resp.set_cookie("sid", sid, max_age=60 * 60 * 24 * 30)
                return resp

            def stream():
                while True:
                    item = events.get()
                    if item is _SENTINEL:
                        break
                    yield _sse({"type": "log", "text": item})
                yield _sse({"type": "answer", "text": outcome.get("reply", ""),
                            "code": outcome.get("code", "")})

            resp = Response(stream(), mimetype="text/event-stream", headers=headers)

        if is_new:
            resp.set_cookie("sid", sid, max_age=60 * 60 * 24 * 30)
        return resp

    return app


app = create_app()


def run_local():
    """前台把服务跑起来（本地开发用）。云上走 gunicorn app:app，不经过这里。"""
    mode_note = "离线假脑子（脚本，零成本）" if MODE == "fake" else "真模型"
    shown = "127.0.0.1" if HOST == "0.0.0.0" else HOST   # 0.0.0.0 不是能打开的地址，提示里换回来
    print(f"[webchat] 模式：{mode_note}  →  打开 http://{shown}:{PORT}")
    app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    run_local()

# agent_brain.py —— 把「完整 agent-claude 主循环」搬进网页的脑子（webchat 专项）
#
# 目标：不重写 agent，把上层目录那个成品 agent-claude.py 当模块 import 进来，
# 复用它那个被 337 个测试护着的 handle_user_turn 主循环（工具 + 护栏全在）。
# 页面只做两件事：把 stdout 里的活动日志接出来（"正在查服务…"）、把最终回答抠出来。
#
# 两种模式（AGENT_WEB_MODE 控制）：
#   fake（默认，零成本离线）：把 agent-claude 里的真 client 换成"按剧本演"的
#       FakeModel —— 脚本说"调 check_service / query_log"，真实离线工具就会真跑
#       （读 ops_demo 的假服务 pid 和假日志），页面看到完整工具日志 + 回答。
#   real：用 .env 里的真 key 连真模型，agent 自己决定调什么工具（跟 CLI 完全一样）。
#
# 页面打字机 = 前端 JS 逐字显示最终回答，所以把 agent 的流式关掉（USE_STREAMING=False），
# 免得它把回答逐字打进 stdout 混进活动日志。
import io
import importlib.util
import os
import sys
from pathlib import Path

# webchat/ 在 learn-agent/ 下：parents[1] = learn-agent，parents[2] = agent-claude.py 所在目录
_LEARN_AGENT = Path(__file__).resolve().parents[1]
AGENT_HOME = Path(__file__).resolve().parents[2]     # 成品 agent 所在目录（app.py 用它找 .env）
_DEFAULT_AGENT_PY = os.environ.get("AGENT_WEB_AGENT",
                                   str(AGENT_HOME / "agent-claude.py"))

# 本地那份配置（.env，跟 agent-claude 同一份）在这里统一读进来，这样 AGENT_WEB_MODE
# 也能写进文件里、不用每次敲命令行。override=False（默认）→ 命令行/平台注入的环境变量优先。
# 云上通常没有这个文件 → 空操作，全靠平台的环境变量。
try:
    from dotenv import load_dotenv
except ImportError:                              # 没装 python-dotenv 也能跑，只是不能写进 .env
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv(AGENT_HOME / ".env")


def _ensure_learn_agent_on_path():
    """brain 要借 learn-agent 里的 FakeModel（agent_loop.py）当离线替身。"""
    if str(_LEARN_AGENT) not in sys.path:
        sys.path.insert(0, str(_LEARN_AGENT))


# ---------------------- 成品 agent 当模块加载（只跑一次） ----------------------

_AC = None   # 缓存的 agent-claude 模块


def _load_agent_module():
    """用 importlib 按路径把 agent-claude.py 加载成模块（文件名带连字符不能直接 import）。

    加载会执行它的模块级代码：读 .env（真 key 在这台机器上）、建真 client。
    之后我们按模式覆写两个全局：client（fake 时换成假模型）、USE_STREAMING（关流式）。

    云上没有 .env、没有 key：实测 anthropic SDK 允许 api_key=None 建 client（只在真发请求时
    才报错），而 fake 模式压根不发请求，所以页面照常起、照常聊，不需要给假 key。
    """
    global _AC
    if _AC is not None:
        return _AC
    spec = importlib.util.spec_from_file_location("ac_web", _DEFAULT_AGENT_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"找不到成品 agent：{_DEFAULT_AGENT_PY}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ac_web"] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        raise RuntimeError(f"加载 {_DEFAULT_AGENT_PY} 失败：{exc}") from exc
    # 运行时覆写：
    mod.USE_STREAMING = False   # 打字机让页面 JS 做，模型别逐字打进 stdout
    # ACTIVE_TOOLS 只在 connect_mcp() 里初始化（不连 MCP 就没有）→ 这里用内置 TOOLS 兜底
    if not getattr(mod, "ACTIVE_TOOLS", None):
        mod.ACTIVE_TOOLS = list(mod.TOOLS)
    _AC = mod
    return _AC


def warm_up():
    """预热：提前把成品 agent 模块加载好。

    云上冷启动的 worker 里，第一次聊天要当场做这一整串重活（agent-claude + learn-agent
    一整条 import 链），实测那一下最容易出问题（PythonAnywhere 免费版每个新 worker 的
    第一次聊天会返回平台错误页，之后就正常了）。放到启动时做，等于把"第一次请求的风险"
    换成"开机慢一秒"。

    失败不抛错：预热只是优化，不该拦住服务起不来。
    """
    try:
        _load_agent_module()
        return True
    except Exception as exc:                        # noqa: BLE001 —— 预热失败不算致命
        print(f"[webchat] 预热失败（不影响启动，第一次聊天会现加载）：{exc}")
        return False


# ---------------------- 离线剧本（fake 模式的"假脑子"） ----------------------

def _fake_model_for(message):
    """按用户的话挑一段剧本，换成"会演工具调用的假模型"。

    FakeModel 是被动剧本机：create() 一次吐一个 FakeResponse。
    真正驱动循环的是 agent-claude 的 handle_user_turn —— 它读到 tool_use 就去
    执行真工具（离线工具读 ops_demo 假数据），再把结果喂回下一轮。
    所以剧本只要写：先调两个工具 → 再说一段话收尾。
    """
    _ensure_learn_agent_on_path()
    from agent_loop import FakeModel, FakeResponse, tool_block, text_block

    if any(k in message for k in ("删", "杀", "重启", "清空", "干掉", "rm ", "rm -rf")):
        # 护栏场景：让 agent 去删日志 → 真实 run_command 护栏拒绝 → 收尾话术。
        # 路演记忆点：「面试官叫它删日志，它拒绝」。
        script = [
            FakeResponse("tool_use", [
                tool_block("run_command", {"command": "del app.log"}),
            ]),
            FakeResponse("end_turn", [text_block(
                "（演示模式 · 护栏话术）我刚想执行 del app.log 帮你删日志，"
                "但被安全护栏当场拦下了——\n\n"
                "[安全护栏] 拒绝执行破坏性命令：del（删除类操作一律拒绝，需人工确认）。\n"
                "\n"
                "运维助手只做只读诊断：查服务、查日志可以，删文件/杀进程/重启"
                "这类破坏性操作无论谁叫都不做，必须由人工确认后手动执行。\n"
                "真模型下这条规则同样生效——命令黑名单在工具层拦截，模型想绕也绕不过。")]),
        ]
    elif any(k in message for k in ("挂了", "排查", "查一下", "服务", "日志", "order-api",
                                    "api", "为什么", "down")):
        # 排障场景：check_service + query_log（都是离线真工具）→ 收尾总结
        script = [
            FakeResponse("tool_use", [
                tool_block("check_service", {"service_name": "order-api"}),
                tool_block("query_log", {"service_name": "order-api",
                                         "keyword": "ERROR"}),
            ]),
            FakeResponse("end_turn", [text_block(
                "（演示模式 · 脚本话术，零成本离线）\n"
                "我查了 order-api 的两类证据：\n"
                "· 服务状态：停止（pid 文件不存在）\n"
                "· 日志 ERROR：database connection pool exhausted —— 连接池耗尽\n"
                "\n"
                "结论：服务疑似因连接池被打满后崩溃。\n"
                "真模型模式（AGENT_WEB_MODE=real）会基于真实日志继续分析根因并给修复建议。")]),
        ]
    else:
        # 普通问答：一句收尾，演示页面能打字机
        script = [FakeResponse("end_turn", [text_block(
            "（演示模式 · 脚本话术）这是离线假脑子按剧本回的。\n"
            "想看我真调工具？发一句「order-api 好像挂了帮我查一下」；"
            "想连真模型就把环境变量 AGENT_WEB_MODE 设成 real。")])]
    return FakeModel(script)


class QueueSink:
    """一个"像文件一样可写"的替身：agent 每打一行日志，就立刻交给 emit 回调。

    页面用它做**真·实时**滚动——agent 跑到哪，日志就滚到哪，不用等整轮跑完。
    行为对齐 _activity_lines：空行丢掉；碰到 "[Agent回答]" 就封口
    （最终回答走返回值、由页面打字机打，不混进活动日志）。
    """

    def __init__(self, emit):
        self._emit = emit
        self._buf = ""
        self._sealed = False

    def write(self, text):
        if self._sealed:
            return len(text)
        self._buf += text
        while "\n" in self._buf:            # print 可能把一行拆成几次 write，攒够整行再发
            line, self._buf = self._buf.split("\n", 1)
            self._push(line)
        return len(text)

    def flush(self):
        pass

    def _push(self, line):
        if self._sealed:
            return
        line = line.rstrip()
        if not line:
            return
        if line.startswith("[Agent回答]"):
            self._sealed = True             # 后面是最终回答 + 裁判打分，不归日志管
            return
        self._emit(line)


# ---------------------- 一轮对话（页面调这个） ----------------------

def run_turn(messages, user_message, mode=None, log_sink=None):
    """跑一轮完整对话：agent 主循环（可含多次工具调用），直到它给最终回答。

    参数 log_sink（可选）：一个"像文件一样可写"的对象（见 QueueSink）。给了它，
    活动日志就**边跑边写进去**（页面靠这个做实时滚动），返回的 logs 为空列表；
    不给就照旧攒在内存里、跑完一次性返回。

    返回 (logs, reply, code)：
      logs   stdout 里的活动日志（"正在查服务…"之类），按行拆成列表
      reply  最终回答文本（页面打字机用）
      code   handle_user_turn 的收尾码：END_TURN / STUCK / MAX_ITERS / API_ERROR
    """
    ac = _load_agent_module()
    real = (mode or os.environ.get("AGENT_WEB_MODE", "fake")).lower() == "real"

    if not real:
        ac.client = _fake_model_for(user_message)   # 假脑子：按剧本演

    messages.append({"role": "user", "content": user_message})

    # 包一层 stdout 捕获：agent 里 execute_tool / call_multiagent 会把活动打进 stdout
    live = log_sink is not None
    buf = None if live else io.StringIO()
    old = sys.stdout
    sys.stdout = log_sink if live else buf
    try:
        code = ac.handle_user_turn(messages)
    finally:
        sys.stdout = old
        if live:
            try:
                log_sink.flush()
            except Exception:
                pass

    logs = [] if live else _activity_lines(buf.getvalue())
    reply = _extract_last_reply(messages, code)
    return logs, reply, code


def _activity_lines(raw):
    """把捕获的 stdout 拆成日志行：去掉空行，砍掉结尾的「[Agent回答]」大段。"""
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    cut = 0
    for i, ln in enumerate(lines):
        if ln.startswith("[Agent回答]"):
            cut = i          # 从这句起是最终回答，不走日志走打字机
            break
    else:
        cut = len(lines)
    return lines[:cut]


def _extract_last_reply(messages, code):
    """从消息历史里抠出最近一条"带了文字"的助手回答（跳过 tool_use 中间轮）。

    content 里的块是对象（离线 FakeBlock / 真 SDK block），用属性访问，不假设是 dict。
    """
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, list):
            parts = [getattr(b, "text", "")
                     for b in content if getattr(b, "type", "") == "text"]
            text = "\n".join(p for p in parts if p.strip())
            if text.strip():
                return text.strip()
    # 不是正常 END_TURN（护栏介入等）就明说，别让页面空白
    return f"（这轮没给出正常回答，护栏收尾：{code}）"

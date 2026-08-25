"""
Claude-powered interactive AI Agent — converted from DashScope/Qwen to Anthropic SDK.

Usage:
  1. pip install anthropic python-dotenv
  2. 复制 .env.example 为 .env 并填入你的 API 配置
  3. python agent-claude.py
"""

import os
import sys
import subprocess
import json
import shlex
import urllib.request
import ssl
from html.parser import HTMLParser
from pathlib import Path

import anthropic
from anthropic.types import (
    MessageParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlock,
    TextBlock,
)
from dotenv import load_dotenv

# --- Windows GBK 编码修复 ---
# 设置标准输出为 UTF-8，避免 emoji 等字符导致 UnicodeEncodeError
if sys.platform == "win32":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", buffering=1)
    sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", errors="replace", buffering=1)

# 从脚本所在目录加载 .env，确保无论从哪里运行都能找到
load_dotenv(Path(__file__).parent / ".env")

# 复用"被测试过"的护栏逻辑（learn-agent/spin_guard.py，被 508 个检查保护）。
# 生产项目里 spin_guard 应该是一个独立包；课程里先直接借课程目录的。
sys.path.insert(0, str(Path(__file__).parent / "learn-agent"))
from spin_guard import make_fingerprint, track_repeat
from context import trim_history
from llm_judge import judge_answer
from summarize import replace_with_summary
from streaming import run_stream
from mcp_client import McpClient, StdioTransport
from rag import chunk_text, retrieve_top_k as keyword_retrieve
from embedding import BowEmbedder, build_vocab, retrieve_top_k as embed_retrieve
from embedding_models import try_load_model, REAL_MIN_SIM
from memory_store import MemoryStore, build_memory_prompt, remember_last_turn
from itops_guard import guard_command, load_service_registry, check_service_status, read_log_safely

# ---------------------------------------------------------------------------
# Client — 与 Claude Code 使用相同的环境变量
# ---------------------------------------------------------------------------

client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
)

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
MAX_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", "16000"))
# DeepSeek 等第三方端点可能不支持 thinking，通过环境变量控制
USE_THINKING = os.environ.get("ANTHROPIC_USE_THINKING", "false").lower() == "true"

# --- 护栏（第三、四课）：兜底圈数 + 打转阈值 ---
MAX_ITERS = 6       # 一轮最多 6 圈，第 7 圈检查就拦住，不白打
MAX_REPEATS = 3     # 同一工具 + 同样参数连用 3 次 = 打转，刹车

# --- 上下文护栏（第十课）：每次发 API 前，把输入裁到预算以内 ---
# 预留 16000 给输出 + 一点给 system/tools，剩下的才是输入能占的。
CONTEXT_BUDGET = 40000

# --- 裁判护栏（第九课）：这轮回答完，请一台 LLM 打分（可关：CLAUDE_USE_JUDGE=false）---
USE_JUDGE = os.environ.get("CLAUDE_USE_JUDGE", "true").lower() == "true"

# --- 摘要护栏（第十一课）：超预算时把最老对话压成摘要，而不是纯扔掉（可关：CLAUDE_USE_SUMMARY=false）---
USE_SUMMARY = os.environ.get("CLAUDE_USE_SUMMARY", "true").lower() == "true"

# --- 流式输出（第十四课）：边生成边打字机吐字，不憋一口气（可关：CLAUDE_USE_STREAMING=false）---
USE_STREAMING = os.environ.get("CLAUDE_USE_STREAMING", "true").lower() == "true"

# --- MCP 工具接入（第十五课）：工具不写死在代码里，问一个独立小程序要（可关：CLAUDE_USE_MCP=false）---
# 配了 CLAUDE_MCP_SERVER（一条启动服务器的命令）才去连；连不上就优雅降级，只用内置工具。
USE_MCP = os.environ.get("CLAUDE_USE_MCP", "true").lower() == "true"
MCP_SERVER_COMMAND = os.environ.get("CLAUDE_MCP_SERVER", "").strip()

# --- RAG 检索增强（第十六课）：提问前先在你自己的知识库里"检索最相关的几段"再回答 ---
# 默认读 learn-agent/knowledge.md；可用 CLAUDE_RAG_FILE 指定别的文件；CLAUDE_USE_RAG=false 可关。
USE_RAG = os.environ.get("CLAUDE_USE_RAG", "true").lower() == "true"
CLAUDE_RAG_FILE = os.environ.get("CLAUDE_RAG_FILE", "").strip()
RAG_TOP_K = int(os.environ.get("CLAUDE_RAG_TOP_K", "2"))
RAG_CHUNK_SIZE = int(os.environ.get("CLAUDE_RAG_CHUNK_SIZE", "200"))
RAG_CHUNKS: list[str] = []   # 加载好的知识块；空 = RAG 没开
# --- 向量检索（第十七课）：默认开。把文字变向量、按余弦相似度找最像的块，比关键词打分更准。
# 本地用"词袋向量"当假门（免费可复现）；起不来就优雅降级回第十六课的关键词打分。
USE_EMBEDDING = os.environ.get("CLAUDE_USE_EMBEDDING", "true").lower() == "true"
RAG_EMBEDDER = None            # BowEmbedder 或 ModelEmbedder 实例；None = 用关键词打分
RAG_CHUNK_VECTORS: list = []   # 启动时算好每块的向量，提问时不再重算
# --- 真向量模型（第十八课）：配了 CLAUDE_EMBEDDING_MODEL（如 BAAI/bge-small-zh-v1.5）
# 就把检索从"词袋假门"升级成"真模型语义检索"。首次会下载 ~100MB，之后离线可用；
# 加载失败自动回退假门，绝不崩。真模型没有"正好 0"，阈值要抬高（REAL_MIN_SIM）。
CLAUDE_EMBEDDING_MODEL = os.environ.get("CLAUDE_EMBEDDING_MODEL", "").strip()
RAG_MIN_SIM = 0.0              # 词袋假门用 0（撞不上 = 0）；真模型用 REAL_MIN_SIM

# --- 长记忆（第二十一课）：把重要的事写进"记事本"文件，下次启动还记得（可关：CLAUDE_USE_MEMORY=false）
# 模型失忆（第一课）、messages 只活在内存里，程序一关就清零——记事本把"关于用户的
# 事实"落盘到 JSON 文件，启动时读回来贴进 system prompt。文件放在 agent-claude.py
# 旁边而不是 learn-agent/ 里，免得课程目录被用户隐私污染、误提交到 GitHub。
USE_MEMORY = os.environ.get("CLAUDE_USE_MEMORY", "true").lower() == "true"
MEMORY_FILE = os.environ.get("CLAUDE_MEMORY_FILE", "").strip() or str(
    Path(__file__).parent / "agent_memory.json"
)
MEMORY_MAX_ITEMS = int(os.environ.get("CLAUDE_MEMORY_MAX_ITEMS", "50"))

# --- IT 运维助手（第二十二课）：只读诊断 + 破坏性命令安全护栏（可关：CLAUDE_USE_IT_OPS=false）
# 真实业务场景：查服务状态、查日志找故障现场，但删除/重启/杀进程一律拒绝。
# 数据目录默认 learn-agent/ops_demo（假服务 + 假日志），可用 CLAUDE_OPS_DATA_DIR 指定。
USE_IT_OPS = os.environ.get("CLAUDE_USE_IT_OPS", "true").lower() == "true"
OPS_DATA_DIR = os.environ.get("CLAUDE_OPS_DATA_DIR", "").strip() or str(
    Path(__file__).parent / "learn-agent" / "ops_demo"
)

MEMORY: MemoryStore | None = None   # 记事本实例；None = 记忆没开


# --- 清理非法 surrogate 字符 ---
def sanitize(obj):
    """递归移除对象中的 lone surrogate 字符，防止 UTF-8 编码失败"""
    if isinstance(obj, str):
        return obj.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj

# ---------------------------------------------------------------------------
# Skill loader (reusable — unchanged from original)
# ---------------------------------------------------------------------------

SKILLS_DIR = Path(__file__).parent / "skills"


class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._skills: dict[str, str] = {}
        self._descriptions: list[str] = []
        self._load_all()

    def _load_all(self):
        if not self.skills_dir.exists():
            return
        for skill_file in sorted(self.skills_dir.glob("*.md")):
            name = skill_file.stem
            content = skill_file.read_text(encoding="utf-8")
            self._skills[name] = content
            first_line = next(
                (l.strip("# ").strip() for l in content.splitlines() if l.strip()), ""
            )
            self._descriptions.append(f"- {name}: {first_line}")

    def get_descriptions(self) -> str:
        return "\n".join(self._descriptions) if self._descriptions else "（暂无可用技能）"

    def get_content(self, skill_name: str) -> str:
        return self._skills.get(
            skill_name, f"未找到技能「{skill_name}」，请检查技能名称。"
        )


SKILL_LOADER = SkillLoader(SKILLS_DIR)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = f"""
你是 lcc,一个 太监。你必须始终使用中文进行回复。

重要规则：
1. 所有回答必须使用中文，包括思考过程和技术术语
2. 遇到不熟悉的专题时，请先调用 load_skill 工具加载对应的知识，再给出回答
3. 保持回答简洁、准确、有帮助
4. 遇到服务/日志/运维类问题，优先用 check_service / query_log 做只读排查；删除、重启、杀进程类操作一律拒绝，需人工确认

当前可用技能：
{SKILL_LOADER.get_descriptions()}"""

# ---------------------------------------------------------------------------
# Anthropic-format tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[ToolParam] = [
    {
        "name": "run_command",
        "description": "在终端执行一条 shell 命令并返回输出",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令",
                }
            },
            "required": ["command"],
        },
    },
    {
        "name": "web_fetch",
        "description": "获取指定 URL 的网页内容，支持文本提取模式",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要访问的完整 URL",
                },
                "extract_mode": {
                    "type": "string",
                    "description": "提取模式: text (纯文本, 默认) 或 raw (原始 HTML)",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "最大返回字符数，默认 8000",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "load_skill",
        "description": "加载指定技能的详细知识内容，在回答相关问题前调用",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "技能名称，必须是系统提示中列出的可用技能之一",
                }
            },
            "required": ["skill_name"],
        },
    },
]

# 第二十二课：IT 运维业务工具（只读诊断 + 安全护栏；可关：CLAUDE_USE_IT_OPS=false）
if USE_IT_OPS:
    TOOLS += [
        {
            "name": "check_service",
            "description": "检查一个服务的运行状态（只读）：运行中/停止/未知服务，含 pid 和端口",
            "input_schema": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "要检查的服务名，如 order-api",
                    }
                },
                "required": ["service_name"],
            },
        },
        {
            "name": "query_log",
            "description": "查询服务的日志（只读），可按关键词过滤，返回带行号的最近若干行",
            "input_schema": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "要查日志的服务名，如 order-api",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "过滤关键词（忽略大小写），如 ERROR、CRITICAL；留空则返回最近日志",
                    },
                    "tail_lines": {
                        "type": "integer",
                        "description": "最多返回几行，默认 20，上限 100",
                    },
                },
                "required": ["service_name"],
            },
        },
    ]

# 第十五课：MCP 连上后，把外部工具加进这份"实际发给模型的清单"。
# 默认就是内置工具；connect_mcp() 连上服务器后替换成 内置 + 外部。
ACTIVE_TOOLS: list[ToolParam] = list(TOOLS)
MCP_CLIENT: McpClient | None = None
MCP_TOOL_NAMES: set[str] = set()

# ---------------------------------------------------------------------------
# HTML text extractor (unchanged from original)
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "aside"):
            self._skip_depth += 1
        elif tag in (
            "br", "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "pre",
        ):
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "aside"):
            self._skip_depth -= 1
        elif tag in (
            "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "pre",
        ):
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        text = "".join(self._chunks)
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def web_fetch(url: str, extract_mode: str = "text", max_chars: int = 8000) -> str:
    """Fetch a URL and extract text or raw HTML.  Uses proper SSL verification."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.0"
                )
            },
        )
        # Proper SSL verification (no CERT_NONE override)
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")

        if extract_mode == "raw":
            return raw[:max_chars]

        extractor = _TextExtractor()
        extractor.feed(raw)
        return extractor.get_text()[:max_chars]
    except Exception as exc:
        return f"获取网页失败: {exc}"


def run_command(command: str) -> str:
    """Execute a shell command.  Uses shell=False with shlex splitting for safety.
    Falls back to shell=True only for commands with shell operators (|, >, <, &&, etc.).
    """
    # 第二十二课：只读安全护栏——破坏性命令（删/杀/重启/写文件）一律拒绝，不执行
    allowed, reason = guard_command(command)
    if not allowed:
        return (
            f"[安全护栏] 拒绝执行破坏性命令：{reason}。"
            f"运维助手只做只读诊断，删除/重启/杀进程类操作需人工确认后手动执行。"
        )
    shell_operators = {"|", ">", "<", "&", ";", "$(", "`"}
    needs_shell = any(op in command for op in shell_operators)

    if needs_shell:
        # Commands with pipes/redirects still need shell=True — use with caution
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
    else:
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = [command]
        try:
            result = subprocess.run(argv, shell=False, capture_output=True, text=True)
        except FileNotFoundError:
            result = subprocess.run(command, shell=True, capture_output=True, text=True)

    return result.stdout or result.stderr


def check_service(service_name: str) -> str:
    """检查一个服务的运行状态（只读）。照 run_command 模式：异常吞成字符串。"""
    try:
        base = Path(OPS_DATA_DIR)
        registry = load_service_registry(base)
        return check_service_status(service_name, registry, base)
    except Exception as exc:
        return f"检查服务失败: {exc}"


def query_log(service_name: str, keyword: str = "", tail_lines: int = 20) -> str:
    """查询服务日志（只读），可按关键词过滤。照 run_command 模式：异常吞成字符串。"""
    try:
        base = Path(OPS_DATA_DIR)
        registry = load_service_registry(base)
        if service_name not in registry:
            return f"未知服务：{service_name}"
        log_rel = registry[service_name].get("log_file", "app.log")
        return read_log_safely(log_rel, base, keyword=keyword, tail_lines=tail_lines)
    except Exception as exc:
        return f"查询日志失败: {exc}"


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def execute_tool(name: str, args: dict) -> str:
    """Route a tool-use block to the correct implementation and return its result."""
    # 第十五课：如果是 MCP 服务器提供的工具，交给它执行
    if MCP_CLIENT is not None and name in MCP_TOOL_NAMES:
        print(f"[MCP工具]: {name}({args})")
        return MCP_CLIENT.call_tool(name, args)
    if name == "run_command":
        command = args["command"]
        print(f"[执行命令]: {command}")
        output = run_command(command)
        print(f"[命令输出]: {output}")
        return output

    elif name == "web_fetch":
        url = args["url"]
        mode = args.get("extract_mode", "text")
        max_chars = args.get("max_chars", 8000)
        print(f"[网页获取]: {url}")
        output = web_fetch(url, mode, max_chars)
        print(f"[网页内容]: {output[:200]}...")
        return output

    elif name == "load_skill":
        skill_name = args["skill_name"]
        print(f"[加载技能]: {skill_name}")
        output = SKILL_LOADER.get_content(skill_name)
        print(f"[技能内容]: {output[:200]}...")
        return output

    elif name == "check_service":
        service_name = str(args.get("service_name", ""))
        print(f"[查服务]: {service_name}")
        output = check_service(service_name)
        print(f"[服务状态]: {output}")
        return output

    elif name == "query_log":
        service_name = str(args.get("service_name", ""))
        keyword = str(args.get("keyword", ""))
        try:
            tail_lines = int(args.get("tail_lines", 20))
        except (TypeError, ValueError):
            tail_lines = 20
        print(f"[查日志]: {service_name} keyword={keyword!r}")
        output = query_log(service_name, keyword, tail_lines)
        print(f"[日志内容]: {output[:200]}...")
        return output

    else:
        return f"Error: Unknown tool '{name}'"


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------


def connect_mcp():
    """第十五课：启动时问 MCP 服务器"你有什么工具"，把它的工具加进清单。

    优雅降级：服务器连不上 / 握手失败，就打一行日志，继续用内置工具——
    绝不让 agent 崩。这就是 resume-advisor 那课学过的"优雅降级 ≠ 静默吞错"。
    """
    global ACTIVE_TOOLS, MCP_CLIENT, MCP_TOOL_NAMES
    if not (USE_MCP and MCP_SERVER_COMMAND):
        return
    try:
        client = McpClient(StdioTransport(MCP_SERVER_COMMAND))
        client.handshake()
        mcp_tools = client.list_tools()
        MCP_CLIENT = client
        MCP_TOOL_NAMES = {t["name"] for t in mcp_tools}
        ACTIVE_TOOLS = TOOLS + mcp_tools
        print(f"[MCP] 连上服务器，新增外部工具：{sorted(MCP_TOOL_NAMES)}")
    except Exception as exc:
        print(f"[MCP] 连接失败，只用内置工具：{exc}")
        MCP_CLIENT = None
        MCP_TOOL_NAMES = set()
        ACTIVE_TOOLS = list(TOOLS)


def connect_rag():
    """第十六课：启动时加载你的知识库，切好块。之后提问前会先检索再回答。

    优雅降级：没找到文件 / 读失败，就打一行日志，等于 RAG 没开，照常聊天。
    """
    global RAG_CHUNKS, RAG_EMBEDDER, RAG_CHUNK_VECTORS, RAG_MIN_SIM
    if not USE_RAG:
        return
    path = CLAUDE_RAG_FILE or str(Path(__file__).parent / "learn-agent" / "knowledge.md")
    if not os.path.exists(path):
        print(f"[RAG] 没找到知识库 {path}，跳过（可用 CLAUDE_RAG_FILE 指定别的文件）")
        return
    try:
        text = Path(path).read_text(encoding="utf-8")
        RAG_CHUNKS = chunk_text(text, RAG_CHUNK_SIZE)
        print(f"[RAG] 已加载知识库（{len(text)} 字 → {len(RAG_CHUNKS)} 块），提问时会先检索最相关的 {RAG_TOP_K} 块")
    except Exception as exc:
        print(f"[RAG] 加载失败，跳过：{exc}")
        RAG_CHUNKS = []
        return
    # 第十七课：默认升级成向量检索（词袋假向量，免费可复现）；起不来就降级回关键词打分
    if USE_EMBEDDING:
        try:
            vocab = build_vocab(RAG_CHUNKS)
            RAG_EMBEDDER = BowEmbedder(vocab)
            RAG_CHUNK_VECTORS = [RAG_EMBEDDER.embed(c) for c in RAG_CHUNKS]
            RAG_MIN_SIM = 0.0
            print(f"[RAG] 检索方式：向量余弦相似度（本地词袋向量，免费）")
        except Exception as exc:
            print(f"[RAG] 向量检索没起来，回退关键词打分：{exc}")
            RAG_EMBEDDER = None
            RAG_CHUNK_VECTORS = []
            return
        # 第十八课：配了真模型就换真门（语义检索，番茄能搜到西红柿）；换不上保持假门
        if CLAUDE_EMBEDDING_MODEL and RAG_EMBEDDER is not None:
            real, err = try_load_model(CLAUDE_EMBEDDING_MODEL)
            if real is not None:
                RAG_EMBEDDER = real
                RAG_CHUNK_VECTORS = [real.embed(c) for c in RAG_CHUNKS]
                RAG_MIN_SIM = REAL_MIN_SIM
                print(f"[RAG] 检索方式已升级：真向量模型 {CLAUDE_EMBEDDING_MODEL}（{real.dim} 维，语义检索）")
            else:
                print(f"[RAG] 真模型加载失败，保持词袋假门：{err}")


def connect_memory():
    """第二十一课：启动时打开"记事本"，把以前存的事实读回来。

    优雅降级：文件坏 / 读不了 → 空记忆照常聊，绝不让 agent 崩。
    记事本打不开就这轮先不记（MEMORY = None），记忆是身外之物，命是主循环。
    """
    global MEMORY
    if not USE_MEMORY:
        return
    try:
        MEMORY = MemoryStore(MEMORY_FILE, max_items=MEMORY_MAX_ITEMS)
        n = len(MEMORY.load())
        print(f"[记忆] 记事本已打开（{n} 条旧记忆，存于 {MEMORY_FILE}）")
    except Exception as exc:
        print(f"[记忆] 打开失败，这轮先不记：{exc}")
        MEMORY = None


def build_system_text():
    """system prompt + 长期记忆（第二十一课）。

    记忆不是贴在 messages 里——system 每次发 API 都会被带上一份，
    所以模型"一开场就知道你是谁"。记忆在 store 里，改一条，下一轮自动生效。
    """
    if MEMORY is None or not MEMORY.all():
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + "\n\n" + build_memory_prompt(MEMORY.all())


def _call_model(kwargs):
    """调一次模型：流式开 → 打字机逐字打；流式关 → 憋一次再打。

    两条路都返回"完整 response"（stop_reason/content 一个不少）——
    所以后面的护栏判断一行都不用改，这就是 get_final_message 的福利。
    """
    if not USE_STREAMING:
        return client.messages.create(**kwargs)
    reply, response = run_stream(
        lambda: client.messages.stream(**kwargs),
        on_chunk=lambda text: print(text, end="", flush=True),
    )
    print()  # 流式结束后补一个换行
    return response


def handle_user_turn(messages):
    """处理一轮用户输入，直到模型给出最终回答或护栏介入。

    返回值：这轮怎么结束的（"END_TURN" / "STUCK" / "MAX_ITERS" / "API_ERROR" / "OTHER"）。
    抽成函数的原因：给循环一个"门"，它才能被假模型驱动、被测试驱动（第八课）。
    """
    turn = 0
    last_call = None      # 打转护栏：上一道菜长什么样
    repeat_count = 0

    while True:
        turn += 1
        if turn > MAX_ITERS:   # 兜底护栏：第 7 圈检查就拦住，不白打
            print("[护栏] 绕了太多圈，请换个说法再试。")
            return "MAX_ITERS"

        # 上下文护栏：messages 无脑累积，这里每次发出去前先裁到预算以内
        # （只丢最老的消息、永远保住最后一条；不改动 messages 本体）
        trimmed = trim_history(messages, CONTEXT_BUDGET)
        kwargs = dict(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=build_system_text(),   # 第二十一课：system prompt + 长期记忆
            tools=ACTIVE_TOOLS,   # 第十五课：内置工具 + 可能连上的 MCP 外部工具
            messages=sanitize(trimmed),
        )
        if USE_THINKING:
            kwargs["thinking"] = {"type": "adaptive"}

        try:
            response = _call_model(kwargs)
        except Exception as exc:
            err = str(exc)
            # DeepSeek 等端点不支持的参数，自动去掉 thinking 后重试
            if "thinking" in err and USE_THINKING:
                print(f"[提示] thinking 参数不被支持，自动关闭后重试...")
                kwargs.pop("thinking", None)
                response = client.messages.create(**kwargs)
            else:
                print(f"[API 错误]: {err}")
                return "API_ERROR"

        # Check stop reason
        if response.stop_reason == "end_turn":
            # Claude is done — print its text and return to next user turn
            text_blocks = [
                b.text for b in response.content if b.type == "text"
            ]
            reply = "\n".join(text_blocks)
            # 流式开：文字已一边生成一边打印；流式关：这里一次性打出来
            if not USE_STREAMING:
                print(f"[Agent回答]: {reply}\n")
            messages.append({
                "role": "assistant",
                "content": response.content,
            })
            return "END_TURN"

        if response.stop_reason == "tool_use":
            # Claude wants to call tools
            tool_use_blocks: list[ToolUseBlock] = [
                b for b in response.content if b.type == "tool_use"
            ]

            # Record the assistant turn with its tool_use content
            messages.append({
                "role": "assistant",
                "content": response.content,
            })

            # Execute each tool and collect results
            tool_results: list[ToolResultBlockParam] = []
            stuck = False
            for tool_block in tool_use_blocks:
                # 打转护栏：同一工具 + 同样参数连用 MAX_REPEATS 次 = 刹车
                this_call = make_fingerprint(tool_block.name, tool_block.input)
                repeat_count, stuck_now = track_repeat(
                    last_call, repeat_count, this_call, MAX_REPEATS
                )
                last_call = this_call

                if stuck_now:
                    print(f"[护栏] 检测到打转：连续 {MAX_REPEATS} 次调用 {tool_block.name}")
                    stuck = True
                    break

                result = execute_tool(tool_block.name, tool_block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result,
                })

            if stuck:
                # 打转 → 不把结果喂回去，直接刹车
                print("[护栏] 我在原地打转，请换个说法再试。")
                return "STUCK"

            # Send tool results back to Claude
            messages.append({"role": "user", "content": tool_results})
            # Loop continues — Claude will process the tool results

        else:
            # Other stop reasons (max_tokens, stop_sequence, etc.)
            # are treated as end-turn — just print what we have
            text_blocks = [
                b.text for b in response.content if b.type == "text"
            ]
            reply = "\n".join(text_blocks)
            if not USE_STREAMING:
                if reply:
                    print(f"[Agent回答]: {reply}\n")
                print(f"(stop_reason: {response.stop_reason})")
            messages.append({
                "role": "assistant",
                "content": response.content,
            })
            return "OTHER"


def judge_last_turn(messages):
    """第九课的裁判：这轮回答完了，请一台 LLM 给回答打 0-5 分（质量护栏）。

    只做最朴素的事：抽出"最近的问题 + 最近的回答"，请裁判打分。
    打不出分（模型跑了、格式跑偏）就优雅降级，绝不让主循环崩。
    返回分数；打不出来返回 None。
    """
    # 最近的问题是"最后一条纯文本 user 消息"（工具循环的 tool_result 不算）
    task = next(
        (m["content"] for m in reversed(messages)
         if m.get("role") == "user" and isinstance(m.get("content"), str)),
        "",
    )
    # 最近的回答是"最后一条带文字的 assistant 消息"
    reply = ""
    for m in reversed(messages):
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        texts = (
            [b.text for b in content if getattr(b, "type", None) == "text"]
            if isinstance(content, list) else []
        )
        if texts:
            reply = "\n".join(texts)
            break
    if not task or not reply:
        return None
    try:
        score, judge_text = judge_answer(client, task, reply)
        print(f"[裁判] 这轮回答 {score}/5 → {judge_text[:60]}")
        return score
    except Exception as exc:
        print(f"[裁判] 打分失败，跳过：{exc}")
        return None


def main():
    # Conversation history — Anthropic format uses content blocks
    messages: list[MessageParam] = []

    # 启动诊断：打印实际加载的配置，方便排查问题
    print(f"=== 配置诊断 ===")
    print(f"Token    : {os.environ.get('ANTHROPIC_AUTH_TOKEN', '(未设置)')[:20]}...")
    print(f"Base URL : {os.environ.get('ANTHROPIC_BASE_URL', '(未设置)')}")
    print(f"================")
    print(f"Claude Agent 就绪 (模型: {MODEL})")
    print("输入消息与 Claude 对话，Ctrl+C 退出\n")

    # 第十五课：问 MCP 服务器要外部工具（连不上就优雅降级，只用内置工具）
    connect_mcp()

    # 第十六课：加载知识库、切好块（没找到就优雅降级，等于没开 RAG）
    connect_rag()

    # 第二十一课：打开"记事本"，把以前存的事实读回来（打不开就这轮先不记）
    connect_memory()

    while True:
        try:
            user_input = input("你：")
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break

        if not user_input.strip():
            continue

        # 第十六课：先在你自己的知识库里检索最相关的几块，塞在问题前面。
        # 注意顺序：资料块必须在真问题【之前】——裁判护栏认"最后一条用户消息"是任务，
        # 检索结果放前面才不会把"资料"当成要打分的那道题。
        # 第十七课：默认用向量检索（词袋假向量，免费）；起不来就回退关键词打分。
        if RAG_CHUNKS:
            if RAG_EMBEDDER is not None:
                context = embed_retrieve(
                    user_input, RAG_CHUNKS, RAG_TOP_K,
                    RAG_EMBEDDER.embed, chunk_vectors=RAG_CHUNK_VECTORS,
                    min_sim=RAG_MIN_SIM,   # 第十八课：真模型没"正好 0"，阈值抬高
                )
            else:
                context = keyword_retrieve(user_input, RAG_CHUNKS, RAG_TOP_K)
            if context:
                messages.append(
                    {"role": "user", "content": "【检索到的资料，回答时优先参考】\n" + "\n\n".join(context)}
                )

        messages.append({"role": "user", "content": user_input})

        # 处理这一轮：工具循环 + 护栏，全在 handle_user_turn 里
        outcome = handle_user_turn(messages)

        # 裁判护栏（第九课）：这轮好好回答完，就请一台 LLM 打分
        if outcome == "END_TURN" and USE_JUDGE:
            judge_last_turn(messages)

        # 长记忆（第二十一课）：这轮好好回答完了，把刚学到的事实写进记事本。
        # 规则提取免费可测；生产可换成 LLM 提炼（extract_facts 的 extractor 门）。
        if outcome == "END_TURN" and MEMORY is not None:
            added = remember_last_turn(MEMORY, messages)
            if added:
                print(f"[记忆] 这轮记下 {added} 条新事实，写进了记事本")


if __name__ == "__main__":
    main()

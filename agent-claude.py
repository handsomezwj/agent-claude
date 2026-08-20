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


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def execute_tool(name: str, args: dict) -> str:
    """Route a tool-use block to the correct implementation and return its result."""
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

    else:
        return f"Error: Unknown tool '{name}'"


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------


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

        # 上下文护栏：messages 无脑累积，这里每次发出去前先压到预算以内
        # （预算够则原样不动、不花一分钱；超预算才动手）
        if USE_SUMMARY:
            # 摘要模式：最老的对话压成摘要而不是扔掉（要花一次摘要的 API 钱）
            trimmed, _ = replace_with_summary(messages, CONTEXT_BUDGET, client)
        else:
            # 纯裁剪模式：不花钱，但最老的直接扔
            trimmed = trim_history(messages, CONTEXT_BUDGET)
        kwargs = dict(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=sanitize(trimmed),
        )
        if USE_THINKING:
            kwargs["thinking"] = {"type": "adaptive"}

        try:
            response = client.messages.create(**kwargs)
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

    while True:
        try:
            user_input = input("你：")
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break

        if not user_input.strip():
            continue

        messages.append({"role": "user", "content": user_input})

        # 处理这一轮：工具循环 + 护栏，全在 handle_user_turn 里
        outcome = handle_user_turn(messages)

        # 裁判护栏（第九课）：这轮好好回答完，就请一台 LLM 打分
        if outcome == "END_TURN" and USE_JUDGE:
            judge_last_turn(messages)


if __name__ == "__main__":
    main()

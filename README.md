# 多工具 LLM Agent

基于 Anthropic SDK 从零手写的交互式 AI Agent —— 不依赖 LangChain 等上层框架。手写工具调用循环、四层生产护栏、流式输出、MCP 协议、RAG 检索增强、长记忆持久化，一套代码兼容 Anthropic 官方 / DeepSeek 等兼容端点。

## 功能特性

- **手写工具调用循环**：基于 Anthropic SDK 实现 `while(stop_reason=="tool_use")` 多轮自主工具编排，不依赖上层框架，核心逻辑全透明可控
- **3 个自定义工具**：
  - `run_command` — Shell 执行。默认 `shell=False` + `shlex` 参数拆解防注入，仅管道/重定向命令回退 `shell=True`
  - `web_fetch` — 网页抓取。HTML 智能文本抽取（自动跳过 script/nav/footer 噪声），严格 SSL 校验、超时与长度截断
  - `load_skill` — 技能知识库按需加载，注入 System Prompt 扩展 Agent 领域能力
- **SkillLoader 技能系统**：`skills/` 目录下 Markdown 知识库自动加载，按需注入
- **四层生产护栏**：
  - 最大轮数兜底：迭代超过上限强制停（防死循环）
  - 原地打转检测：连续「同工具同参数」自动刹车
  - 上下文超窗裁剪 + 摘要压缩：40k Token 超预算自动处理，永远保住最近对话
  - LLM 质量裁判：每轮回答后独立 LLM 按 0-5 打分，优雅降级不拖垮主循环
- **流式输出**：边生成边打字机吐字，实时体验（`CLAUDE_USE_STREAMING` 可关）
- **MCP 协议接入**：工具不写死在代码里，通过 `CLAUDE_MCP_SERVER` 连一个独立小程序要工具（可关）
- **RAG 检索增强**：词袋向量 + bge 中文向量模型语义检索，同义词可召回（如"番茄"搜得到"西红柿"），有效抑制模型幻觉
- **长记忆**：JSON 记事本持久化关键事实，重启不忘；记忆自动提取并注入 System Prompt（`CLAUDE_USE_MEMORY` 可关）
- **多端点兼容**：`ANTHROPIC_BASE_URL` 统一入口，一套代码切换 Anthropic 官方 / DeepSeek / 第三方兼容端点
- **自动化测试**：188 个 unittest 全绿，自研 FakeModel 假模型替身，零成本回归验证全部护栏
- **工程适配**：Windows 中文环境 GBK/UTF-8 编码修复、lone surrogate 清理、启动配置诊断

## 快速开始

```bash
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL

python agent-claude.py
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_AUTH_TOKEN` | API 密钥 | — |
| `ANTHROPIC_BASE_URL` | API 端点（官方或第三方兼容端点） | — |
| `ANTHROPIC_MODEL` | 模型名称 | `claude-opus-5` |
| `CLAUDE_MAX_TOKENS` | 最大输出 token | `16000` |
| `ANTHROPIC_USE_THINKING` | 启用 adaptive thinking | `false` |
| `CLAUDE_USE_STREAMING` | 流式打字机输出 | `true` |
| `CLAUDE_USE_JUDGE` | 每轮回答后是否请 LLM 裁判打分 | `true` |
| `CLAUDE_USE_SUMMARY` | 上下文超预算时是否用摘要压缩 | `true` |
| `CLAUDE_USE_MCP` | 是否接入 MCP 外部工具 | `true` |
| `CLAUDE_MCP_SERVER` | MCP 服务器启动命令（配了才连，连不上优雅降级） | （空） |
| `CLAUDE_USE_RAG` | 是否启用 RAG 检索增强 | `true` |
| `CLAUDE_RAG_FILE` | RAG 知识库文件 | `learn-agent/knowledge.md` |
| `CLAUDE_RAG_TOP_K` | 检索返回条数 | `2` |
| `CLAUDE_RAG_CHUNK_SIZE` | 知识库切块大小 | `200` |
| `CLAUDE_USE_EMBEDDING` | 是否启用向量检索 | `true` |
| `CLAUDE_EMBEDDING_MODEL` | 真向量模型（如 `BAAI/bge-small-zh-v1.5`，空则用词袋向量） | （空） |
| `CLAUDE_USE_MEMORY` | 是否启用长记忆记事本 | `true` |
| `CLAUDE_MEMORY_FILE` | 记忆文件路径 | `agent-claude.py` 旁 `agent_memory.json` |
| `CLAUDE_MEMORY_MAX_ITEMS` | 记忆最多保留条数 | `50` |

## 项目结构

```
.
├── agent-claude.py    # 主程序：Agent 循环 + 工具系统 + 四层护栏 + 流式/MCP/RAG/长记忆
├── skills/            # 技能知识库（Markdown）
│   ├── python.md
│   ├── git.md
│   └── shell.md
├── learn-agent/       # 从零手写 Agent 的完整源码：每个能力 = 可测模块 + 可运行示例 + 测试
│   ├── agent_loop.py      # Agent 循环核心（含 FakeModel 假模型，零成本测试）
│   ├── spin_guard.py      # 打转检测护栏
│   ├── context.py         # 上下文裁剪护栏
│   ├── summarize.py       # 摘要压缩（旧对话浓缩成便签）
│   ├── llm_judge.py       # LLM 质量裁判
│   ├── memory_store.py    # 长记忆记事本（JSON 持久化，重启不忘）
│   ├── embedding.py       # 词袋向量嵌入（余弦相似度）
│   ├── embedding_models.py# 真向量模型（bge 中文语义检索）
│   ├── multi_agent.py     # 多 Agent 协作（写手 + 评审双脑）
│   ├── prompting.py       # 提示词工程
│   ├── async_utils.py     # 异步编程（并发 gather / 限流 Semaphore）
│   ├── *.py               # 每个能力的可运行示例
│   ├── test_*.py          # 188 个 unittest（FakeModel，零成本）
│   └── knowledge.md       # RAG 默认知识库
├── requirements.txt   # 依赖
└── .env.example       # 环境变量模板
```

## 从零手写（learn-agent/）

整个 Agent 不是拼装出来的，而是自底向上从零手写——每个能力都是**一个可独立测试的模块**，配一个可运行示例 + 一组测试，然后全部接进主程序 `agent-claude.py`，每个能力带环境变量开关，可独立启停：

- 手写工具调用循环（`stop_reason` 驱动多轮自主编排）
- 四层护栏：最大轮数兜底 / 打转检测 / 上下文裁剪 + 摘要压缩 / LLM 质量裁判
- 流式输出、MCP 协议、RAG 检索（词袋向量 + bge 语义向量）、真向量模型、多 Agent 协作（写手 + 评审）、提示词工程、长记忆持久化、异步编程

**每个模块 = 「怎么用」（示例）+「怎么保证不出错」（测试）**。全部能力接进成品后，用 `test_real_agent.py` 回归验证主程序护栏不被破坏。

## 测试

```bash
cd learn-agent && python -m pytest  # 或逐个运行 test_*.py
```

188 个 unittest 全绿。测试不调用真实 API：用自研 FakeModel 假模型替身，几秒跑完、零成本。

## 说明

- `.env` 含真实密钥，永不提交，仅保留 `.env.example` 模板
- `agent_memory.json` 含个人记忆，已加入 `.gitignore`，不进仓库
- 安全：工具执行默认禁止 shell 操作符注入；网页抓取走完整 SSL 校验

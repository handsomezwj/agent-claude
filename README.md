# 多工具 LLM Agent

基于 Anthropic SDK 的交互式 AI Agent，支持自定义工具调用、技能知识库动态加载与多端点兼容。从 DashScope/Qwen 迁移至 Anthropic SDK，手写 `while(stop_reason=="tool_use")` 工具调用闭环，不依赖 LangChain 等上层框架。

## 功能特性

- **手写工具调用循环**：基于 Anthropic SDK 实现多轮自主工具编排，不依赖上层框架
- **3 个自定义工具**：
  - `run_command` — Shell 执行。默认 `shell=False` + `shlex` 参数拆解防注入，仅管道/重定向命令回退 `shell=True`
  - `web_fetch` — 网页抓取。HTML 智能文本抽取（自动跳过 script/nav/footer 噪声），严格 SSL 校验、超时与长度截断
  - `load_skill` — 技能知识库按需加载，注入 System Prompt 扩展 Agent 领域能力
- **SkillLoader 技能系统**：`skills/` 目录下 Markdown 知识库自动加载，按需注入
- **Agent 护栏**：最大 6 轮迭代兜底；连续 3 次「同工具同参数」判定打转自动刹车（复用经属性检查保护的 `spin_guard` 逻辑）；上下文超预算自动裁剪、永远保住最近对话（`context.py`）
- **LLM 质量裁判**：每轮回答后调用独立 LLM 按 0-5 评分标准打分，优雅降级不拖垮主循环（`llm_judge.py`，`CLAUDE_USE_JUDGE` 可关）
- **多端点兼容**：`ANTHROPIC_BASE_URL` 统一入口，第三方端点不支持 thinking 参数时自动降级重试，兼容 OpenAI / Qwen / Claude 多模型
- **工程适配**：Windows 中文环境 GBK/UTF-8 编码修复、lone surrogate 清理、启动配置诊断
- **自动化测试**：35+ 测试用例 + 500 条随机序列属性测试（工具循环、护栏、Mock 验证、裁判打分、上下文裁剪、摘要压缩）

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
| `CLAUDE_USE_JUDGE` | 每轮回答后是否请 LLM 裁判打分 | `true` |

## 项目结构

```
.
├── agent-claude.py    # 主程序：Agent 循环 + 工具系统 + 护栏
├── skills/            # 技能知识库（Markdown）
│   ├── python.md
│   ├── git.md
│   └── shell.md
├── learn-agent/       # Agent 开发课程练习与测试
│   ├── agent_loop.py  # 可测试的 Agent 循环核心
│   ├── spin_guard.py  # 打转检测护栏
│   ├── context.py     # 上下文裁剪护栏
│   ├── summarize.py   # 摘要压缩（trim 的进阶，旧对话浓缩成便签）
│   ├── llm_judge.py   # LLM 质量裁判
│   └── test_*.py      # 自动化测试
├── requirements.txt   # 依赖
└── .env.example       # 环境变量模板
```

## 测试

```bash
cd learn-agent && python -m pytest  # 或逐个运行 test_*.py
```

## 说明

- `.env` 含真实密钥，永不提交，仅保留 `.env.example` 模板
- 安全：工具执行默认禁止 shell 操作符注入；网页抓取走完整 SSL 校验

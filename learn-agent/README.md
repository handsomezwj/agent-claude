# Agent 开发入门课（代码目录）

十一课课程，从零开始带你写第一个 agent。每课一个文件，按顺序看。

## 课程地图

| 文件 | 课 | 讲什么 | 怎么跑 |
|---|---|---|---|
| `01-hello-agent.py` | 第 1 课 | 最小"会接话"的 AI（记忆 + 循环） | `python 01-hello-agent.py` |
| `02-tool-loop.py` | 第 2 课 | 装手：工具调用循环（stop_reason） | `python 02-tool-loop.py` |
| `03-guardrail.py` | 第 3 课 | 兜底护栏：MAX_ITERS | `python 03-guardrail.py` |
| `04-spin-guard.py` | 第 4 课 | 聪明护栏：原地打转检测 | `python 04-spin-guard.py` |
| `agent_tools.py` | 第 5 课 | 被测对象：拆出来的"手"（纯函数） | — |
| `test_tools.py` | 第 5 课 | eval：测"手" | `python test_tools.py` |
| `spin_guard.py` | 第 6 课 | 从循环里抽出来的护栏逻辑 | — |
| `test_spin_guard.py` | 第 6 课 | eval：测护栏的边界 | `python test_spin_guard.py` |
| `test_spin_property.py` | 第 6 课 | eval：测规则本身（500 随机序列） | `python test_spin_property.py` |
| `agent_loop.py` | 第 8 课 | 被测对象：抽成函数的循环 + 假模型 | — |
| `05-mock-loop.py` | 第 8 课 | 假模型演戏：四个剧本看完整个循环 | `python 05-mock-loop.py` |
| `test_loop.py` | 第 8 课 | eval：测整个循环（正常/工具/打转/兜底） | `python test_loop.py` |
| `test_real_agent.py` | 终局 | eval：测**你自己的 agent** 的护栏（真文件+假模型） | `python test_real_agent.py` |
| `llm_judge.py` | 第 9 课 | 被测对象：裁判模型（打分 + 抠分数） | — |
| `06-llm-judge.py` | 第 9 课 | 真裁判给三份回答打分 | `python 06-llm-judge.py --fake` |
| `test_judge.py` | 第 9 课 | eval：测抠分数 + 假裁判 | `python test_judge.py` |
| `context.py` | 第 10 课 | 被测对象：估 token + 裁对话（上下文管理） | — |
| `07-context.py` | 第 10 课 | 对话超窗演示：超预算 → 裁到放得下 | `python 07-context.py` |
| `test_context.py` | 第 10 课 | eval：测估 token + 裁对话的边界 | `python test_context.py` |
| `summarize.py` | 第 11 课 | 被测对象：摘要压缩（旧对话浓缩成便签，trim 的进阶） | — |
| `08-summarize.py` | 第 11 课 | 摘要演示：超预算 → 浓缩成摘要而不是扔掉 | `python 08-summarize.py --fake` |
| `test_summarize.py` | 第 11 课 | eval：测打包提示 + 假摘要模型 + 压缩替换 | `python test_summarize.py` |

## 怎么跑

- 第 1-4 课会读 `.env` 里的 API 配置（文件已经改成按"脚本所在目录"找 `.env`，所以从哪运行都行）。
- 第 8 课完全离线：用假模型演戏，不读 `.env`、不花一分钱。
- 测试文件不需要 `.env`，跑之前记得改坏一个期望值试试红灯。

## 三句心法（回头看用）

1. 模型失忆，你替它记（history）。
2. 模型点菜，程序做菜（工具循环）。
3. 别用手数，让程序数（eval）。

## 下一步

- ✅ 重构作业已完成：`04-spin-guard.py` 只借不抄——打转判断借 `spin_guard.py`，工具执行借 `agent_tools.py`。
- ✅ 第八课完成：假模型测循环（`05-mock-loop.py` + `test_loop.py`），四个剧本免费看全护栏。
- ✅ 终局完成：`agent-claude.py` 上了两道护栏，`test_real_agent.py` 证明它会拦（真文件+假模型，一分钱不花）。
- ✅ 第九课完成：裁判模型（`llm_judge.py` + `test_judge.py`），测"回答质量"。
- ✅ 第十课完成：上下文管理（`context.py` + `test_context.py` + `07-context.py`），防"聊太久超窗"。
- ✅ 第十课已接进 agent：`agent-claude.py` 每次调 API 前 `trim_history(messages, CONTEXT_BUDGET=40000)`，`test_real_agent.py` 验证不破坏原护栏。
- ✅ 第九课已接进 agent：每轮回答完请裁判打分（`judge_last_turn`，`CLAUDE_USE_JUDGE=false` 可关），`test_real_agent.py` 剧本 5 验证。
- ✅ 第十一课完成：摘要压缩（`summarize.py` + `test_summarize.py` + `08-summarize.py`），trim 的进阶——旧对话浓缩成摘要而不是扔掉。
- ✅ 第十一课已接进 agent：`agent-claude.py` 上下文管理默认走摘要模式（`CLAUDE_USE_SUMMARY=false` 退回纯裁剪），`test_real_agent.py` 验证不破坏原护栏。
- 收尾：十一课全部完成，作品集已同步 GitHub。

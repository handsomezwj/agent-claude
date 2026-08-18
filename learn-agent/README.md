# Agent 开发入门课（代码目录）

八课课程，从零开始带你写第一个 agent。每课一个文件，按顺序看。

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
- 测输出：模型自由文本回答需要"裁判模型"打分（LLM-judge），进阶。
- 终局：给你自己的 `agent-claude.py` 加护栏 + 加 eval（把内层 `while True` 抽成函数，就能照第八课测）。

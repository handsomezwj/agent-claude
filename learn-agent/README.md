# Agent 开发入门课（代码目录）

二十二课课程，从零开始带你写第一个 agent。每课一个文件，按顺序看。

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
| `09-git-rebase.md` | 第 12 课 | git 实战：分支分叉 → rebase → 先拉后推 | 复习用笔记（无代码） |
| `streaming.py` | 第 14 课 | 被测对象：流式输出（拼字 + 跑一次流） | — |
| `11-streaming.py` | 第 14 课 | 流式演示：假流打字机 / 真流打字机 | `python 11-streaming.py --fake` |
| `test_streaming.py` | 第 14 课 | eval：测拼字 + 假流 + stop_reason 照常传回 | `python test_streaming.py` |
| `mcp_client.py` | 第 15 课 | 被测对象：MCP 客户端（协议纯函数 + 真门/假门 + 客户端） | — |
| `mcp_weather_server.py` | 第 15 课 | 迷你 MCP 服务器：假装会查天气（被客户端拉起，别手动跑） | — |
| `12-mcp.py` | 第 15 课 | MCP 演示：假门剧本 / 真门启动迷你服务器走真协议 | `python 12-mcp.py --fake` |
| `test_mcp.py` | 第 15 课 | eval：测协议拼装 + 工具翻译 + 假门 + 调用顺序 | `python test_mcp.py` |
| `rag.py` | 第 16 课 | 被测对象：RAG（切块/拆词/打分/检索/拼 prompt + 模型门） | — |
| `knowledge.md` | 第 16 课 | 演示用的知识库（杭州攻略，`agent-claude.py` 默认读它） | — |
| `13-rag.py` | 第 16 课 | RAG 演示：问知识库里的事，先检索再回答；`--fake` 离线跑通 | `python 13-rag.py --fake` |
| `test_rag.py` | 第 16 课 | eval：测切块/拆词/打分/检索（含停用字边界）/拼 prompt | `python test_rag.py` |
| `embedding.py` | 第 17 课 | 被测对象：向量嵌入（余弦相似度/词表/词袋向量/向量检索 + embed 门） | — |
| `14-embedding.py` | 第 17 课 | 向量检索演示：文字变数字 → 余弦找最像；番茄/西红柿演示字面检索的天花板 | `python 14-embedding.py` |
| `test_embedding.py` | 第 17 课 | eval：测余弦/词表/词袋向量/向量检索（含长度归一化、min_sim 边界） | `python test_embedding.py` |
| `embedding_models.py` | 第 18 课 | 被测对象：真向量模型门（ModelEmbedder + 优雅加载工厂） | — |
| `15-embedding-real.py` | 第 18 课 | 真模型语义检索：番茄终于搜得到西红柿；`--fake` 假门复习 | `python 15-embedding-real.py --fake` |
| `test_embedding_real.py` | 第 18 课 | eval：测真门包装 + 工厂降级 + 真模型阈值下的同义词检索（假模型注入，不下载） | `python test_embedding_real.py` |
| `multi_agent.py` | 第 19 课 | 被测对象：真正的多 Agent（双脑版——写手/评审各带各的记忆 + 协调器只管流程） | — |
| `16-multi-agent.py` | 第 19 课 | 双脑协作演示：草稿→评审→重写→通过；结尾摊开两个脑子的账本（各记各的账） | `python 16-multi-agent.py --fake` |
| `test_multi_agent.py` | 第 19 课 | eval：测 Agent 记忆/双脑隔离/优雅降级/解析 + 协调器全流程 | `python test_multi_agent.py` |
| `prompting.py` | 第 20 课 | 被测对象：提示词工程（三要素/few-shot/JSON 容错抽取/max_tokens/思维链/注入防护/分隔符/温度） | — |
| `17-prompting.py` | 第 20 课 | 提示词 demo：四幕演完八股（--fake 离线 / 真模型看 few-shot 差距） | `python 17-prompting.py --fake` |
| `test_prompting.py` | 第 20 课 | eval：测三要素/few-shot/JSON 容错抽取/截断/温度 | `python test_prompting.py` |
| `memory_store.py` | 第 21 课 | 被测对象：长记忆（记事本 MemoryStore + 事实提取门 + 自动记） | — |
| `18-memory.py` | 第 21 课 | 记忆演示：五幕演完"重启不失忆"的机关；真模式两段对话间重启，模型真记得 | `python 18-memory.py --fake` |
| `test_memory.py` | 第 21 课 | eval：测记事本增删去重/上限/存盘读回/坏文件/事实提取/自动记 | `python test_memory.py` |
| `19-deploy.md` | 第 22 课 | 上线部署笔记：怎么启动 / 密钥放哪 / 状态存哪，照着能上线 | 复习用笔记（无代码） |
| `async_utils.py` | 专项 · 异步 | 被测对象：异步编程（fake_call 门 / 串行 / 并发 gather / 限流 Semaphore） | — |
| `20-async.py` | 专项 · 异步 | 异步演示：五幕（串行 vs 并发 / 保序 / 限流 / 依赖关系） | `python 20-async.py` |
| `test_async.py` | 专项 · 异步 | eval：测串行耗时/并发耗时/保序/限流上限/边界 | `python test_async.py` |

## 怎么跑

- 第 1-4 课会读 `.env` 里的 API 配置（文件已经改成按"脚本所在目录"找 `.env`，所以从哪运行都行）。
- 第 8 课完全离线：用假模型演戏，不读 `.env`、不花一分钱。
- 第 14 课默认连真 API 流式打字机；`--fake` 假流一分钱不花。`agent-claude.py` 的流式可用 `CLAUDE_USE_STREAMING=false` 关掉，回退到老的一次性输出。
- 第 15 课 `--fake` 用假门（剧本）离线跑通；不带参数启动本机的迷你天气服务器（`mcp_weather_server.py`）真实走一遍 JSON-RPC，也是本机、不花钱。`agent-claude.py` 配了 `CLAUDE_MCP_SERVER` 才会去连 MCP，连不上自动降级只用内置工具。
- 第 16 课 `--fake` 离线跑通（假模型照剧本回答）；不带参数会真调 API 答三个关于杭州的问题。`agent-claude.py` 默认开 RAG：每次提问前先在 `learn-agent/knowledge.md` 里检索最相关的几块塞给模型；可用 `CLAUDE_RAG_FILE` 换知识库、`CLAUDE_USE_RAG=false` 关掉、`CLAUDE_RAG_TOP_K` 调检索条数。
- 第 17 课完全本地、免费：`python 14-embedding.py` 把文字变向量、用余弦相似度找最像的块。`agent-claude.py` 默认用向量检索（`CLAUDE_USE_EMBEDDING=false` 可关回第十六课的关键词打分；向量检索起不来也会自动降级）。
- 第 18 课把假门换成真向量模型（本地 bge-small-zh-v1.5，首次用下载 ~100MB，之后离线免费）：`python 15-embedding-real.py --fake` 复习假门，不带参数跑真模型看语义检索。`agent-claude.py` 配 `CLAUDE_EMBEDDING_MODEL`（如 `BAAI/bge-small-zh-v1.5`）就升级成语义检索；模型加载失败自动回退假门。真模型没"正好 0"的相似度，阈值抬高到 `REAL_MIN_SIM=0.45`（换语料要重调）。
- 第 19 课 `--fake` 用两个假模型剧本离线跑双脑协作（零成本）；不带参数用真模型真协作（花一点钱）。这课独立演示 + 测试，不接 `agent-claude.py`——给成品接"写手+评审"是下一个自然实验，先在本课把双脑 Agent 摸透。
- 第 20 课提示词工程：`--fake` 假模型剧本离线看六幕（零成本）；不带参数第 2、5 幕会真调 API（花一点钱，看真差距）。纯知识课 + 小实验，不接 `agent-claude.py`。
- 第 21 课长记忆：`--fake` 离线演五幕（记事本增删存盘 / 重启读回 / 自动记 / 贴进 system prompt / 重启不失忆的机关，零成本）；不带参数第 5 幕真调 API，两段对话之间"重启"，模型真的记得你。`agent-claude.py` 默认开长记忆：把"关于用户的事实"记进 `agent_memory.json`（在 agent-claude.py 旁边，不是课程目录），每轮对话结束自动记、每次回答前贴进 system prompt；可用 `CLAUDE_USE_MEMORY=false` 关掉、`CLAUDE_MEMORY_FILE` 换文件、`CLAUDE_MEMORY_MAX_ITEMS` 调条数上限。
- 第 22 课是纯笔记（`19-deploy.md`），不花钱。想真部署：照着"第 4 节流程"做即可（加 gunicorn 到 requirements → 建 Procfile → 推 GitHub → Render 连仓库填环境变量 → 拿 URL）。动手任务里有个零成本体验：本地用 `waitress` 跑生产模式（gunicorn 在 Windows 上跑不了——这本身就是"本地≠线上"的例子）。
- 异步专项完全离线：用 `asyncio.sleep` 模拟 API 延迟，不读 `.env`、不花一分钱。`20-async.py` 五幕演示（串行 vs 并发 / 保序 / 限流 / 依赖关系），`test_async.py` 12 个测试验证"串行耗时为和 / 并发耗时为最大 / 限流上限不超"。
- 测试文件不需要 `.env`，跑之前记得改坏一个期望值试试红灯。

## 三句心法（回头看用）

1. 模型失忆，你替它记（history）。
2. 模型点菜，程序做菜（工具循环）。
3. 别用手数，让程序数（eval）。
4. 先拉后推，被拒先看（git）。

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
- ✅ 第十二课完成：git 发布实战（分叉 → rebase → 先拉后推），笔记 `09-git-rebase.md`；第二个作品集 `resume-advisor` 已上线 https://github.com/handsomezwj/resume-advisor
- ✅ 第十四课完成：流式输出（`streaming.py` + `test_streaming.py` + `11-streaming.py`），打字机效果；已接进 `agent-claude.py`（`CLAUDE_USE_STREAMING=false` 可关，回退老行为），`test_real_agent.py` 验证流式开/关两条路都不破坏原护栏。
- ✅ 第十五课完成：MCP 工具接入（`mcp_client.py` + `mcp_weather_server.py` + `test_mcp.py` + `12-mcp.py`）——工具不写死在代码里，问一个独立小程序要；已接进 `agent-claude.py`（`CLAUDE_MCP_SERVER` 配了才连，连不上优雅降级），`test_real_agent.py` 验证不破坏原护栏。
- ✅ 第十六课完成：RAG 检索增强（`rag.py` + `knowledge.md` + `test_rag.py` + `13-rag.py`）——AI 不懂你自己的资料，提问前先在知识库里检索最相关的几块再回答；已接进 `agent-claude.py`（默认读 `learn-agent/knowledge.md`，`CLAUDE_USE_RAG=false` 可关，`CLAUDE_RAG_FILE` 换知识库），`test_real_agent.py` 验证不破坏原护栏。
- ✅ 第十七课完成：向量嵌入（`embedding.py` + `test_embedding.py` + `14-embedding.py`）——关键词打分只认字面（番茄搜不到西红柿），把文字变向量用余弦相似度找最像；本地词袋向量当假门把机制讲透，真向量模型是同一扇门；已接进 `agent-claude.py`（`CLAUDE_USE_EMBEDDING=false` 可关回关键词，起不来自动降级），`test_real_agent.py` 验证不破坏原护栏。
- ✅ 第十八课完成：真向量模型（`embedding_models.py` + `test_embedding_real.py` + `15-embedding-real.py`）——把假门换成 bge 中文模型，语义检索兑现：番茄 vs 西红柿余弦 0.75，问「番茄」搜得到写「西红柿」的正文；真模型没有"正好 0"，阈值调到 0.45 才挡得住无关内容；已接进 `agent-claude.py`（`CLAUDE_EMBEDDING_MODEL` 配置即升级，加载失败自动回退假门），`test_real_agent.py` 验证不破坏原护栏。
- ✅ 第十九课完成：真正的多 Agent 协作（`multi_agent.py` + `test_multi_agent.py` + `16-multi-agent.py`）——第 13 课的单脑版升级成双脑版：写手、评审是两个独立 Agent 对象，各带各的记忆（messages），协调器只认 `.ask()` 一个门；结尾把两个人的账本摊开，看"各记各的账"（信息隔离）。优雅降级 + max_rounds 护栏照旧。独立演示 + 测试，未接 `agent-claude.py`。
- ✅ 第二十课完成：提示词工程深挖（`prompting.py` + `test_prompting.py` + `17-prompting.py`，26 测试）——system prompt 三要素（角色+规则+输出格式）、few-shot 少样本（给例子比说"要简短"管用）、结构化输出 JSON 容错抽取（剥代码块/剥废话，抠不到返回 None）、max_tokens 的坑（截断 + resume-advisor 踩过的空响应）、思维链 CoT（先推理再答 + 抠最终答案）、提示词注入防护（扫"忽略指令"这类苗头）、分隔符指令-数据分离、温度速查表（抽取 0 / 创意 1）。纯知识课 + 小实验，未接 `agent-claude.py`；复用第 10 课 `estimate_tokens` 当"门"。中途修了 `.env` 路径 bug（10/16/17 课的 demo 改指向 `..`）。
- ✅ 第二十一课完成：长记忆（`memory_store.py` + `test_memory.py` + `18-memory.py`，27 测试）——给 agent 一个"记事本"：`MemoryStore` 把"关于用户的事实"存进 JSON 文件（增/查/存盘/读回，重复不记、max_items 挤最老、读坏文件优雅降级）；`extract_facts` 规则门从对话抽事实（我叫/我住在/我喜欢/我在…工作，外加"记住：X / 别忘了 X"显式命令，区分"记住了"这种应答）；`build_memory_prompt` 把记忆贴进 system prompt，模型"一开场就知道你是谁"；`remember_last_turn` 一轮结束自动记（复用第九课"抽最近一问 + 最近一答"的逻辑）。已接进 `agent-claude.py`：启动 `connect_memory()` 打开记事本（默认 `agent_memory.json` 在 agent-claude.py 旁边，不进课程目录免得用户隐私误提交），每次回答前 `build_system_text()` 把记忆贴进 system，每轮 END_TURN 后自动记新事实；`CLAUDE_USE_MEMORY=false` 可关、`CLAUDE_MEMORY_FILE` 换文件。`test_real_agent.py` 验证不破坏原护栏。
- ✅ 第二十二课完成：上线部署原理（`19-deploy.md`）——文档课，不花钱。对着真实 resume-advisor 把"怎么启动（gunicorn `app:app` + `0.0.0.0:$PORT`，Windows 本地用 waitress）/ 密钥放哪（.gitignore 盖 .env + 平台环境变量面板，load_dotenv 不覆盖已有变量）/ 状态存哪（内存 dict 重启就丢，生产换数据库）"讲透；含 Render 上线流程、上线后真坑（冷启动/max_tokens 空响应/超时/健康检查）、面试速答、零成本动手任务（本地 waitress 跑生产模式）。想真部署（花钱版）随时说。
- ✅ 异步编程专项完成（`async_utils.py` + `test_async.py` + `20-async.py`，12 测试）——讲透"程序等 I/O 时 CPU 在干等"：串行 await 总耗时相加、`gather` 并发叠等待、`Semaphore` 限流防打爆、保序（返回顺序=传入顺序）、依赖关系（没依赖的并发，有依赖的必须等）。完全离线免费。独立演示 + 测试，未接 `agent-claude.py`（agent 用的同步 SDK 流式；接异步是自然延伸，想接再说）。

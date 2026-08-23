# 第 22 课：上线部署——从"本地能跑"到"网上能用"

> 部署原理 + 步骤文档课（不花钱版）。对着你真实的 resume-advisor 讲，
> 把"本地能跑 ≠ 线上能跑"这件事讲透。真想花钱上线时，照"第 4 节步骤"做即可。

---

## 0. 先建心法：部署 = 把"你的电脑"换成一台"永远开机的别人的电脑"

你在本地跑 app，只有你自己能访问——因为 `localhost` 是你的电脑自己的回环地址。

**部署 = 把代码放到一台 7×24 小时开机的服务器上，让全世界通过网址访问。**

服务器上没你的键盘、没你的鼠标、没你的 `C:\Users\zwj\.env`。所以部署其实是在回答三个问题：

| 必答题 | 人话 | 本地 | 线上 |
|---|---|---|---|
| ① 怎么启动 | 谁来把程序跑起来 | `python app.py` | 平台跑一个启动命令 |
| ② 密钥放哪 | 你的 token 放哪不被偷 | `C:\Users\zwj\.env` | 平台环境变量面板 |
| ③ 状态存哪 | 记忆/会话放哪 | 内存 dict | 内存 dict（会丢）或数据库 |

把这三个问题想清楚，部署就没有玄学了。

---

## 1. 你的项目现状（resume-advisor）

```
app.py            Flask 入口：路由是薄壳，只取表单、调 service、回渲模板
services.py       业务逻辑（面试/诊断/改写）
llm_client.py     .env 加载 + client 初始化 + 密钥
prompts/parsers   菜谱 + 验菜员
interview_store.py  面试会话状态：内存 dict（sid → 历史）
```

本地跑法：`pip install -r requirements.txt` → 填 `.env` → `python app.py` → 浏览器开 `localhost:5000`。

**这个跑法有三个"只有本地才成立"的地方**，每个都是上线的坎：

1. `app.run(debug=True)` —— **开发模式**
2. `llm_client.py` 读家目录 `.env` 兜底 —— 服务器上没有 `C:\Users\zwj\.env`
3. `interview_store.py` 是**内存 dict** —— 进程一重启就全丢

---

## 2. 三个必答题，逐题拆

### 问① 怎么启动（生产入口）

**本地**：`python app.py` 里最后一行的 `app.run(debug=True)`。

**生产不能这么跑**，原因有三：

- **debug=True 会泄密**：出错时浏览器会显示**完整堆栈 + 源码 + 环境变量**。
  访问者一触发一个错，就能看到你的密钥。这是开发模式，不是给你上线用的。
- **Flask 自带服务器慢且不抗造**：它是"开发用的小板凳"，不是"给全世界坐的椅子"。
  生产要用专业 **WSGI 服务器**（gunicorn / waitress）来跑 Flask 应用。
- **端口只绑在 localhost**：本地 `localhost:5000` 只有你自己能进。
  线上要绑 `0.0.0.0:$PORT`，让平台能把外部请求转发进来。

**生产入口长这样**（不用改 app.py，gunicorn 直接 import `app:app`）：

```bash
# 平台上要填的启动命令（gunicorn 是 Unix 系的 WSGI 服务器）
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

等等，`app:app` 是啥？`app`（模块名 app.py）里有个 `app`（Flask 实例）。
gunicorn 说"去 app.py 里找那个叫 app 的 Flask 对象，跑起来"。就这一句。

**一个真实的坑（也是最好的"本地≠线上"例子）**：gunicorn 是 Unix 的，**你在 Windows 上装不了/跑不了**。
本地想体验"生产模式"，用 **waitress**（Windows 也能装的 WSGI 服务器）：

```bash
pip install waitress
waitress-serve --listen=0.0.0.0:5000 app:app
```

> 你写代码的机器是 Windows，服务器是 Linux——同一个 app，两种跑法。
> 这就是"本地能跑 ≠ 线上能跑"最生动的版本：**不只环境不同，连服务器软件都不同**。

### 问② 密钥放哪（安全）

你的密钥：`ANTHROPIC_AUTH_TOKEN`（真金白银）、`FLASK_SECRET_KEY`（session 签名）。

**铁律（面试必背）：密钥绝不进 GitHub。**
你的 `.gitignore` 已经写了 `.env` ✓——`git push` 不会把密钥推上去。这层你已经做对了。

那服务器上密钥放哪？两条路：

- **路 A：平台环境变量面板（推荐）**。Render 的 Web Service 里有个 Environment 区域，
  填 `ANTHROPIC_AUTH_TOKEN = 你的token`，平台会把它注入进程的环境变量。
  **关键细节**：python-dotenv 的 `load_dotenv()` 默认 `override=False`——
  **不会覆盖已有的环境变量**。所以平台面板里填的变量，永远赢过 `.env` 文件。安全。
- **路 B：在服务器上建一个 `.env` 文件**（放进项目目录，但别 commit）。

**你代码里的一个本地特例**：`llm_client.py` 有一行 `load_dotenv(Path.home() / ".env")`——
读家目录兜底，这是给**你自己电脑**用的（`C:\Users\zwj\.env` 里有真密钥）。
**服务器上没有这个文件**，所以这一行在线上是空转。没关系——只要面板/项目 `.env` 兜住了就行。
但你要知道：**"家目录兜底"是本地开发才有的便利，不是生产特性**。

**另一个隐藏坑**：`app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(16)`。
不设 `FLASK_SECRET_KEY` → 每次启动随机生成 → **服务器重启后所有用户 session 全失效**（全被登出）。
上线前务必在面板里填一个固定的 `FLASK_SECRET_KEY`。

### 问③ 状态存哪（数据/会话）

`interview_store.py` 是**纯内存 dict**。在本地单进程无所谓，在线上有两个问题：

1. **服务器重启就全丢**（进程死了，内存里的 50 个面试会话全没了）
2. **多 worker 不共享**（平台可能起 2 个进程，用户请求可能被分到另一个进程，查不到自己的会话）

同理，Flask 的 `session` 也存在签名 cookie 里，配合 `FLASK_SECRET_KEY` 用。

生产选项：

| 方案 | 代价 | 适合 |
|---|---|---|
| 接受"重启丢会话" | 0 | 单用户 demo 工具（resume-advisor 就够用） |
| 换成数据库/Redis | 要写代码 + 可能花钱 | 多人真实使用 |

**面试八股**：12-factor 原则说"进程无状态，状态进外部存储"——
真正的生产应用，会话/数据要放数据库或 Redis，进程本身是个"用完就忘"的干活的。

---

## 3. 平台怎么选

| 平台 | 免费额度 | 连 GitHub 自动部署 | 备注 |
|---|---|---|---|
| **Render** | 有（免费层会休眠） | ✅ | 教程最多、最省心；国内直连时好时坏 |
| Railway | 试用额度 | ✅ | 简单，但免费额度收紧过 |
| Fly.io | 有限 | ✅ | 全球节点，配置略繁琐 |
| Vercel | 有 | ✅ | 前端为主，Flask 要写 `vercel.json` 适配 |
| 国内云服务器（阿里/腾讯 ECS） | ❌ 按量 | 手动 | 最正统：Linux + gunicorn + Nginx，国内访问快 |
| 国内 Serverless | 有 | 看平台 | 函数计算，Flask 要适配 |

**重点提醒**：阿里云**百炼**、百度**千帆**是"模型 API"平台（卖 token 的），
**不是**把你的 Flask app 托管的平台——别搞混。它们提供模型，不提供"跑你的代码"。

**推荐**：想快速看到真 URL → Render（GitHub 连仓库，环境变量面板，几分钟）。
在国内访问慢 / 想认真做 → 云服务器 + gunicorn + Nginx。

---

## 4. 上线流程（照这个顺序做）

以 Render 为例（真要做时，每一步点哪都写清了）：

1. **加 gunicorn 进 `requirements.txt`**：
   ```
   flask
   anthropic
   python-dotenv
   gunicorn
   ```
2. **确认 `.gitignore` 盖住 `.env`**（你的已经盖了 ✓）。
3. **建 `Procfile`**（仓库根目录）：
   ```
   web: gunicorn app:app --bind 0.0.0.0:$PORT
   ```
4. `git add . && git commit && git push` 推到 GitHub（你的 origin 就是
   `https://github.com/handsomezwj/resume-advisor.git`）。
5. **Render 上操作**：New → Web Service → **Connect** 你的 GitHub 仓库 →
   启动命令填 `gunicorn app:app --bind 0.0.0.0:$PORT`（或让它读 Procfile）。
6. **填环境变量**（Environment 区域）：
   ```
   ANTHROPIC_AUTH_TOKEN = <你的token>
   ANTHROPIC_BASE_URL   = <你的端点>
   ANTHROPIC_MODEL      = <你的模型>
   FLASK_SECRET_KEY     = <随便一长串随机字符，固定它>
   ```
7. **Deploy**。等它构建 + 启动（第一次要几分钟），拿 `https://你的项目名.onrender.com` 访问。

**上线后自检清单**：
- [ ] 首页能打开
- [ ] 传一份简历 + JD 试一次诊断，能出结果（不报 500）
- [ ] 把页面地址发给**别人**（不是你自己）也能打开
- [ ] 触发一个错误（比如不填 JD 就提交），页面是友好提示，不是堆栈
- [ ] 看一眼平台日志，确认没有密钥被打印出来

---

## 5. 上线后的坑（真实教训）

- **免费层会休眠**：Render 免费实例没人访问会睡过去，下次访问要等几秒~几十秒"冷启动"。
  不是坏了，是它刚从梦里醒。付费层不休眠。
- **max_tokens 空响应**（你在 resume-advisor 真踩过的坑）：deepseek 先思考后输出，
  `max_tokens` 太小 → 思考烧光预算 → 正稿空响应。上线环境要把预算调够。
- **请求超时**：平台对单次请求有时限。LLM 调用慢，用户会等不及/被平台掐断。
  对策：合理的 `max_tokens`、把耗时的活做成后台任务（进阶）。
- **日志是命根子**：优雅降级 ≠ 静默吞错（第九课心法）——线上出错要看平台日志面板，
  页面给用户友好提示，真相留在日志里。
- **健康检查**：平台会定期 ping 应用。加一个 `/healthz` 返回 200，平台才知道你活着：
  ```python
  @app.get("/healthz")
  def healthz():
      return "ok", 200
  ```

---

## 6. 面试速答

> **"部署过项目吗？"**
> 部署过一个 Flask 简历助手。核心是把三件事讲清楚：怎么启动（gunicorn + `0.0.0.0:$PORT`）、
> 密钥放哪（`.gitignore` 盖住 `.env` + 平台环境变量面板，`load_dotenv` 不覆盖已有变量）、
> 状态存哪（内存存储重启就丢，生产要换数据库/Redis）。还踩过 max_tokens 空响应和冷启动的坑。

> **"密钥怎么保密？"**
> 三招：① 密钥写进 `.env` 且被 `.gitignore` 忽略，绝不进 GitHub；② 部署时在平台
> 环境变量面板填，注入进程环境变量，不落盘；③ 面板变量优先级高于 `.env`（load_dotenv
> 不覆盖已有环境变量）。外加生产关 debug 模式（debug 会把堆栈和环境变量亮给访问者）。

> **"本地能跑，为什么不能直接上线？"**
> 至少五个差异：① debug 模式泄密且是开发专用；② Flask 自带服务器慢、不安全，
> 要换 gunicorn 这类 WSGI 服务器；③ 端口要从 localhost 改成 `0.0.0.0:$PORT`；④ 密钥
> 从家目录 `.env` 变成平台环境变量；⑤ 内存状态变成"重启就丢"，多人用要换外部存储。

> **"Flask 应用怎么上线？"**
> gunicorn `app:app` + 平台（Render 等）连 GitHub 自动部署 + 环境变量面板填密钥。
> 本地 Windows 想体验生产模式用 waitress（gunicorn 在 Windows 上跑不了）。

---

## 7. 动手任务（不花钱，本地先体验"生产模式"）

1. 在 resume-advisor 目录跑 `pip install waitress`，然后
   `waitress-serve --listen=0.0.0.0:5000 app:app`——用生产级 WSGI 服务器跑起来，
   浏览器开 `localhost:5000`，对比 `python app.py` 的体验差异。
2. 试试把 `app.run(debug=True)` 改一行，用环境变量控制 debug，体会"生产/开发分开"：
   ```python
   if __name__ == "__main__":
       app.run(debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
   ```
3. 想清楚再动手：`interview_store.py` 如果上线，重启丢会话你能接受吗？
   能 → 不用改；不能 → 想想换成 sqlite（一行 `import sqlite3` 就能试）。

# itops_guard.py — IT 运维安全护栏模块（被测对象）
#
# 业务场景：运维助手只做"只读诊断"——查服务状态、查日志、看资源，
# 但绝不碰破坏性操作（删文件、杀进程、重启服务）。真出事了，永远先问人。
#
# 两道门：
#   guard_command    命令黑名单：破坏性动词 / 写操作符，token 级拦截
#   read_log_safely  路径护栏：日志只能读白名单目录内的文件，../ 越权一律拒绝
#
# 一句话：Agent 越能干，越要敢说"不"。安全护栏 = 把"能干"框在"该干"里。

import json
import shlex
from pathlib import Path

# 破坏性命令黑名单：token 命中即拒绝，值是对外说明（会回显给模型）。
# 覆盖 Unix（rm/kill/reboot…）和 Windows（del/taskkill/format…）常见破坏性动词。
DANGEROUS_CMDS: dict[str, str] = {
    "rm": "删除文件/目录",
    "rmdir": "删除目录",
    "del": "删除文件（Windows）",
    "erase": "删除文件（Windows）",
    "rd": "删除目录（Windows）",
    "kill": "杀进程",
    "taskkill": "杀进程（Windows）",
    "pkill": "按名字杀进程",
    "killall": "杀所有同名进程",
    "reboot": "重启系统",
    "shutdown": "关机/重启系统",
    "halt": "停机",
    "poweroff": "断电",
    "mkfs": "格式化磁盘",
    "dd": "低级磁盘读写",
    "fdisk": "磁盘分区",
    "iptables": "改防火墙规则",
    "systemctl": "控制系统服务",
    "service": "控制系统服务",
    "format": "格式化磁盘（Windows）",
    ">": "重定向覆盖写文件",
    ">>": "重定向追加写文件",
}


def guard_command(command: str) -> tuple[bool, str]:
    """判断一条命令是否允许执行（只读安全护栏）。纯函数，可测。

    做法：shlex 按空格拆 token（posix=False 是为了 Windows 反斜杠路径
    不被当转义符吞掉），每个 token 小写后跟黑名单比对，任一命中 → 拒绝
    并说明原因；全部干净 → (True, "ok")。

    覆盖隐蔽写法：管道/分号拼接（`ls | rm`、`ls; rm`）里 rm 是独立 token
    一样会被拦；不带空格的 `cat a >b` 由"以 > 开头"兜住。
    """
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        tokens = [command]
    for tok in tokens:
        low = tok.lower()
        if low in DANGEROUS_CMDS:
            return False, f"{low}（{DANGEROUS_CMDS[low]}）"
        if low.startswith(">"):
            return False, f"{low}（重定向写文件）"
        if low.startswith("mkfs"):
            return False, f"{low}（格式化磁盘）"
    return True, "ok"


def read_log_safely(
    log_relpath: str, base_dir: Path, keyword: str = "", tail_lines: int = 20
) -> str:
    """只读日志文件，带路径护栏和关键词过滤。纯函数，可测。

    - 路径护栏：请求路径 resolve() 后必须落在 base_dir 里，否则拒绝
      （防 `../.env`、绝对路径等越权——日志目录之外一律不让读）
    - 文件缺失 / 空文件 / 目标是目录：优雅返回提示，不抛异常
    - keyword：忽略大小写的子串过滤；空 = 不过滤
    - tail_lines：只返回末尾 N 条（钳制在 [1, 100]，防一次读爆上下文）
    - 返回带原行号的文本，方便回答里引用"第几行"作证据
    """
    try:
        base = base_dir.resolve()
        full = (base / log_relpath).resolve()
        if not full.is_relative_to(base):
            return f"拒绝读取：{log_relpath} 超出运维日志目录（只读护栏）"
        if not full.exists():
            return f"日志不存在：{log_relpath}"
        if full.is_dir():
            return f"拒绝读取：{log_relpath} 是目录，不是日志文件"
    except OSError:
        return f"拒绝读取：{log_relpath} 路径不合法"

    try:
        lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"读取日志失败：{exc}"

    try:
        n = max(1, min(int(tail_lines), 100))
    except (TypeError, ValueError):
        n = 20

    if keyword:
        hits = [
            (i, line)
            for i, line in enumerate(lines, 1)
            if keyword.lower() in line.lower()
        ]
        shown = hits[-n:]
        if not shown:
            return f"日志中没找到包含「{keyword}」的行"
        return "\n".join(f"{i}: {line}" for i, line in shown)

    start = max(0, len(lines) - n)
    return "\n".join(f"{i}: {line}" for i, line in enumerate(lines[start:], start + 1))


def load_service_registry(base_dir: Path) -> dict:
    """读服务注册表（ops_demo/services.json），文件缺失/解析失败返回空 dict。纯函数，可测。"""
    p = Path(base_dir) / "services.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def check_service_status(service_name: str, registry: dict, base_dir: Path) -> str:
    """查一个服务的状态（只读）。纯函数，可测。

    状态判定只看 pid 文件在不在：
    - 注册表里没有 → 未知服务
    - pid 文件不在 → 停止
    - pid 文件在   → 运行中（报 pid / 端口 / 描述）

    注意：这里【不】做 os.kill(pid, 0) 存活校验——Windows 上 os.kill(pid, 0)
    会真的把进程杀掉（Windows 的 os.kill 语义特殊）！真实部署应改用 ps/tasklist
    校验；demo 里 pid 文件由 ops_demo/demo_service.py 的 start/stop 控制，够确定。
    """
    svc = registry.get(service_name)
    if not svc:
        names = "、".join(registry.keys()) or "无"
        return f"未知服务：{service_name}（当前可查：{names}）"
    pid_file = Path(base_dir) / svc.get("pid_file", f"{service_name}.pid")
    if not pid_file.exists():
        return (
            f"服务 {service_name}：状态【停止】——pid 文件 {pid_file.name} 不存在，"
            f"进程没在跑。（端口 {svc.get('port', '?')}，描述：{svc.get('description', '')}）"
        )
    try:
        pid = pid_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        pid = "?"
    return (
        f"服务 {service_name}：状态【运行中】——pid={pid}，端口 {svc.get('port', '?')}。"
        f"（描述：{svc.get('description', '')}）"
    )

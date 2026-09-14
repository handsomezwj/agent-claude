# remote_ops.py — 连到真 Linux 主机做只读巡检（被测对象）
#
# 为什么要有这个：itops_guard.py 那套是"演"的——读本地假的 pid 文件、假的 app.log。
# 面试官一句"这是真环境吗"就到底了。这个模块让 agent 通过 SSH 去查**真主机**：
#   systemctl 真问服务状态、journalctl 真翻系统日志、uptime/free/df 真看负载和磁盘。
#
# 安全设计（四道门，从里到外）——这是本模块的重点，比功能重要：
#   ① 参数层：所有会被拼进命令的输入（服务名）先过正则白名单，只认字母数字和 @._:- ，
#      且不许以 - 开头（防 `--help` 这类选项注入）；关键词过滤干脆不拼进命令，本地筛。
#   ② 客户端黑名单：guard_command（itops_guard）先拦破坏性动词。
#   ③ 远端白名单：screen_remote_cmd 只放行"以固定前缀开头的单条只读命令"，
#      且命令里不许出现 ; | & $ ` > < 和换行——合法命令根本不需要这些。
#      黑名单挡的是"能想到的坏写法"，白名单挡的是"没想到的坏写法"，两个都要。
#   ④ 主机侧最小权限：sshd 只认密钥不认密码（PermitRootLogin prohibit-password）。
#
# 一句话：Agent 越能干，越要敢说"不"，而且要敢在**别人家的机器上**说"不"。

import os
import re
import shutil
import subprocess
from pathlib import Path

# ---- 远端白名单（第三道门）：只认这些前缀开头的命令 ----
# 全是只读查询：看状态、看日志、看负载，没有一条会改机器上的任何东西。
REMOTE_ALLOW_PREFIXES: tuple[str, ...] = (
    "systemctl is-active ",
    "systemctl is-enabled ",
    "systemctl show ",
    "journalctl -u ",
    "cat /etc/os-release",
    "uptime",
    "nproc",
    "free -m",
    "df -h",
    "ps -eo ",
)

# 命令里出现这些字符一律拒绝：合法只读命令不需要它们，而它们正是拼接注入的原料。
FORBIDDEN_CHARS: tuple[str, ...] = (";", "|", "&", "$", "`", ">", "<", "\n", "\r")

# 服务名白名单：systemd 单元名合法字符，且不以 - 开头（- 开头会被当成命令行选项）
_UNIT_RE = re.compile(r"^[A-Za-z0-9_@.][A-Za-z0-9_@.:-]{0,63}$")

# journalctl 一次最多拉多少行（拉回来在本地筛，绝不在远端拼管道）
LOG_FETCH_MAX = 500
LOG_TAIL_MAX = 100


def screen_remote_cmd(cmd: str) -> tuple[bool, str]:
    """判断一条**将要发到远端**的命令是否放行。纯函数，可测。

    跟 guard_command 的分工：guard_command 是黑名单（哪些动词绝对不能干），
    这里是白名单（除了这几类查询，别的我根本不认）。白名单更狠——
    就算有人发明了我没见过的坏写法，只要不在白名单里，一样出不去。

    返回 (是否放行, 原因)。
    """
    if not isinstance(cmd, str):
        return False, "命令必须是字符串"
    text = cmd.strip()
    if not text:
        return False, "命令是空的"
    for ch in FORBIDDEN_CHARS:
        if ch in text:
            shown = "换行" if ch in ("\n", "\r") else ch
            return False, f"命令里出现禁止字符 {shown}（只读巡检不需要它）"
    if not text.startswith(REMOTE_ALLOW_PREFIXES):
        return False, f"不在只读命令白名单里：{text[:40]}"
    return True, "ok"


def safe_unit(unit: str) -> tuple[bool, str]:
    """校验服务名（第一道门）。纯函数，可测。"""
    if not isinstance(unit, str) or not _UNIT_RE.match(unit.strip()):
        return False, f"服务名不合法：{unit!r}（只允许字母数字和 _ @ . : -，且不能以 - 开头）"
    return True, unit.strip()


# ---------------------- 命令构造（全是只读查询） ----------------------

def build_service_cmds(unit: str) -> dict[str, str]:
    """构造问一个服务状态的三条命令：活着吗 / 开机自启吗 / 细节（pid、启动时间、重启次数）。纯函数。"""
    return {
        "active": f"systemctl is-active {unit}",
        "enabled": f"systemctl is-enabled {unit}",
        "show": (
            f"systemctl show {unit} -p MainPID -p ActiveEnterTimestamp "
            f"-p SubState -p NRestarts -p LoadState"
        ),
    }


def build_log_cmd(unit: str, fetch_lines: int = 200) -> str:
    """构造取系统日志的命令。纯函数。

    注意：**不用管道**。关键词过滤在本地做（远端少一次拼接就少一个注入面），
    而且 journalctl 的输出格式稳定，本地筛更好控制。
    """
    n = max(1, min(int(fetch_lines), LOG_FETCH_MAX))
    return f"journalctl -u {unit} -n {n} --no-pager --no-hostname"


def build_health_cmds() -> dict[str, str]:
    """构造"这台机器健康吗"的几条命令：负载 / 核数 / 内存 / 磁盘 / 吃 CPU 的进程。纯函数。

    为什么要问核数（nproc）：**负载数字本身没有好坏，要除以核数才有**。
    负载 4.0 在 2 核机器上是严重过载（活儿排了两倍队），在 16 核机器上屁事没有。
    只看数字不看核数，是新手最容易犯的判断错误。
    """
    return {
        "os": "cat /etc/os-release",
        "uptime": "uptime",
        "cores": "nproc",
        "free": "free -m",
        "df": "df -h",
        "ps": "ps -eo pid,pcpu,pmem,etime,comm --sort=-pcpu",
    }


# ---------------------- 输出解析（纯函数，离线可测） ----------------------

def _to_int(text, default: int = 0) -> int:
    """宽容地把一段文本变成整数。读不懂就返回默认值，绝不抛异常（远端输出不可信）。纯函数。"""
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return default


# 下面这三个 read_* 是"读原始数字"，上面的 parse_* 是"读成人话"。
# 为什么要分两层：**判断好坏要的是数字，说给人听要的是人话**。
# 比如"磁盘 92%"——判断要不要告警得比大小，讲给用户听得说"快满了"。
# 两件事分开做，但底层解析只写一遍（parse_* 就是调 read_* 再包装）。

def read_mem(out: str) -> dict:
    """从 free -m 的输出里读出原始数字（单位 MB）。读不到就返回空字典。纯函数。

    两个运维常识藏在这里：
      · 看内存够不够，看的是 available（还能拿来用的），不是 free（完全没占的）。
        Linux 会"闲着也是闲着"，把没用的内存拿去当磁盘缓存——所以 free 常年很小，
        但那是缓存，一有程序要内存立刻还给它。盯着 free 会天天虚惊。
      · swap 被用起来（used > 0）才说明真紧张：内存不够了，系统把数据挪到硬盘上，
        而硬盘比内存慢几个数量级，所以一旦开始 swap，机器会明显变卡。
    """
    info: dict = {}
    for line in (out or "").splitlines():
        cols = line.split()
        if not cols:
            continue
        if cols[0] == "Mem:" and len(cols) >= 4:
            info["total"] = _to_int(cols[1])
            info["used"] = _to_int(cols[2])
            info["free"] = _to_int(cols[3])
            # 第 7 列才是 available（老版本 free 没这列，退回 free）
            info["available"] = _to_int(cols[6], info["free"]) if len(cols) >= 7 else info["free"]
        elif cols[0] == "Swap:" and len(cols) >= 3:
            info["swap_total"] = _to_int(cols[1])
            info["swap_used"] = _to_int(cols[2])
    return info


def read_load(out: str):
    """从 uptime 的输出里读出 1/5/15 分钟负载，返回三元组；读不到返回 None。纯函数。"""
    m = re.search(r"load average:\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)", out or "")
    if not m:
        return None
    try:
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)))
    except ValueError:
        return None


def read_df_rows(out: str) -> list:
    """把 df -h 每一行读成一个字典：{fs, size, used, use_pct, mount}。纯函数。

    按列位置取（不是在算大小），所以"3.4G / 92%"这种给人看的格式照样能读出 92 这个数。
    """
    rows = []
    for line in (out or "").splitlines()[1:]:          # 第一行是表头
        cols = line.split()
        if len(cols) >= 6 and cols[4].endswith("%"):
            try:
                pct = int(cols[4].rstrip("%"))
            except ValueError:
                continue
            rows.append({"fs": cols[0], "size": cols[1], "used": cols[2],
                         "use_pct": pct, "mount": " ".join(cols[5:])})
    return rows


_ACTIVE_CN = {
    "active": "运行中",
    "reloading": "重载中",
    "inactive": "已停止（没在跑）",
    "failed": "已崩溃（failed，需要看日志）",
    "activating": "正在启动",
    "deactivating": "正在停止",
    "unknown": "未知（查不到这个服务）",
}


def parse_is_active(out: str) -> str:
    """把 systemctl is-active 的输出翻成人话。纯函数，可测。"""
    key = (out or "").strip().splitlines()[0].strip() if (out or "").strip() else "unknown"
    return _ACTIVE_CN.get(key, f"未知状态：{key}")


def parse_show(out: str) -> dict[str, str]:
    """把 systemctl show 的 key=value 输出解析成字典。纯函数，可测。"""
    info: dict[str, str] = {}
    for line in (out or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


def parse_uptime(out: str, cores: int | None = None) -> str:
    """从 uptime 输出里抠出"已经跑了多久"和"负载"。纯函数，可测。

    知道核数时，顺手把负载换算成"每核负载"——这才是有意义的那个数（见 build_health_cmds）。
    """
    text = (out or "").strip()
    if not text:
        return ""
    m = re.search(r"up\s+(.+?),\s+\d+\s+user", text)
    up = m.group(1).strip() if m else ""
    load = read_load(text)
    load_text = "/".join(f"{v:.2f}" for v in load) if load else ""
    parts = []
    if up:
        parts.append(f"已运行 {up}")
    if load_text:
        extra = f"（{cores} 核，每核 {load[0] / cores:.2f}）" if cores else ""
        parts.append(f"负载（1/5/15 分钟）{load_text}{extra}")
    return "，".join(parts)


def parse_free(out: str) -> str:
    """从 free -m 输出里抠出内存总量/已用/可用（MB）。纯函数，可测。"""
    m = read_mem(out)
    if not m or "total" not in m:
        return ""
    return f"内存 {m['used']}/{m['total']} MB 已用，可用 {m['available']} MB"


def parse_df(out: str, max_rows: int = 6) -> str:
    """从 df -h 输出里抠出各挂载点的使用率，挑最满的几行报出来。纯函数，可测。"""
    rows = read_df_rows(out)
    if not rows:
        return ""
    rows.sort(key=lambda r: r["use_pct"], reverse=True)
    shown = "；".join(f"{r['mount']} {r['use_pct']}%（{r['used']}/{r['size']}）"
                      for r in rows[:max_rows])
    return f"磁盘使用率最高：{shown}"


def parse_top_procs(out: str, top: int = 5) -> str:
    """从 ps 输出里挑出吃 CPU 最多的前几个进程。纯函数，可测。"""
    procs = []
    for line in (out or "").splitlines()[1:]:
        cols = line.split(None, 4)
        if len(cols) == 5:
            pid, cpu, mem, etime, comm = cols
            try:
                procs.append((float(cpu), pid, mem, etime, comm))
            except ValueError:
                continue
    if not procs:
        return ""
    procs.sort(reverse=True)
    shown = "，".join(f"{comm}(pid {pid}，CPU {cpu}%，内存 {mem}%)"
                     for cpu, pid, mem, _etime, comm in procs[:top])
    return f"最吃 CPU 的进程：{shown}"


def format_log_window(raw: str, keyword: str = "", tail_lines: int = 20) -> str:
    """把 journalctl 拉回来的日志做本地筛选 + 编行号（照 read_log_safely 的规矩）。纯函数，可测。

    行号是"在本次拉取的窗口内"的序号，不是全量日志的绝对行号——所以输出里会写明窗口大小，
    免得把相对行号当绝对行号用（证据要能对得上，这是运维回答问题的底线）。
    """
    lines = (raw or "").splitlines()
    try:
        n = max(1, min(int(tail_lines), LOG_TAIL_MAX))
    except (TypeError, ValueError):
        n = 20
    if keyword:
        hits = [(i, ln) for i, ln in enumerate(lines, 1) if keyword.lower() in ln.lower()]
        if not hits:
            return f"最近 {len(lines)} 行日志里没找到包含「{keyword}」的行"
        shown = hits[-n:]
        return (f"最近 {len(lines)} 行日志里命中「{keyword}」{len(hits)} 行，"
                f"下面是最后 {len(shown)} 行（行号是本次窗口内的序号）：\n"
                + "\n".join(f"{i}: {ln}" for i, ln in shown))
    start = max(0, len(lines) - n)
    shown = list(enumerate(lines[start:], start + 1))
    return (f"最近 {len(lines)} 行日志的最后 {len(shown)} 行"
            f"（行号是本次窗口内的序号）：\n"
            + "\n".join(f"{i}: {ln}" for i, ln in shown))


# ---------------------- 传输层（可注入的「门」） ----------------------

class SshRunner:
    """通过系统 ssh 客户端连远端主机。跟模型一样做成"可注入的门"：生产用它，测试用 FakeRunner。

    为什么用系统 ssh 而不是装个 SSH 库：真运维就是这么干的（密钥、known_hosts、跳板机
    都是 ssh 客户端的事），而且少一个依赖。所有参数走参数数组、shell=False，
    本地这一层也没有拼接。
    """

    def __init__(self, host: str, user: str = "root", key: str | None = None,
                 port: int = 22, timeout: int = 10, wake_cmd: str = ""):
        self.host = host
        self.user = user
        # 展开 ~：环境变量里写 ~/.ssh/id_ed25519 是很自然的写法，但 ssh 命令行不认
        # 这个波浪号（那是 shell 的活儿，我们走参数数组不过 shell），不展开就会报
        # "no such identity"。默认值也走这里，保证两条路一致。
        self.key = str(Path(key).expanduser()) if key else str(Path.home() / ".ssh" / "id_ed25519")
        self.port = int(port)
        self.timeout = int(timeout)
        # wake_cmd：本机靶机（WSL）空闲会被回收，连之前先敲一下把它叫醒。
        # 真·远程主机上留空即可（一直开着，不需要叫）。
        self.wake_cmd = wake_cmd

    def _ssh_argv(self, remote_cmd: str) -> list[str]:
        ssh = shutil.which("ssh") or "ssh"
        return [
            ssh,
            "-i", self.key,
            "-p", str(self.port),
            "-o", "BatchMode=yes",                 # 绝不弹密码提示：无人值守
            "-o", "StrictHostKeyChecking=accept-new",  # 首连记指纹，之后变了就报错（防中间人）
            "-o", "IdentitiesOnly=yes",
            "-o", "ConnectTimeout=8",
            f"{self.user}@{self.host}",
            remote_cmd,
        ]

    def probe(self) -> bool:
        """探活：主机当前连得上吗。连不上且配了 wake_cmd 就唤醒一次再试。"""
        if self._can_connect():
            return True
        if self.wake_cmd:
            try:                                   # 唤醒失败不算错，接着再试一次连接
                subprocess.run(self.wake_cmd, shell=True, capture_output=True, timeout=60)
            except Exception:
                pass
            return self._can_connect()
        return False

    def _can_connect(self) -> bool:
        try:
            r = subprocess.run(self._ssh_argv("true"), capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=self.timeout + 10)
            return r.returncode == 0
        except Exception:
            return False

    def run(self, cmd: str) -> tuple[int, str]:
        """执行一条远端命令，返回 (返回码, 输出)。命令先过远端白名单。

        连不上时返回 (255, 说明)——照 run_command 的规矩：异常吞成字符串，
        让模型能"看见"失败并把它讲给用户听，而不是把异常抛去炸掉整个循环。
        """
        ok, reason = screen_remote_cmd(cmd)
        if not ok:
            return 255, f"[远端护栏] 拒绝执行：{reason}"
        try:
            # encoding 必须写死 utf-8：Windows 默认按本地码页（cp936）解码远端回来的
            # UTF-8 字节，解不出的字节会变成"孤立代理字符"（\udcxx），传到下游直接炸
            # （真机上踩过：裁判护栏打分报 surrogates not allowed）。errors=replace 兜底。
            r = subprocess.run(self._ssh_argv(cmd), capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=self.timeout + 20)
        except subprocess.TimeoutExpired:
            return 255, f"远端主机 {self.host} 响应超时（{self.timeout + 20} 秒）"
        except Exception as exc:
            return 255, f"连远端主机 {self.host} 失败：{exc}"
        if r.returncode == 255:
            return 255, f"远端主机 {self.host} 连不上（{r.stderr.strip()[:120]}）"
        return r.returncode, (r.stdout or r.stderr)


class FakeRunner:
    """测试用的假 ssh：按"命令前缀 → 输出"的剧本回话，不碰网络。跟 FakeModel 一个套路。"""

    def __init__(self, script: dict[str, str] | None = None, rc: int = 0,
                 reachable: bool = True, host: str = "假SSH"):
        self.script = script or {}
        self.rc = rc
        self.reachable = reachable
        self.host = host                    # 降级文案里要报"哪台机器不可达"，假 runner 也得有个名
        self.calls: list[str] = []          # 记下被问过什么，测试好断言

    def probe(self) -> bool:
        return self.reachable

    def run(self, cmd: str) -> tuple[int, str]:
        ok, reason = screen_remote_cmd(cmd)          # 假 runner 也过白名单：护栏本身也要被测
        if not ok:
            return 255, f"[远端护栏] 拒绝执行：{reason}"
        self.calls.append(cmd)
        if not self.reachable:
            return 255, "[模拟] 主机不可达"
        for prefix, out in self.script.items():
            if cmd.startswith(prefix):
                return self.rc, out
        return self.rc, ""


def runner_from_env() -> "SshRunner | None":
    """按环境变量建一个 runner。没配主机就返回 None（= 只用本地演示数据，行为跟以前一样）。

    CLAUDE_OPS_SSH_HOST  远端主机（空 = 不启用真主机巡检）
    CLAUDE_OPS_SSH_USER  登录用户（默认 root）
    CLAUDE_OPS_SSH_KEY   私钥路径（默认 ~/.ssh/id_ed25519）
    CLAUDE_OPS_SSH_PORT  端口（默认 22）
    CLAUDE_OPS_SSH_WAKE  连之前先跑的本机命令（靶机是 WSL 时用来唤醒，空 = 不唤醒）
    """
    host = os.environ.get("CLAUDE_OPS_SSH_HOST", "").strip()
    if not host:
        return None
    return SshRunner(
        host=host,
        user=os.environ.get("CLAUDE_OPS_SSH_USER", "root").strip() or "root",
        key=os.environ.get("CLAUDE_OPS_SSH_KEY", "").strip() or None,
        port=int(os.environ.get("CLAUDE_OPS_SSH_PORT", "22") or 22),
        wake_cmd=os.environ.get("CLAUDE_OPS_SSH_WAKE", "").strip(),
    )


# ---------------------- 对外的三个查询（agent 调这三个） ----------------------

def remote_service(unit: str, runner) -> str:
    """问远端主机：这个服务活着吗、开机自启吗、重启过几次。只读。"""
    ok, reason = safe_unit(unit)
    if not ok:
        return reason
    if runner is None:
        return "没配远端主机（CLAUDE_OPS_SSH_HOST），只能查本地演示数据"
    if not runner.probe():
        return f"远端主机 {getattr(runner, 'host', '?')} 不可达：可能没开机，或网络/密钥不对"
    cmds = build_service_cmds(unit)
    rc, active_out = runner.run(cmds["active"])
    if rc == 255:
        return active_out
    _, enabled_out = runner.run(cmds["enabled"])
    _, show_out = runner.run(cmds["show"])
    info = parse_show(show_out)
    bits = [f"服务 {unit}：状态【{parse_is_active(active_out)}】"]
    if info.get("LoadState") and info["LoadState"] not in ("loaded", ""):
        bits.append(f"加载状态 {info['LoadState']}")
    if info.get("SubState"):
        bits.append(f"子状态 {info['SubState']}")
    if info.get("MainPID") and info["MainPID"] not in ("0", ""):
        bits.append(f"主进程 pid {info['MainPID']}")
    if info.get("ActiveEnterTimestamp"):
        bits.append(f"进入该状态时间 {info['ActiveEnterTimestamp']}")
    restarts = info.get("NRestarts", "")
    if restarts.isdigit() and int(restarts) > 0:
        bits.append(f"⚠ 已重启过 {restarts} 次（重启多 = 进程在反复崩，重点看日志）")
    enabled = (enabled_out or "").strip().splitlines()[0] if (enabled_out or "").strip() else ""
    if enabled:
        bits.append(f"开机自启：{enabled}")
    return "，".join(bits)


def remote_logs(unit: str, keyword: str = "", tail_lines: int = 20, runner=None) -> str:
    """翻远端主机的系统日志（journalctl），可按关键词筛。只读。"""
    ok, reason = safe_unit(unit)
    if not ok:
        return reason
    if runner is None:
        return "没配远端主机（CLAUDE_OPS_SSH_HOST），只能查本地演示数据"
    if not runner.probe():
        return f"远端主机 {getattr(runner, 'host', '?')} 不可达：可能没开机，或网络/密钥不对"
    rc, out = runner.run(build_log_cmd(unit))
    if rc == 255:
        return out
    return format_log_window(out, keyword=keyword, tail_lines=tail_lines)


def remote_health(runner) -> str:
    """看远端主机整体健康：系统、跑了多久、负载、内存、磁盘、吃 CPU 的进程。只读。"""
    if runner is None:
        return "没配远端主机（CLAUDE_OPS_SSH_HOST），只能查本地演示数据"
    if not runner.probe():
        return f"远端主机 {getattr(runner, 'host', '?')} 不可达：可能没开机，或网络/密钥不对"
    cmds = build_health_cmds()
    out = {}
    for k in ("os", "uptime", "cores", "free", "df", "ps"):
        rc, text = runner.run(cmds[k])
        if rc == 255:
            return text
        out[k] = text
    os_name = ""
    for line in (out["os"] or "").splitlines():
        if line.startswith("PRETTY_NAME="):
            os_name = line.split("=", 1)[1].strip().strip('"')
    # 核数拿不到就是 None（老机器没 nproc、命令被拦等）——不编一个默认值糊弄，
    # 后面 parse_uptime 会老老实实只报原始负载，不报"每核"。
    cores = None
    first = (out.get("cores") or "").strip().splitlines()
    if first and _to_int(first[0]) > 0:
        cores = _to_int(first[0])
    bits = []
    if os_name:
        bits.append(f"系统 {os_name}")
    for key in ("uptime", "free", "df", "ps"):
        if key == "uptime":
            text = parse_uptime(out[key], cores=cores)
        elif key == "free":
            text = parse_free(out[key])
        elif key == "df":
            text = parse_df(out[key])
        else:
            text = parse_top_procs(out[key])
        if text:
            bits.append(text)
    return "；".join(bits) if bits else "远端主机没返回可用信息"

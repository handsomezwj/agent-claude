# patrol.py — 值班巡检：把一堆数字，变成一句结论
#
# 问题：remote_ops 已经把真主机的数字取回来了——负载 4.2、磁盘 92%、内存剩 300MB。
#       可**数字不是结论**。领导不问"你 disk 多少"，他问一句：
#       **"这台机器到底有没有事？"**
#       你得自己先算明白：92% 算不算满？4.2 是高还是低？剩 300MB 是紧张还是够用？
#
# 答案：值班巡检（patrol）——运维上班第一件事，把所有机器过一遍，
#       该看的看、该比的比、最后出一份**有结论**的报告：
#       没事就一句"一切正常"，有事就明确指出"哪一项、多严重、为什么"。
#
# 和 remote_ops 的分工（一句话分清）：
#   remote_ops = **取数**（怎么连上、怎么防乱来、怎么把输出读出来）
#   patrol.py  = **判断**（多少算好、几项要报、最后的结论是什么）
#   本模块一行 SSH 都不写，全靠 remote_ops 那三道门把数取回来——这叫各管一摊。
#
# 心法对照（面试可讲）：
#   监控 = 盯着看（一直看着，出事就叫）
#   巡检 = 定期过一遍（一天看几次，出一份报告）
#   告警 = 判断完之后的动作（这份报告里带 ❌ 的就该叫人了）
#   阈值 = 判断用的尺子。尺子不对，要么天天虚惊（狼来了），要么出事不报（最要命）
#
# 三个最容易判错的坑（本模块专门处理，每一条都有测试兜着）：
#   ① **负载不除以核数就没意义**——4.0 在 2 核机器上是过载，在 16 核机器上是闲着
#   ② **内存要看 available 不是 free**——Linux 拿空闲内存当磁盘缓存，free 常年很小是正常的，
#      盯着 free 看会天天虚惊；真紧张的表现是**开始用 swap**
#   ③ **df 里有些"盘"根本不是这台机器的**——WSL 里能看到 Windows 的 C 盘（常年 92%），
#      容器里能看到宿主机盘、网络盘、snap 的只读镜像（天生 100%）。
#      把别人的盘算成自己机器的，就是天天误报的根源。

from collections import namedtuple
from datetime import datetime

from remote_ops import (
    build_health_cmds,
    build_service_cmds,
    parse_is_active,
    parse_show,
    read_df_rows,
    read_load,
    read_mem,
    safe_unit,
)

# ---------------------- 报告里的四档结论 ----------------------

LEVEL_CRIT = "严重"
LEVEL_WARN = "警告"
LEVEL_INFO = "提示"
LEVEL_OK = "正常"

_ORDER = {LEVEL_CRIT: 0, LEVEL_WARN: 1, LEVEL_INFO: 2, LEVEL_OK: 3}
_ICON = {LEVEL_CRIT: "❌", LEVEL_WARN: "⚠ ", LEVEL_INFO: "ℹ ", LEVEL_OK: "✅"}

# 一条发现 = 什么级别 + 说的是谁 + 具体怎么回事
Finding = namedtuple("Finding", "level item detail")


def _worse(a: str, b: str) -> str:
    """两个级别取更严重的那个。纯函数。"""
    return a if _ORDER[a] <= _ORDER[b] else b


# ---------------------- 阈值（尺子） ----------------------
# 全写成常量，是为了三件事：**讲得出依据**（面试被问"凭什么是 85%"）、
# **改得动**（业务不同、尺子不同，改一行就行）、**测得了**（测试直接引用常量，不写魔数）。

DISK_WARN_PCT = 85           # 磁盘过这条线开始提醒
DISK_CRIT_PCT = 95           # 过这条线基本写不进去了
MEM_AVAIL_WARN_PCT = 15      # 可用内存低于总内存的 15% 提醒
MEM_AVAIL_CRIT_PCT = 5       # 低于 5% 随时可能 OOM
SWAP_WARN_PCT = 20           # swap 用了 20% 说明物理内存不够了
SWAP_CRIT_PCT = 50           # 用了一半，机器会明显变卡
LOAD_PER_CORE_WARN = 1.0     # 每核负载过 1 = 活儿开始排队
LOAD_PER_CORE_CRIT = 2.0     # 过 2 = 排了两倍队，明显跟不上

# 这些"文件系统"不是这台机器自己的盘，判磁盘时不参与打分。
# 判断依据：按文件系统类型 + 挂载点前缀两道筛，宁可漏报也不误报。
DISK_SKIP_FS = ("tmpfs", "devtmpfs", "none", "overlay", "squashfs", "shm")
DISK_SKIP_MOUNTS = ("/mnt/", "/usr/lib/wsl", "/snap/", "/run/", "/sys/", "/proc/")


def _is_foreign(row: dict) -> bool:
    """这个挂载点是不是"别人的盘"（宿主机的、网络的、内存里的只读镜像）。纯函数。"""
    fs = (row.get("fs") or "").strip()
    mount = (row.get("mount") or "").strip()
    if fs in DISK_SKIP_FS:
        return True
    if mount.startswith("/dev/loop") or mount.startswith("/dev/sr"):
        return True
    return any(mount == p.rstrip("/") or mount.startswith(p) for p in DISK_SKIP_MOUNTS)


# ---------------------- 各项判断（全是纯函数，离线可测） ----------------------

def judge_disk(rows: list) -> tuple:
    """判断磁盘。返回 (发现列表, 被跳过的挂载点说明列表)。纯函数。

    被跳过的那些会**明着写在报告里**——跳过了但不能装作没看见，
    这是巡检报告的诚实底线（不然用户会以为你全看过了）。
    """
    real = [r for r in rows if not _is_foreign(r)]
    skipped = [f"{r['mount']}（{r['use_pct']}%）" for r in rows if _is_foreign(r)]
    if not real:
        return [Finding(LEVEL_INFO, "磁盘", "这次输出里没有属于本机的文件系统，判不了")], skipped

    findings, ok_rows = [], []
    for r in real:
        pct, mount = r["use_pct"], r["mount"]
        head = f"{pct}%（{r['used']}/{r['size']}）"
        if pct >= DISK_CRIT_PCT:
            findings.append(Finding(LEVEL_CRIT, f"磁盘 {mount}",
                                    head + "，已经满了，任何写操作都会失败（日志都写不进去）"))
        elif pct >= DISK_WARN_PCT:
            findings.append(Finding(LEVEL_WARN, f"磁盘 {mount}",
                                    head + f"，超过 {DISK_WARN_PCT}% 警戒线，该清理了"))
        else:
            ok_rows.append(r)

    if ok_rows:
        fullest = max(ok_rows, key=lambda r: r["use_pct"])
        if findings:
            detail = (f"其余 {len(ok_rows)} 个挂载点正常，"
                      f"最满的 {fullest['mount']} 才 {fullest['use_pct']}%")
        elif len(ok_rows) == 1:
            detail = f"挂载点 {fullest['mount']} 正常（{fullest['use_pct']}%）"
        else:
            detail = f"{len(ok_rows)} 个挂载点都正常，最满的 {fullest['mount']} {fullest['use_pct']}%"
        findings.append(Finding(LEVEL_OK, "磁盘", detail))
    return findings, skipped


def judge_memory(info: dict) -> list:
    """判断内存和 swap。纯函数。

    内存看 available（还能拿来用的），不是 free（完全没占的）——原因见模块开头坑②。
    swap 只在**真被用起来**的时候才报：swap 用了 0 就不占报告篇幅（报告要的是信噪比，
    健康项写一大堆，真出事的反而被淹了）。

    阈值口径跟磁盘统一：**到达阈值就报警**（含等号）。这一点必须全模块一致——
    同一份报告里磁盘"到 95% 报严重"、内存"要低于 5% 才报严重"，
    两把尺子量法不同，迟早有人按错的那把做决策。
    """
    findings = []
    if not info or info.get("total", 0) <= 0:
        return [Finding(LEVEL_INFO, "内存", "没读到内存信息，判不了")]

    total = info["total"]
    avail = info.get("available", info.get("free", 0))
    pct = avail * 100.0 / total
    if pct <= MEM_AVAIL_CRIT_PCT:
        level, tail = LEVEL_CRIT, "，随时可能触发 OOM（系统强杀进程腾内存）"
    elif pct <= MEM_AVAIL_WARN_PCT:
        level, tail = LEVEL_WARN, "，内存吃紧，先看是哪个进程在涨"
    else:
        level, tail = LEVEL_OK, ""
    findings.append(Finding(level, "内存", f"可用 {avail}/{total} MB（{pct:.0f}%）{tail}"))

    swap_total, swap_used = info.get("swap_total", 0), info.get("swap_used", 0)
    if swap_total > 0:
        spct = swap_used * 100.0 / swap_total
        if spct >= SWAP_CRIT_PCT:
            findings.append(Finding(LEVEL_CRIT, "Swap",
                                    f"已用 {swap_used}/{swap_total} MB（{spct:.0f}%），"
                                    f"大量拿硬盘当内存用，机器会明显变卡"))
        elif spct >= SWAP_WARN_PCT:
            findings.append(Finding(LEVEL_WARN, "Swap",
                                    f"已用 {swap_used}/{swap_total} MB（{spct:.0f}%），"
                                    f"开始动用 swap 了，说明物理内存不够用"))
    return findings


def judge_load(load, cores) -> list:
    """判断负载。纯函数。

    **拿不到核数就不下结论**——只报原始数字并注明"判不了"。
    这是巡检的另一个底线：证据不足时，宁可说"我不知道"，也不要硬给一个听着专业的结论。
    """
    if load is None:
        return [Finding(LEVEL_INFO, "负载", "没读到负载数字，判不了")]
    if not cores:
        return [Finding(LEVEL_INFO, "负载",
                        f"1/5/15 分钟 {load[0]:.2f}/{load[1]:.2f}/{load[2]:.2f}"
                        f"（拿不到核数，算不出每核负载，所以不下结论）")]
    per = load[0] / cores
    if per >= LOAD_PER_CORE_CRIT:
        level, tail = LEVEL_CRIT, "，活儿排了两倍以上的队，机器已经明显跟不上"
    elif per >= LOAD_PER_CORE_WARN:
        level, tail = LEVEL_WARN, "，活儿开始排队了，再看看是哪个进程在吃"
    else:
        level, tail = LEVEL_OK, ""
    return [Finding(level, "负载", f"{cores} 核，1 分钟负载 {load[0]:.2f}（每核 {per:.2f}）{tail}")]


# is-enabled 返回的东西里，**只有一部分才是"你该管的问题"**。systemctl 给的状态含义各不相同，
# 一律当成"没自启=有问题"就会天天虚惊。真机上踩过这个假警报，所以去机器上验过再写死：
#
#   enabled   —— 开机自启，正常
#   static    —— **unit 文件里没有 [Install] 段**，压根 enable 不了。
#                真机证据：systemd-journald 就是 static，
#                `systemctl cat systemd-journald.service | grep -c '\[Install\]'` 输出 0；
#                而 cron 是 enabled，同一命令输出 1。journald 由 systemd 在启动过程中
#                直接拉起来，不靠 enable——**把它报成"不自启"是纯假警报**。
#   indirect  —— 靠别的单元间接触发，同上，不该报
#   disabled  —— 能 enable 而没 enable：机器重启后它不会自己回来，这是**真该提醒的**
#   masked    —— 被屏蔽了，连手工 start 都会失败，比 disabled 更严重，该**警告**
_ENABLED_FINE = ("enabled", "enabled-runtime", "static", "indirect", "alias", "generated")
_ENABLED_MASKED = ("masked", "masked-runtime")


def judge_service(unit: str, active_out: str, enabled_out: str, show_out: str) -> "Finding":
    """判断一个服务。纯函数。

    前提认知：**巡检清单上列的服务，就是"应该活着的"**——所以"没在跑"本身就是问题，
    不需要再问一遍"它该不该跑"（那是写清单的人的责任）。

    最值钱的一条：**"运行中"不等于没事**。一个进程反复崩溃、又被 systemd 拉起来，
    is-active 一直显示运行中，但 NRestarts 会蹭蹭涨——只看"运行中"就漏了。
    """
    info = parse_show(show_out)
    lines = (active_out or "").strip().splitlines()
    state = lines[0].strip() if lines else ""
    load_state = info.get("LoadState", "")

    if load_state == "not-found" or state in ("", "unknown"):
        return Finding(LEVEL_CRIT, unit, "不存在（没这个服务，或者服务名写错了）")

    level = LEVEL_OK if state in ("active", "reloading") else LEVEL_CRIT
    facts = [f"状态【{parse_is_active(active_out)}】"]
    if level == LEVEL_CRIT:
        facts.append("清单上的服务本该活着，要去看日志找原因")

    if info.get("MainPID") and info["MainPID"] not in ("0", ""):
        facts.append(f"pid {info['MainPID']}")

    restarts = info.get("NRestarts", "")
    if restarts.isdigit() and int(restarts) > 0:
        level = _worse(level, LEVEL_WARN)
        facts.append(f"重启过 {restarts} 次（进程在反复崩，光看『运行中』会漏掉这个）")

    enabled = (enabled_out or "").strip().splitlines()
    enabled = enabled[0].strip() if enabled else ""
    if enabled in _ENABLED_MASKED:
        level = _worse(level, LEVEL_WARN)
        facts.append(f"已被屏蔽（{enabled}）——现在连手工启动都会失败，要用得先解屏蔽")
    elif enabled and enabled not in _ENABLED_FINE:
        level = _worse(level, LEVEL_INFO)
        facts.append(f"开机不自启（{enabled}）——机器重启后它不会自己回来")
    return Finding(level, unit, "，".join(facts))


# ---------------------- 报告 ----------------------

# 清单里出现这些字符，就整条拒掉、一个字节都不发——注意**不含换行和空白**，
# 因为那是清单合法的分隔符（"ssh nginx" 本来就该拆成两个）。
_UNITS_FORBIDDEN = (";", "|", "&", "$", "`", ">", "<")


def screen_units(text) -> tuple:
    """清单整体过一道门，返回 (是否放行, 原因)。纯函数。

    为什么不像命令那样"逐条判"：清单是**逗号/空格分隔的名字列表**，
    一旦里面冒出 ; | & 这些玩意儿，说明它压根不是清单——那就不跟它玩解析了，整条拒。

    真机上踩过一个反面教材：`"ssh; rm -rf /"` 按空格拆开是 ["ssh;","rm","-rf","/"]，
    其中 **"rm" 居然是个合法服务名**（正则允许字母），于是真的会发出 `systemctl is-active rm`。
    那条命令本身是只读的、无害（门没被攻破），但"把攻击串拆成好几段、其中一段碰巧合法"
    这种路子不能开——**解析前先整体判一次**，比事后指望每段都判对要可靠。
    """
    if isinstance(text, (list, tuple)):
        return True, "ok"
    for ch in _UNITS_FORBIDDEN:
        if ch in str(text or ""):
            return False, f"清单里出现禁止字符 {ch}"
    return True, "ok"


def parse_units(text) -> list:
    """把"ssh, nginx cron"这样的清单拆成服务名列表：逗号/空格/换行都认，去重保序。纯函数。"""
    if isinstance(text, (list, tuple)):
        raw = [str(x) for x in text]
    else:
        raw = str(text or "").replace(",", " ").replace("，", " ").replace("\n", " ").split()
    seen, out = set(), []
    for name in raw:
        name = name.strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _section(title: str, findings: list) -> list:
    """把一组发现渲染成报告里的几行，严重的排前面。纯函数。"""
    if not findings:
        return []
    lines = [title]
    for f in sorted(findings, key=lambda f: _ORDER[f.level]):
        lines.append(f"  {_ICON[f.level]} [{f.level}] {f.item}：{f.detail}")
    return lines


def build_report(host: str, ts: str, service_findings: list, host_findings: list,
                 skipped: list, units_count: int) -> str:
    """拼出完整报告：**结论先行**——看报告的人只想知道"有没有事"。纯函数。"""
    everything = list(service_findings) + list(host_findings)
    counts = {lv: sum(1 for f in everything if f.level == lv)
              for lv in (LEVEL_CRIT, LEVEL_WARN, LEVEL_INFO)}
    if counts[LEVEL_CRIT]:
        verdict = f"❌ 发现 {counts[LEVEL_CRIT]} 项严重问题，需要立刻处理"
    elif counts[LEVEL_WARN]:
        verdict = f"⚠  发现 {counts[LEVEL_WARN]} 项警告，建议尽快看一下"
    elif counts[LEVEL_INFO]:
        verdict = f"✅ 没有发现异常（另有 {counts[LEVEL_INFO]} 项信息供参考）"
    else:
        verdict = "✅ 一切正常，未发现异常"

    lines = [f"===== 值班巡检报告 · {host} =====",
             f"巡检时间：{ts}",
             f"结论：{verdict}", ""]
    lines += _section(f"【服务】巡检了 {units_count} 个服务", service_findings)
    if service_findings:
        lines.append("")
    lines += _section("【主机】", host_findings)
    if skipped:
        lines += ["", f"【说明】{len(skipped)} 个挂载点不属于这台机器（{('、'.join(skipped))[:160]}），"
                      f"已跳过判分——别拿别人的盘吓自己"]
    return "\n".join(lines)


def patrol_host(units=None, runner=None, now=None) -> str:
    """跑一次值班巡检，返回一份带结论的报告。只读，全程走 remote_ops 的三道门。

    units  ：要巡检的服务清单（字符串或列表）。不传就用调用方给的默认值。
    runner ：怎么连主机。生产是 SshRunner，测试是 FakeRunner（老规矩：可注入的门）。
    now    ：当前时间。可注入，测试才能断言出固定的时间戳。
    """
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    host = getattr(runner, "host", "?")

    # 清单先整体过门，再过不了就直接返回——**连探活都不做**，一个字都不发。
    # 顺序有意为之：先判输入，再碰网络（输入不老实，没必要浪费一次连接）。
    ok, reason = screen_units(units)
    if not ok:
        return "\n".join([
            f"===== 值班巡检报告 · {host} =====",
            f"巡检时间：{stamp}",
            "结论：❌ 巡检清单不合法，没有向主机发出任何命令",
            "",
            f"说明：{reason}。巡检清单只该是服务名列表（例如 ssh,nginx），",
            "     出现这些字符说明输入不老实——整条拒掉，不跟它玩解析。",
        ])

    unit_list = parse_units(units)

    if runner is None:
        return "没配远端主机（CLAUDE_OPS_SSH_HOST），巡检做不了——只能查本地演示数据"

    if not runner.probe():
        return "\n".join([
            f"===== 值班巡检报告 · {host} =====",
            f"巡检时间：{stamp}",
            "结论：❌ 巡检没跑成——主机连不上",
            "",
            f"说明：{host} 不可达（可能没开机、网络不通、或者密钥不对）。",
            "     这次巡检是**没有结论**的——不能当成『一切正常』，得有人去看一眼。",
        ])

    # ---- 服务 ----
    service_findings = []
    for unit in unit_list:
        ok, reason = safe_unit(unit)
        if not ok:
            service_findings.append(Finding(LEVEL_WARN, unit, f"清单里这个名字不合法，已跳过（{reason}）"))
            continue
        cmds = build_service_cmds(unit)
        rc, active_out = runner.run(cmds["active"])
        if rc == 255:
            return _failed_report(host, stamp, active_out)
        _, enabled_out = runner.run(cmds["enabled"])
        _, show_out = runner.run(cmds["show"])
        service_findings.append(judge_service(unit, active_out, enabled_out, show_out))

    # ---- 主机 ----
    cmds = build_health_cmds()
    out = {}
    for key in ("uptime", "cores", "free", "df"):
        rc, text = runner.run(cmds[key])
        if rc == 255:
            return _failed_report(host, stamp, text)
        out[key] = text

    cores = None
    cores_line = (out["cores"] or "").strip().splitlines()
    if cores_line and cores_line[0].strip().isdigit() and int(cores_line[0].strip()) > 0:
        cores = int(cores_line[0].strip())

    host_findings = []
    host_findings += judge_load(read_load(out["uptime"]), cores)
    host_findings += judge_memory(read_mem(out["free"]))
    disk_findings, skipped = judge_disk(read_df_rows(out["df"]))
    host_findings += disk_findings

    return build_report(host, stamp, service_findings, host_findings, skipped, len(unit_list))


def _failed_report(host: str, stamp: str, reason: str) -> str:
    """巡检跑到一半断了（连上了又掉线）：也得给一份报告，不能抛异常炸掉 Agent 循环。"""
    return "\n".join([
        f"===== 值班巡检报告 · {host} =====",
        f"巡检时间：{stamp}",
        "结论：❌ 巡检没跑完——中途和主机断了",
        "",
        f"原因：{reason}",
        "     这次巡检没结论，得重跑一遍，别当成『一切正常』。",
    ])

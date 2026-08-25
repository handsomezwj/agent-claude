# demo_service.py — 一个"假服务"：用 pid 文件 + 日志模拟真实服务的启停状态。
# 运维演示用它控制 order-api 的"在跑 / 挂掉"：
#   python demo_service.py start  order-api   # 服务"启动"（写 pid 文件 + 写日志）
#   python demo_service.py stop   order-api   # 服务"停止"（删 pid 文件 + 写日志）
#   python demo_service.py status order-api   # 查状态（运维 agent 的 check_service 读同一套文件）
# 测试可传 --data-dir 指向临时目录，不污染演示数据。
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def load_services(data_dir):
    p = Path(data_dir) / "services.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def append_log(data_dir, service, line):
    svc = load_services(data_dir).get(service)
    if not svc:
        return
    log_path = Path(data_dir) / svc["log_file"]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{ts} {line}\n")


def start(data_dir, service):
    svc = load_services(data_dir).get(service)
    if not svc:
        return f"未知服务：{service}"
    pid_file = Path(data_dir) / svc["pid_file"]
    if pid_file.exists():
        pid = pid_file.read_text(encoding="utf-8", errors="replace").strip()
        return f"{service} 已经在运行（pid={pid}），无需重复启动"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    append_log(
        data_dir,
        service,
        f"INFO [startup] {service} started (pid={os.getpid()}, port={svc['port']})",
    )
    return f"{service} 已启动（pid={os.getpid()}）"


def stop(data_dir, service):
    svc = load_services(data_dir).get(service)
    if not svc:
        return f"未知服务：{service}"
    pid_file = Path(data_dir) / svc["pid_file"]
    if pid_file.exists():
        pid_file.unlink()
        append_log(data_dir, service, f"INFO [startup] {service} stopped")
        return f"{service} 已停止"
    return f"{service} 本来就没在运行"


def status(data_dir, service):
    svc = load_services(data_dir).get(service)
    if not svc:
        return f"未知服务：{service}"
    pid_file = Path(data_dir) / svc["pid_file"]
    if pid_file.exists():
        pid = pid_file.read_text(encoding="utf-8", errors="replace").strip()
        return f"{service}：运行中（pid={pid}）"
    return f"{service}：停止"


def main():
    parser = argparse.ArgumentParser(description="假服务：模拟服务启停，配合运维 agent 演示")
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("service")
    parser.add_argument("--data-dir", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        print(f"数据目录不存在：{data_dir}")
        sys.exit(1)

    if args.action == "start":
        print(start(data_dir, args.service))
    elif args.action == "stop":
        print(stop(data_dir, args.service))
    else:
        print(status(data_dir, args.service))


if __name__ == "__main__":
    main()

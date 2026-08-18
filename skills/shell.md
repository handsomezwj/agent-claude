# Shell 命令指南

## 概述
此技能提供常用 Shell 命令和脚本编写技巧。

## 文件操作
- `ls -la` — 列出目录所有文件（含隐藏文件）
- `find . -name "*.py"` — 递归查找 Python 文件
- `grep -r "pattern" .` — 递归搜索文本
- `wc -l <file>` — 统计行数
- `du -sh <dir>` — 查看目录大小

## 文本处理
- `cat file | sort | uniq -c | sort -rn` — 统计并排序
- `sed 's/old/new/g' file` — 文本替换
- `awk '{print $1}' file` — 提取列
- `head -n 10` / `tail -n 10` — 查看文件头/尾

## 系统信息
- `top` / `htop` — 进程监控
- `df -h` — 磁盘使用情况
- `free -h` — 内存使用情况（Linux）
- `ps aux` — 列出所有进程

## 网络
- `curl -I <url>` — 查看 HTTP 响应头
- `ping <host>` — 测试网络连通性
- `netstat -an` — 查看网络连接
- `nslookup <domain>` — DNS 查询

## 安全提醒
- 避免在命令中直接使用用户输入而不做验证
- 敏感信息（密码、Token）不要出现在命令行历史中
- 优先使用参数列表而非字符串拼接

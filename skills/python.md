# Python 编程指南

## 概述
此技能提供 Python 编程的最佳实践和常用模式。

## 代码风格
- 遵循 PEP 8 代码风格规范
- 使用 `black` 自动格式化代码
- 类型注解使用 `typing` 模块
- 文档字符串使用 Google 风格或 NumPy 风格

## 常用库
- `requests` — HTTP 请求
- `rich` — 终端美化输出
- `click` / `typer` — CLI 工具开发
- `pytest` — 单元测试
- `pathlib` — 文件路径处理

## 异步编程
- 使用 `asyncio` 进行异步编程
- `aiohttp` 用于异步 HTTP 请求
- `httpx` 支持同步和异步双模式

## 注意事项
- 始终使用虚拟环境（venv/conda）
- 敏感信息使用环境变量或 `.env` 文件
- 避免使用 `shell=True`，优先使用 `subprocess.run` + 参数列表

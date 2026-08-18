# Git 版本控制指南

## 概述
此技能提供 Git 版本控制的常用命令和工作流程。

## 基础命令
- `git status` — 查看工作区状态
- `git add <file>` — 暂存文件
- `git commit -m "message"` — 提交更改
- `git push` / `git pull` — 推送/拉取远程仓库
- `git log --oneline` — 查看提交历史

## 分支管理
- `git branch <name>` — 创建分支
- `git checkout -b <name>` — 创建并切换分支
- `git merge <branch>` — 合并分支
- `git rebase <branch>` — 变基到指定分支

## 撤销操作
- `git reset HEAD <file>` — 取消暂存
- `git checkout -- <file>` — 撤销文件修改
- `git revert <commit>` — 撤销某次提交
- `git reset --soft HEAD~1` — 撤销最近一次提交但保留更改

## 工作流建议
- 主分支保护，通过 PR/MR 合并
- 提交信息使用约定式提交格式：`type(scope): description`
- 定期 `git fetch` 同步远程信息
- 合并前先 `rebase` 保持历史整洁

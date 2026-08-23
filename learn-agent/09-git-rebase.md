# 第 12 课：git 实战——分支分叉 → rebase → 先拉后推

> 背景：把 resume-advisor 推上 GitHub 时，push 被拒（`! [rejected] ... non-fast-forward`）。这一课把它彻底讲懂。

## 一、什么是"分支分叉"（divergence）

想象 git 历史是一条向前走的路，每个 commit 是一块里程碑：

```
                    E（网页端改 README）
                  ╱
        A ── B ──┤
                  ╲
                    D（本地加截图）
```

- `B` 是我们第一次 push 的共同起点
- 之后**两个端各走了一步**：网页端提交了 `E`，本地提交了 `D`
- 这条路在 `B` 之后**分成了两条**——这就是分叉

为什么会分叉？因为 git 的提交历史是"看不见别人的"，两端各改各的，直到 push 才撞见。

## 二、为什么 push 被拒（non-fast-forward）

git 有个保护规则：**如果远程有新提交，而本地没有（本地不是远程的子集），就拒绝直接 push。**

```
本地:  A → B → D
远程:  A → B → E
```

直接 push 意味着"用我的线盖掉你的线"——`E`（网页端那步）就丢了。git 宁可拒绝，也不让数据丢失。这就是报错里那句 `hint: 'git pull' before pushing again.` 的意思。

**关键认知：push 被拒不是错误，是 git 在保护你。** 它想让你先看看远程多了什么，再决定怎么合并。

## 三、怎么解：`git pull --rebase`（核心）

rebase = **把本地提交"摘下来，重放到远程最新提交的屁股后面"**：

```
            D'（本地提交，换了新位置）
           ╱
        A → B → E → deebb8f   （一条直线了）
```

- `E` 在前，`D'` 在后，历史变成**一条直线**
- 原来分叉的两条路合并成一条，所有提交都在
- push 就顺利了：本地现在是远程的子集

命令：`git pull --rebase origin main` 然后 `git push origin main`

**为什么是 rebase 而不是 merge？**
- merge 会把两条线合起来，留下一个"合并点"，历史出现分叉再汇合的折线
- rebase 是**把线捋直**，历史干净线性，适合个人项目/小团队
- 面试问到"merge 和 rebase 区别"，核心一句：merge 保历史原样、留合并点；rebase 重写历史、捋直成一条线

## 四、多端编辑冲突了怎么办？

这次网页端改「技术亮点」标题、本地改「效果演示」——改的是 README **不同位置**，git 能自动合并（零冲突）。

如果两边改了**同一行**，rebase 会停下来报冲突（`CONFLICT (content)`），让你手动选：
1. 打开冲突文件，会看到 `<<<<<<< HEAD ... ======= ... >>>>>>>` 标记
2. 保留你想要的部分，删掉标记
3. `git add <文件>` 然后 `git rebase --continue`

## 五、口诀

1. **先拉后推**：push 之前先 `git pull --rebase`，让本地跟上远程
2. **被拒先看**：push 被拒 → `git fetch` 看远程多了啥，别硬推
3. **不同行自动并，同一行手动并**：冲突是正常的，不是灾难

## 六、今天顺带练会的 git 基础

| 命令 | 干啥 |
|---|---|
| `git init` | 文件夹变仓库 |
| `git add -A` / `git commit -m "..."` | 拍快照 |
| `git branch -M main` | 本地分支改名对齐 GitHub 主分支约定 |
| `git fetch` | 只看远程有什么（不动本地） |
| `git log --oneline` | 看提交历史 |
| `git pull --rebase` | 拉远程 + 把本地提交重放上去 |

## 七、安全习惯（push 前必做）

- 确认 `.env`（含密钥）没进 commit：`.gitignore` 排除 + `git diff --cached --name-only` 检查
- 公开仓库 = 给全世界看，README 写"面向面试官"，代码不藏密钥
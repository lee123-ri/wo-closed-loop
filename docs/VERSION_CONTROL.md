# 版本管理流程

## 分支策略

```
main ──────────────────────────────────────→ 生产分支
  │
  └── feature/xxx ──→ PR ──→ squash merge ──→ main
```

## 日常开发

```bash
# 1. 从 main 拉最新
git checkout main
git pull origin main

# 2. 开 feature 分支
git checkout -b feature/描述

# 3. 开发 + 提交
git add -A
git commit -m "feat: 做了什么"

# 4. 推送
git push origin feature/描述

# 5. 在 GitHub 创建 PR → squash merge → main
```

## 版本号规则

`v<主版本>.<次版本>.<修订号>`

| 变更类型 | 版本号 | 示例 |
|---------|--------|------|
| 大功能/架构变更 | 主版本 +1 | v1.0.0 |
| 新功能/模块 | 次版本 +1 | v0.6.0 |
| Bug修复/小调整 | 修订号 +1 | v0.5.1 |

## 当前版本

**v0.5.0** — 2026-08-12

## 发布流程

```bash
# 发布时打 tag
git checkout main
git pull origin main
git tag v0.6.0
git push origin v0.6.0
```
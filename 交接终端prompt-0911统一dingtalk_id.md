# 交接终端：统一 users.dingtalk_id 为钉钉新格式 userId

**目标**：把系统 `users.dingtalk_id` 统一成钉钉**新格式 userId**（形如 `20260629192000997-1218-257858D99`），这是红点 @（`at.atUserIds`）和工作通知认人的前提。当前库里 union_id / 旧 staffId 混存，会导致 @ 不到人。

**前置**：本机 `dws` 已认证（能跑 `dws contact`）。PG 原生 running。

**步骤**：

1. 先确认 dws 返回的 userId 是新格式（打印样例，别急着写库）：
```bash
dws contact +list-dept-members --depts 1086698109 --format json | head -c 2000
```
确认成员里 `userId` 字段是 `2026…-xxxx-…` 这种新格式（不是纯数字 old staffId，也不是 `union_` 开头）。

2. 跑同步脚本（它会按 userId 去重、按 name 更新/新建，把你的 dingtalk_id 覆盖成新格式）：
```bash
cd ~/Documents/work/wo-closed-loop/backend
.venv/bin/python ../scripts/sync_dingtalk_users.py
```
（脚本逻辑：`uid = m.get("userId", m.get("staffId",""))`，找到 user 就 `user.dingtalk_id = uid`；新建的 role=executor，**不碰已存在用户的 role**。）

3. 核对两个关键人：
```bash
psql -U postgres -d wo_closed_loop -c "SELECT id,name,role,dingtalk_id FROM users WHERE name IN ('李沛东','刘冰') ORDER BY id;"
```
- 李沛东（admin）那行 `dingtalk_id` 应为 `20260629192000997-1218-257858D99`，且 `role` 仍是 `admin`。
- 刘冰那行 `dingtalk_id` 应为 `20250728131502929-101F-94567DE05`（如果 sync 拉得到他）。

**回报**：① dws 样例里 userId 的格式；② sync 脚本输出（新建/更新/跳过数 + 有钉钉ID统计）；③ 上面 psql 两条的查询结果。

**约束**：不改脚本、不改 backend 代码、**不改任何用户的 role**（尤其 admin）。任何一步报错原样回报，不要自行处理。
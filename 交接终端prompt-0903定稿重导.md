# 交接终端 v2：drive 定稿文件夹重导 + 日期补空（2026-09-03）

> v1 两个拍板已落地为代码（本会话改的，终端无需再改）：
> 1. **授权换列举办**：定稿文件夹是 alidocs 节点，`drive +list` 列举不到（RESOURCE_NOT_FOUND）。`_walk_folder` 已改走 `doc +list --folder <uuid>`；配置的数字 dentryId（230610076351）经 `drive +info --node` 自动换 uuid。`_norm_node` 兼容 alidocs/drive 两种节点结构；`_download` 按 `drive download` / `doc +download` × 两个 id 逐组合尝试，落盘为准。
> 2. **那 1 个 failed 是测试脆性，不是环境问题**：`test_dev_login_disabled_by_default` 已改成 monkeypatch 强制默认关（不读本机 .env）。**本机 `.env` 的 `DEV_LOGIN_ENABLED=true` 是用户拍板，保持不动**。预期 pytest 77 passed。

## 步骤（按序，每步贴输出）

1. `cd ~/Documents/work/wo-closed-loop/backend && .venv/bin/python -m pytest tests -q`
   预期 77 passed。红了把失败原文发回（注意本仓库有并行任务在改代码，先 `git status` 看一眼别把别人的未提交改动当成本轮问题）。
2. 备份库（同前两轮习惯）→ `../backup_wo_20260903_round3.sql`。
3. 重跑导入（backend 目录，.env 按 cwd 加载）：
   `.venv/bin/python -c "from app.services.drive_workorder_import import import_drive_workorder_versions as f; import json; print(json.dumps(f(), ensure_ascii=False, indent=1, default=str))"`
4. 验收口径（逐条核对）：
   - errors 无「定稿文件夹列举失败/为空」（有 = 走了关键词回退，列举没通，发回）；
   - imported>0：v1 探到的 7 个定稿表（中建投景县煜特、泰康师宗、协合回龙、金壁、东兰红水河、瓮安建中等）入库 source=plan；
   - backfilled>0：存量 plan 工单空的计划开始/截止被补；
   - 页面抽查这些项目计划开始/截止不再整列「—」。
5. **唯一允许的改码**：若 `doc +list` 实际 JSON 字段名不在 `_norm_node`/`_walk_folder` 兼容清单（nodes/items/files/list；fileId/nodeId/dentryId/id；nodeType/type；extension）里，可往键名元组里补键名——只补键名不改逻辑，改完重跑第 1 步。
6. 若下载不落盘（skipped_file 增多、errors 出现「下载失败」）：贴 `dws doc +download --help` 与 `dws drive download --help` 原文 + 一次真实尝试的 stdout/stderr 发回，**不要自己猜着改**。

## 不要做

- 不推云效、不 commit（等指令）；
- 除第 5 条键名外不改任何代码；
- 不动 aitable/数据池同步；不动 .env。

## 回传

pytest 尾行 + 第 3 步完整 JSON + 验收四条结论。

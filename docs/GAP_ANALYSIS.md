# 软工单管理平台 vs 行业标杆 — 差距分析与补强建议

> 2026-08-13 | 对标：Jira Service Management、ServiceNow、禅道、飞书项目

## 平台定位

本平台是**软工单闭环管理系统**，专注工单全生命周期管理（来源→派发→执行→验收→闭环），不涉及设备台账、巡检、两票、备件等 EAM 领域功能。

---

## 一、通用平台能力对比

| 功能模块 | Jira SM | ServiceNow | 禅道 | 飞书项目 | 我们 | 优先级 |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|
| 工单 CRUD + 状态流转 | ✅ | ✅ | ✅ | ✅ | ✅ | - |
| 审批流引擎 | ✅ | ✅ | ✅ | ✅ | ✅ | - |
| 多角色权限 | ✅ | ✅ | ✅ | ✅ | ✅ | - |
| SLA 管理 | ✅ | ✅ | ✅ | ✅ | ✅ | - |
| 通知/提醒 | ✅ | ✅ | ✅ | ✅ | ⚠️ | P1 |
| 知识库 | ✅ | ✅ | ✅ | ✅ | ✅ | - |
| 报表/看板 | ✅ | ✅ | ✅ | ✅ | ⚠️ | P1 |
| 日历视图 | ✅ | ✅ | ⚠️ | ✅ | ❌ | P2 |
| 看板视图 | ✅ | ✅ | ✅ | ✅ | ❌ | P2 |
| 批量操作 | ✅ | ✅ | ✅ | ✅ | ❌ | P2 |
| 工单模板 | ✅ | ✅ | ✅ | ✅ | ❌ | P2 |
| 自助门户 | ✅ | ✅ | ✅ | ❌ | ❌ | P3 |
| 移动端 | ✅ | ✅ | ✅ | ✅ | ❌ | P3 |
| 报表导出(PDF/Excel) | ✅ | ✅ | ✅ | ✅ | ⚠️ | P1 |
| 自动化规则 | ✅ | ✅ | ✅ | ✅ | ❌ | P2 |

---

## 二、P1 补强方案（显著提升专业度）

### 1. 报表导出（PDF/Excel）

**现状：** 工作台只有屏幕展示，无法导出给甲方。

**方案：**
```
后端新增：
  GET /api/dashboard/export?format=pdf|excel&project_id=X&month=2026-08

实现要点：
  1. Excel 导出：openpyxl 生成，含统计摘要 + 工单明细 + 图表（可选）
  2. PDF 导出：weasyprint 或 reportlab，含封面 + 统计 + 明细表
  3. 复用现有 dashboard 查询逻辑，增加日期范围筛选

前端新增：
  工作台增加"导出报表"按钮 → 下拉选择 PDF/Excel/月度/季度
```

**估时：** 后端 1d，前端 0.5d

---

### 2. 通知/提醒增强

**现状：** 只有 SLA 升级通知，缺少日常提醒。

**方案：**
```
Celery 定时任务（每天 8:00 执行）：
  1. 到期提醒：扫描 deadline 在未来 24h 内的工单 → 钉钉通知责任人
  2. 回填催促：扫描状态为 executing/verifying 且超过 3 天未回填的工单 → 钉钉催促
  3. 验收催促：扫描状态为 verifying 超过 24h 的工单 → 通知审批人

Celery 事件触发（建单时立即执行）：
  4. 新工单派发 → 立即通知责任人
  5. 审批驳回 → 通知创建人

新增通知类型：
  在 notification_policies 表新增：
  - deadline_remind（到期提醒）
  - backfill_urge（回填催促）
  - verify_urge（验收催促）
```

**估时：** 后端 1d（含定时任务 + 通知模板），前端 0.5d（通知配置页新增开关）

---

### 3. SOP 知识库扩展

**现状：** 已支持 SOP 编辑（2026-08-13 更新），基础字段（目的、流程、步骤、验收标准、升级规则、关联指引）已完备。

**待补强：**
```
WorkOrderTypeKB 扩展字段：
  - safety_measures: JSONB → ["断电确认", "挂接地线", "佩戴PPE"]
  - tools_required: JSONB → ["万用表", "力矩扳手"]
  - parts_common: JSONB → ["轴承", "密封圈"]
  - estimated_hours: float → 预估工时
```

**估时：** 后端 0.5d（新增字段 + 迁移），前端 0.5d（SOP 编辑弹窗新增字段）

---

## 三、P2 补强方案（锦上添花）

### 4. 看板视图

**功能描述：** 工单按状态列展示（待审批 → 待执行 → 执行中 → 待验收 → 已闭环），支持拖拽流转。

**方案：**
```
前端新增页面：
  /kanban → KanbanBoard.vue

技术选型：
  - 使用 vuedraggable 或原生 HTML5 drag-and-drop
  - 列：pending | approving | dispatched | executing | verifying | closed
  - 拖拽卡片到目标列 → 调用 transition API

后端无需改动：
  复用现有 GET /work-orders + POST /work-orders/{id}/transition
```

**估时：** 前端 1.5d

---

### 5. 批量操作

**功能描述：** 在工单列表页选中多行，批量派发、批量关闭、批量修改责任人。

**方案：**
```
后端新增：
  POST /api/work-orders/batch
  Body: { ids: [1,2,3], action: "dispatch"|"close"|"reassign", payload: {...} }

前端新增：
  工单列表增加 checkbox 列 + 顶部批量操作栏
  支持：批量派发、批量关闭、批量修改责任人
```

**估时：** 后端 0.5d，前端 0.5d

---

### 6. 工单模板

**功能描述：** 预定义常用工单模板，新建工单时可一键套用。

**方案：**
```
后端新增：
  WorkOrderTemplate 模型：
    id, name, category, title_template, reason_template, action_template,
    default_type_id, default_priority, default_source_code, is_active

  CRUD API：
    GET /api/work-order-templates
    POST /api/work-order-templates
    DELETE /api/work-order-templates/{id}

前端新增：
  新建工单页增加"从模板创建"按钮
  选择模板 → 自动填充标题/原因/行动/类型/优先级
  管理员可在规则配置页管理模板
```

**估时：** 后端 1d（模型 + 迁移 + API），前端 0.5d

---

## 四、补强路线图

```
当前 ──────→ P1 (1.5周) ──────→ P2 (按需)

P1: 报表导出 + 通知增强 + SOP 扩展字段
P2: 看板视图 + 批量操作 + 工单模板
P3: 移动端 + 自助门户
```

### 工作量汇总

| 优先级 | 模块 | 后端 | 前端 | 合计 |
|--------|------|------|------|------|
| P1 | 报表导出 | 1d | 0.5d | 1.5d |
| P1 | 通知增强 | 1d | 0.5d | 1.5d |
| P1 | SOP 扩展 | 0.5d | 0.5d | 1d |
| P2 | 看板视图 | 0d | 1.5d | 1.5d |
| P2 | 批量操作 | 0.5d | 0.5d | 1d |
| P2 | 工单模板 | 1d | 0.5d | 1.5d |
| **合计** | | **4d** | **4d** | **8d** |

---

## 五、2026-08-13 更新记录

### 本次已完成
- [x] 左侧菜单重组：项目管理、用户管理合并到"基础数据"组
- [x] 面包屑导航：支持点击跳转，动态显示层级
- [x] SOP 知识库编辑：SOPBrowser 页面增加"编辑"按钮 + 完整编辑弹窗
- [x] 分页控件升级：项目和用户管理使用 TDesign 分页（含 pageSizeOptions）
- [x] 自动种子数据：首次启动自动灌入示例数据
- [x] 权限配置同步更新
# Phase 3.5 工单系统整合方案

> 2026-08-12 | 来源：听记 "08-12 工单系统整合与异常管理"

---

## 听记核心结论

**只做一件事：工单从哪里来，怎么做出来。**

| 优先级 | 工单来源 | 数据路径 |
|--------|---------|---------|
| P0 | 计划类（EM续签/新增、预算、OA推送、EAM导出） | 钉盘Excel → 数据池-计划 → 自动生成工单 |
| P0 | 异常指标（发电量/限电损失/设备可靠性/双细则） | 资产监视 → 多维表 → 数据池-异常 → 自动生成工单 |
| 暂缓 | 会议待办、客诉、群消息、邮件 | 非结构化，暂不接入 |

**三阶段模式：** 原始异常指标 → 原因/措施回填 → 措施执行工单

---

## 系统改动总览

```
┌─────────────────────────────────────────────────────────┐
│                    数据接入层                              │
│  钉盘Excel上传  │  多维表API  │  CSV导入  │  手动录入       │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│                    数据池 (新增)                           │
│  data_pool_items: 统一暂存表，type=plan|anomaly           │
│  字段: 标题/场站/责任人/截止日/指标值/阈值/来源系统/原始数据  │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   工单生成引擎 (新增)                       │
│  数据池 → 匹配项目/人员(映射表) → 应用优先级规则 → 创建工单   │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   工单 (WorkOrder 扩展)                    │
│  新增字段: backfill_status, backfill_reason,               │
│           backfill_action, parent_pool_id, triggered_wo_id │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   展示层 (扩展)                            │
│  人员专属看板 │ 工单日历 │ 回填状态追踪                      │
└─────────────────────────────────────────────────────────┘
```

---

## 一、数据池（新增）

### 1.1 模型

```python
class DataPoolItem(Base, TimestampMixin):
    """统一数据池：计划类 + 异常指标类"""
    __tablename__ = "data_pool_items"

    id: Mapped[int] = primary key
    pool_type: Mapped[str]       # "plan" | "anomaly"
    source_system: Mapped[str]   # "excel" | "aitable" | "asset_monitor" | "manual"
    source_ref: Mapped[str]      # 来源文件名/表名/引用

    # 核心字段
    title: Mapped[str]           # 事项标题
    project_name: Mapped[str]    # 场站名（映射前）
    person_name: Mapped[str]     # 责任人（映射前）
    deadline: Mapped[date | None]
    description: Mapped[str | None]  # 描述/触发原因

    # 异常指标专用
    metric_type: Mapped[str | None]   # power_gen/curtailment/reliability/dual_rule
    metric_value: Mapped[float | None]
    threshold: Mapped[float | None]
    deviation_pct: Mapped[float | None]

    # 处理状态
    status: Mapped[str]          # "pending" | "generated" | "skipped"
    work_order_id: Mapped[int | None]  # 生成后关联工单
    skip_reason: Mapped[str | None]    # 跳过原因

    # 原始数据（JSONB 保留完整来源行）
    raw_data: Mapped[dict | None]
```

### 1.2 导入 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/import/pool/upload` | POST | 上传 Excel/CSV，解析后写入 data_pool_items |
| `/import/pool/aitable` | POST | 从钉钉多维表拉取数据（传 table_id） |
| `/import/pool/list` | GET | 数据池列表，支持 pool_type/status 筛选 |
| `/import/pool/{id}` | GET | 单条详情 |
| `/import/pool/{id}` | PATCH | 编辑/修正（映射前人工调整） |
| `/import/pool/{id}` | DELETE | 删除 |

### 1.3 导入逻辑

```
Excel/CSV 上传
  ├─ 自动检测列名（中文/英文）
  ├─ 行级校验：标题必填 + 场站名匹配 Project 表
  ├─ 写入 data_pool_items（status=pending）
  └─ 返回：total / imported / skipped / errors
```

---

## 二、工单生成引擎（新增）

### 2.1 服务

```python
# services/pool_service.py

def generate_from_pool(db, pool_ids: list[int]) -> dict:
    """
    从数据池批量生成工单：
    1. 查询 pool items（status=pending）
    2. 匹配项目名 → Project.code（模糊匹配）
    3. 匹配责任人 → User.name（精确匹配）
    4. 应用优先级规则 → priority
    5. 创建 WorkOrder + StatusLog
    6. 更新 pool item status=generated, work_order_id=wo.id
    """
```

### 2.2 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/import/pool/generate` | POST | 批量生成：传入 pool_ids 列表，返回生成结果 |
| `/import/pool/generate-all` | POST | 一键生成所有 pending 项 |

---

## 三、回填机制（扩展 WorkOrder）

### 3.1 模型扩展

在 `WorkOrder` 表新增字段：

```python
# 回填
backfill_status: Mapped[str | None]   # None | "pending" | "filled"
backfill_reason: Mapped[str | None]   # 责任人填写的根因分析
backfill_action: Mapped[str | None]   # 责任人填写的应对措施
backfilled_at: Mapped[datetime | None]

# 溯源
parent_pool_id: Mapped[int | None]    # 来源数据池记录
triggered_wo_id: Mapped[int | None]   # 回填后触发的新工单
```

### 3.2 回填流程

```
工单已派发（dispatched/executing）
  │
  ▼
责任人填写原因 + 措施（backfill）
  │
  ├─ backfill_status = "filled"
  ├─ 回传至原数据池记录（如有 parent_pool_id）
  │
  ▼
系统判断：措施是否触发新工单？
  │
  ├─ 是 → 创建新工单（triggered_wo_id），关联原工单
  └─ 否 → 闭环
```

### 3.3 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/work-orders/{id}/backfill` | POST | 提交回填（reason + action），可选"触发新工单" |
| `/work-orders/{id}/backfill` | GET | 查看回填记录 |

---

## 四、人员看板 + 工单日历（前端扩展）

### 4.1 人员专属看板

新增页面 `/dashboard/person`：

- 按责任人筛选：我的工单 / 指定人员
- 统计卡片：待处理 / 执行中 / 待回填 / 已逾期 / 已闭环
- 回填状态列：pending（待回填）/ filled（已回填）
- 支持按项目、来源、优先级筛选

### 4.2 工单日历

在 Dashboard 增加日历视图：

- 按 deadline 展示工单
- 颜色区分：overdue(红) / today(橙) / upcoming(蓝) / closed(绿)
- 点击弹出工单摘要

### 4.3 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/dashboard/person/{user_id}` | GET | 人员专属统计 |
| `/dashboard/calendar` | GET | 日历数据（月份范围参数） |

---

## 五、改动文件清单

### 后端（3 个新增 + 4 个修改）

| 文件 | 改动 | 说明 |
|------|------|------|
| `models/pool.py` | **新增** | DataPoolItem 模型 |
| `schemas/pool.py` | **新增** | 数据池 Schema |
| `services/pool_service.py` | **新增** | 导入 + 生成 + 回填引擎 |
| `api/imports.py` | 修改 | 新增 pool 导入/生成接口 |
| `api/workorders.py` | 修改 | 新增 backfill 接口 |
| `api/dashboard.py` | 修改 | 新增人员看板 + 日历接口 |
| `models/workorder.py` | 修改 | 新增回填字段 |
| `seed.py` | 修改 | 种子数据适配 |

### 前端（1 个新增 + 4 个修改）

| 文件 | 改动 | 说明 |
|------|------|------|
| `views/DataPool.vue` | **新增** | 数据池管理页（上传/查看/生成） |
| `views/Dashboard.vue` | 修改 | 增加人员看板 + 日历视图 |
| `views/WorkOrderDetail.vue` | 修改 | 增加回填表单 |
| `views/WorkOrderCreate.vue` | 修改 | 增加"从数据池生成"入口 |
| `api/imports.ts` | 修改 | 新增 pool API |

---

## 六、实施顺序

```
Step 1: 数据池模型 + 导入 (1d)
  └─ models/pool.py + schemas/pool.py + api/imports.py 扩展

Step 2: 工单生成引擎 (1d)
  └─ services/pool_service.py + /import/pool/generate

Step 3: 回填机制 (0.5d)
  └─ WorkOrder 扩展 + /work-orders/{id}/backfill

Step 4: 人员看板 + 日历 (1d)
  └─ Dashboard 扩展 + 前端 DataPool.vue

Step 5: 端到端联调 (0.5d)
  └─ Excel导入 → 数据池 → 生成工单 → 回填 → 触发新工单

总计: 4d
```

---

## 七、我的断点

1. **数据池的"计划类"字段怎么定？** 听记里说从预算系统/OA/EAM 来，但这些系统的 Excel 格式我不清楚。你提供一份示例 Excel（计划类 + 异常类各一个），还是我按通用字段先做，你后续调？

2. **"Skill规则 → 多维表"这一步是谁负责？** 听记里说王宁维护多维表，那么这个多维表是钉钉 AI 表格吗？我们需要从它直接 API 拉取，还是王宁导出 Excel 给我们？

3. **回填后"回传至原作业表"** — 这个"原作业表"是哪个？数据池的原始记录？还是多维表？还是 EAM 系统？
# 异常指标→判断Agent→措施工单 · 流程方案设计

> 日期：2026-08-17 | 状态：方案设计 | 关联：`docs/LLM_JUDGMENT_PLAN.md`、`docs/BUSINESS_CONFIRMATION_AGENT.md`

## 一、当前流程（现状）

```
异常指标 → 数据池(pool_type=anomaly) → 生成工单A(问原因+措施)
                                              │
                                              ▼
                                     PMO 回填(原因+措施)
                                              │
                                    trigger_new_wo=true
                                              │
                                              ▼
                                        工单B(措施执行)
```

**问题：**
- PMO 回填的质量完全依赖个人经验，没有校验环节
- 原因分析可能不准确，措施可能不匹配或不可执行
- 措施工单的优先级/责任人/截止时间靠 PMO 手动拍，缺乏标准
- 没有"这个异常是否真的需要新建措施工单"的判断环节

## 二、目标流程（引入判断Agent后）

```
异常指标 → 数据池 → 工单A(问原因+措施)
                         │
                         ▼
                   PMO 回填(原因+措施)
                         │
                         ▼
              ┌──────────────────────┐
              │   判断 Agent（技术提供）  │
              │  输入: 工单A的完整上下文     │
              │  输出: 判定结果+建议       │
              └──────────────────────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
          通过(建议)   通过(不改)   驳回(退回PMO)
              │          │          │
              ▼          ▼          ▼
         工单B(按建议  工单B(原样  工单A状态→
         修改后创建)   创建)     backfill_rejected
```

### 判断Agent的职责

| 判定维度 | 说明 |
|---------|------|
| 原因有效性 | 根因分析是否合理？是否归因到了可操作的层面？ |
| 措施匹配度 | 措施是否针对根因？是否具体可执行？ |
| 优先级合理性 | 措施工单的优先级是否恰当？ |
| 是否需要新工单 | 有些异常不需要建新工单（如数据波动/已恢复） |
| 字段补全建议 | 责任人/截止时间/验收标准是否需要调整 |

## 三、详细流程设计

### 3.1 工单A（问原因+措施工单）的改动

当前 `source_code=alert` 的 anomaly 工单生成后是 `status=pending`，需要改为一个新的子状态或增加标记。

**建议：** 不改变现有状态机，在工单A上增加 `judgment_status` 字段：

```python
# WorkOrder 模型新增
judgment_status: Mapped[str | None]  # None=不需要判断 | pending_judge | judging | approved | rejected
judgment_result: Mapped[dict | None] = mapped_column(JSONB)  # Agent 返回的完整判定结果
```

### 3.2 流程节点

```
Step 1: 异常指标进入数据池
  - 来源: AI表格 / 监视告警 / 手动导入
  - pool_type = "anomaly"
  - 数据池展示异常指标: 指标类型、指标值、阈值、偏离%

Step 2: 数据池 → 生成工单A
  - source_code = "alert"
  - title = "【异常分析】{场站}-{指标类型}偏离{偏离%}%"
  - reason = 自动填入异常指标详情
  - status = "pending"（待PMO派发和回填）
  - judgment_status = None（此时不需要判断，A只是问原因+措施）

Step 3: PMO 回填工单A
  - 填写 backfill_reason（根因分析）
  - 填写 backfill_action（应对措施）
  - 可选填写: new_wo_title, new_wo_deadline, new_wo_person_name
  - 提交回填时: 如果 source_code == "alert" → 触发判断Agent

Step 4: 判断Agent 审核（新增核心环节）
  - 后端调用判断Agent API
  - 传入完整上下文: 原始异常指标 + PMO回填内容 + 场站信息
  - Agent 返回判定结果 JSON

Step 5: 根据判定结果分支
  ┌─ approved_suggested: Agent 通过了，但给了调整建议
  │   → 按建议修改后创建工单B
  │   → 工单A status → "closed"（原因已分析完毕）
  │
  ├─ approved_as_is: Agent 完全通过
  │   → 原样创建工单B
  │   → 工单A status → "closed"
  │
  ├─ rejected: Agent 驳回
  │   → 不创建工单B
  │   → 工单A judgment_status → "rejected"
  │   → 通知PMO: "原因/措施被驳回，原因：{Agent给出的驳回理由}，请重新回填"
  │   → 工单A 回到可回填状态
  │
  └─ no_action_needed: Agent 判断不需要措施工单
      → 不创建工单B
      → 工单A status → "closed"
      → 记录判断结论: "异常已恢复/波动在正常范围/已有其他工单覆盖"

Step 6: 创建工单B（措施执行工单）
  - 基于Agent建议或PMO原始输入创建
  - source_code = "alert"（或新增 "alert_measure"）
  - parent_wo_id = 工单A.id
  - 走正常工单流转: → 审批 → 派发 → 执行 → 验收 → 闭环
```

### 3.3 判断Agent 接口约定

技术团队需要提供一个 HTTP API，系统后端调用它。建议接口规范：

```yaml
POST /judge
Content-Type: application/json

Request:
  work_order_id: string        # 工单A编号
  station_name: string         # 场站名称
  anomaly:
    metric_type: string        # 指标类型: power_gen|curtailment|reliability|dual_rule
    metric_value: float        # 当前值
    threshold: float           # 阈值
    deviation_pct: float       # 偏离百分比
    period: string             # 统计周期: 2026-08
  backfill:
    reason: string             # PMO填写的根因分析
    action: string             # PMO填写的应对措施
  proposed_work_order:         # PMO建议的新工单参数（可选）
    title: string | null
    deadline: string | null    # YYYY-MM-DD
    person_name: string | null
    priority: string | null    # P0|P1|P2

Response:
  verdict: "approved_suggested" | "approved_as_is" | "rejected" | "no_action_needed"
  confidence: 0.0-1.0          # 置信度
  reasoning: string            # 判定理由（可读文本）
  suggestions:                 # verdict=approved_suggested 时必填
    title: string | null
    deadline: string | null
    person_name: string | null
    priority: string | null
    action_adjustment: string | null   # 措施调整建议
  reject_reason: string | null # verdict=rejected 时必填
  risk_level: "high" | "medium" | "low"  # 不处理的风险等级
```

### 3.4 后端实现要点

```python
# 新增文件: backend/app/services/judgment_agent.py

import httpx
from app.core.config import settings

JUDGMENT_AGENT_URL = settings.JUDGMENT_AGENT_URL  # 环境变量注入
JUDGMENT_TIMEOUT = 30  # 秒

async def call_judgment_agent(wo: WorkOrder, pool_item: DataPoolItem) -> dict:
    """调用判断Agent，返回判定结果"""
    
    payload = {
        "work_order_id": wo.code,
        "station_name": _get_project_name(wo),
        "anomaly": {
            "metric_type": pool_item.metric_type,
            "metric_value": pool_item.metric_value,
            "threshold": pool_item.threshold,
            "deviation_pct": pool_item.deviation_pct,
            "period": str(wo.created_date)[:7] if wo.created_date else None,
        },
        "backfill": {
            "reason": wo.backfill_reason,
            "action": wo.backfill_action,
        },
        "proposed_work_order": {
            "title": wo.triggered_wo_title,  # PMO建议的新工单标题
            "deadline": str(wo.triggered_wo_deadline) if wo.triggered_wo_deadline else None,
            "person_name": wo.triggered_wo_person_name,
            "priority": wo.priority,
        },
    }
    
    async with httpx.AsyncClient(timeout=JUDGMENT_TIMEOUT) as client:
        resp = await client.post(
            f"{JUDGMENT_AGENT_URL}/judge",
            json=payload,
            headers={"Authorization": f"Bearer {settings.JUDGMENT_AGENT_TOKEN}"}
        )
        resp.raise_for_status()
        return resp.json()
```

### 3.5 回填接口改造

当前 `backfill_work_order` 在 `pool_service.py` 中，当 `trigger_new_wo=True` 时直接创建工单B。需要改为：

```python
def backfill_work_order(db, wo_id, reason, action, trigger_new_wo, ...):
    # 1. 写入回填数据（不变）
    wo.backfill_reason = reason
    wo.backfill_action = action
    ...
    
    # 2. 如果来源是 alert 且需要触发新工单 → 先调判断Agent
    if trigger_new_wo and wo.source_code == "alert":
        wo.judgment_status = "judging"
        db.flush()
        
        # 同步调用判断Agent（或异步→见3.6）
        judgment = _call_judgment_sync(wo, pool_item)
        wo.judgment_result = judgment
        wo.judgment_status = judgment["verdict"]
        
        if judgment["verdict"] == "rejected":
            # 驳回，不创建工单B
            db.commit()
            _notify_pmo_rejected(wo, judgment["reject_reason"])
            return {"verdict": "rejected", "reason": judgment["reject_reason"]}
        
        if judgment["verdict"] == "no_action_needed":
            # 不需要措施工单
            wo.status = "closed"
            db.commit()
            return {"verdict": "no_action_needed", "reason": judgment["reasoning"]}
        
        # approved_suggested 或 approved_as_is → 创建工单B
        if judgment["verdict"] == "approved_suggested":
            # 用Agent建议覆盖PMO的输入
            new_wo_title = judgment["suggestions"]["title"] or new_wo_title
            new_wo_deadline = judgment["suggestions"]["deadline"] or new_wo_deadline
            ...
        
        # 创建工单B（原逻辑）
        new_wo = WorkOrder(...)
        wo.triggered_wo_id = new_wo.id
    
    db.commit()
    return {...}
```

### 3.6 同步 vs 异步调用

| 方式 | 优点 | 缺点 | 建议场景 |
|------|------|------|---------|
| **同步** | 流程简单，PMO提交后即时看到结果 | Agent慢(>5s)会阻塞用户 | Agent响应<3s |
| **异步** | 不阻塞用户，Agent可做复杂推理 | 需要轮询/回调通知结果 | Agent响应3-30s |

**建议：** 先用同步，加上超时保护（最多等10s）。如果技术团队反馈Agent需要更长时间，再改为异步模式：

```
同步模式: PMO提交 → 等待Agent(最长10s) → 展示结果
异步模式: PMO提交 → 立即返回"已提交判断" → Agent完成后通知PMO → PMO确认
```

## 四、异常处理与降级策略

| 场景 | 处理方式 |
|------|---------|
| Agent 服务不可达（连接超时） | 降级为"跳过判断"，用PMO原输入直接创建工单B，记录告警日志 |
| Agent 返回超时（>10s） | 降级为"跳过判断"，同上 |
| Agent 返回格式错误 | 降级为"跳过判断"，记录错误日志 |
| Agent 返回 5xx | 重试1次，仍失败则降级 |
| 置信度 < 0.6 | 标记为"低置信度"，仍创建工单B但前端标注"AI建议仅供参考" |

**降级日志表：**
```python
class JudgmentDegradationLog(Base):
    work_order_id: int
    reason: str          # timeout|unreachable|parse_error|server_error
    degraded_at: datetime
    original_error: str
```

## 五、部署方案

### 5.1 判断Agent 的部署形态

技术团队做的是一个独立的 HTTP 服务。部署时需要考虑它在整个架构中的位置：

```
                    ┌─────────────────────────┐
                    │     ALB (HTTPS 终结)      │
                    └──────────┬──────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        ┌──────────┐    ┌──────────┐    ┌──────────────┐
        │ Frontend │    │ Backend  │    │ Judgment     │
        │ (Nginx)  │    │ (FastAPI)│    │ Agent (技术)  │
        └──────────┘    └────┬─────┘    └──────────────┘
                             │
                             │ 内网调用 (K8s Service)
                             │ http://judgment-agent:8080/judge
                             ▼
                    ┌──────────────┐
                    │ Judgment     │
                    │ Agent (技术)  │
                    └──────────────┘
```

### 5.2 部署配置

**K8s 部署资源：**

```yaml
# docker/k8s-judgment-agent.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: wo-judgment-agent
spec:
  replicas: 2
  selector:
    matchLabels:
      app: wo-judgment-agent
  template:
    metadata:
      labels:
        app: wo-judgment-agent
    spec:
      containers:
        - name: agent
          image: registry.cn-hangzhou.aliyuncs.com/<命名空间>/wo-judgment-agent:0.1.0
          ports:
            - containerPort: 8080
          env:
            - name: LLM_API_KEY
              valueFrom:
                secretKeyRef:
                  name: wo-secrets
                  key: DASHSCOPE_API_KEY
            - name: LLM_MODEL
              value: "qwen-max"
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2"
              memory: "2Gi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: wo-judgment-agent
spec:
  selector:
    app: wo-judgment-agent
  ports:
    - port: 8080
      targetPort: 8080
```

**后端环境变量新增：**

```bash
kubectl create secret generic wo-secrets \
  ... (现有字段不变) \
  --from-literal=JUDGMENT_AGENT_URL='http://wo-judgment-agent:8080' \
  --from-literal=JUDGMENT_AGENT_TOKEN='<Agent内部认证Token>' \
  --from-literal=JUDGMENT_TIMEOUT='10' \
  --dry-run=client -o yaml | kubectl apply -f -
```

**后端 config 新增：**

```python
# backend/app/core/config.py
class Settings(BaseSettings):
    ...
    JUDGMENT_AGENT_URL: str = "http://localhost:8080"
    JUDGMENT_AGENT_TOKEN: str = ""
    JUDGMENT_TIMEOUT: int = 10
    JUDGMENT_ENABLED: bool = True  # 总开关，可随时关闭降级
```

### 5.3 技术团队需要交付的接口规格

技术团队交付的 Agent 服务需要满足以下约定：

1. **HTTP 接口**：`POST /judge`，入参/出参见 3.3 节
2. **健康检查**：`GET /health` 返回 `{"status": "ok"}`
3. **容器化**：提供 Dockerfile，基础镜像建议 `python:3.11-slim` 或 `registry.cn-hangzhou.aliyuncs.com/...`
4. **配置**：通过环境变量注入 LLM API Key 和模型名
5. **超时**：单次判定在 10s 内完成（含 LLM 调用）
6. **认证**：支持 Bearer Token 认证（通过 `JUDGMENT_AGENT_TOKEN` 传入）
7. **日志**：标准输出 JSON 格式日志，包含 `request_id`, `verdict`, `duration_ms`

### 5.4 部署顺序

```
1. 技术团队交付 Agent 镜像 + 推送 ACR
2. 部后端代码（含 judgment_agent service + 回填改造）
3. kubectl apply -f k8s-judgment-agent.yaml  # 部署 Agent
4. kubectl apply -f k8s.yaml                   # 更新后端
5. kubectl exec deploy/wo-backend -- alembic upgrade head  # 新增字段迁移
6. 验证: curl http://wo-judgment-agent:8080/health
7. 验证: 走通一条完整的"异常指标→回填→判断→措施工单"链路
```

## 六、前端交互设计

### 6.1 回填表单改造

PMO 在工单A详情页点击"回填"时，如果工单来源是 `alert`：

```
┌──────────────────────────────────────────────┐
│  回填 - 工单 RW-2026-0012                     │
│                                              │
│  异常指标：功率发电量偏离 15%（阈值10%）        │
│                                              │
│  根因分析：                                   │
│  ┌──────────────────────────────────────┐    │
│  │ #2逆变器IGBT模块温度过高，导致降容运行   │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  应对措施：                                   │
│  ┌──────────────────────────────────────┐    │
│  │ 安排检修人员清理逆变器散热风道，检查冷却  │    │
│  │ 风扇运行状态                           │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  ☑ 需要创建措施工单                           │
│    工单标题: [清理#2逆变器散热系统，恢复满功率] │
│    责任人:   [高志强          ▼]              │
│    截止时间: [2026-08-20    📅]               │
│                                              │
│  ┌─ AI 判断中... ────────────────────────┐    │
│  │  🤖 正在分析原因和措施的合理性...       │    │
│  └──────────────────────────────────────┘    │
│                                              │
│                    [取消]  [提交审核]          │
└──────────────────────────────────────────────┘
```

### 6.2 判断结果展示

Agent 返回后，在回填结果区域展示：

```
┌─ AI 判断结果 ────────────────────────────────┐
│  ✅ 判定通过（有建议）           置信度: 85%    │
│                                              │
│  📝 判断理由：                                │
│  根因分析定位到IGBT模块温度过高，方向正确。     │
│  建议补充：检查散热风道是否堵塞是第一步，但     │
│  还应增加IGBT本身的老化检测。                  │
│                                              │
│  💡 调整建议：                                │
│  • 标题已采用                                 │
│  • 措施补充：增加"必要时更换IGBT模块"          │
│  • 优先级建议：P1（原P2偏低，发电量偏离影响    │
│    合同指标）                                 │
│                                              │
│  [按建议创建]  [原样创建]  [取消]              │
└──────────────────────────────────────────────┘
```

驳回场景：

```
┌─ AI 判断结果 ────────────────────────────────┐
│  ❌ 判定驳回                     置信度: 92%    │
│                                              │
│  📝 驳回理由：                                │
│  根因分析"逆变器温度过高"未追溯到根本原因。    │
│  请补充：是环境温度过高？还是散热系统故障？     │
│  还是IGBT老化？需进一步定位后再提交。          │
│                                              │
│  [重新回填]                                   │
└──────────────────────────────────────────────┘
```

## 七、数据模型变更汇总

### WorkOrder 表新增字段

```python
# 判断Agent相关
judgment_status: Mapped[str | None]    # None|pending_judge|judging|approved|rejected
judgment_result: Mapped[dict | None]   # JSONB, Agent返回的完整结果
judgment_requested_at: Mapped[datetime | None]
judgment_completed_at: Mapped[datetime | None]

# 回填增强（当前 BackfillRequest 只传了简单字段，需要扩展）
triggered_wo_title: Mapped[str | None]     # PMO建议的新工单标题
triggered_wo_deadline: Mapped[date | None] # PMO建议的截止时间
triggered_wo_person_name: Mapped[str | None] # PMO建议的责任人
```

### 新增降级日志表

```python
class JudgmentDegradationLog(Base):
    __tablename__ = "judgment_degradation_log"
    id: int (PK)
    work_order_id: int (FK)
    reason: str          # timeout|unreachable|parse_error|server_error
    original_error: str
    created_at: datetime
```

## 八、配置管理

在 ConfigPage 中新增判断Agent的配置项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `judgment.enabled` | true | 总开关 |
| `judgment.agent_url` | http://wo-judgment-agent:8080 | Agent 地址 |
| `judgment.timeout` | 10 | 超时秒数 |
| `judgment.auto_approve_confidence` | 0.8 | 置信度高于此值自动通过 |
| `judgment.require_manual_review` | true | 驳回/低置信度是否需人工确认 |

## 九、实施步骤

| 阶段 | 内容 | 估时 |
|------|------|------|
| **Phase 1: 接口对齐** | 与技术团队确认 3.3 节的接口规范，联调 | 0.5d |
| **Phase 2: 后端改造** | judgment_agent service + 回填改造 + 数据迁移 | 1.5d |
| **Phase 3: 前端改造** | 回填表单 + 判断结果展示 + 驳回重新回填 | 1d |
| **Phase 4: 部署** | Agent 容器化 + K8s 部署 + 环境变量 | 0.5d |
| **Phase 5: 测试** | 正常/驳回/降级/超时 四种场景测试 | 0.5d |
| **合计** | | **4d** |

## 十、待确认事项

1. 🔴 **判断Agent 由哪个技术团队做？** 接口规范（3.3节）是否认可？需要他们确认能交付的字段和响应时间。
2. 🔴 **Agent 调用是同步还是异步？** 建议先用同步+超时降级，如果 Agent 响应 >5s 再改异步。
3. 🟠 **驳回后 PMO 可以重新回填几次？** 建议最多 3 次，超过后升级到审批人手动处理。
4. 🟠 **Agent 的建议是否强制执行？** 建议 PMO 可以选择"按建议"或"原样"，但驳回必须重新回填。
5. 🟡 **是否所有 anomaly 工单都走判断？** 还是只有特定指标类型（如 power_gen 偏离 >10%）才触发？
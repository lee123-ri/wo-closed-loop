# 工单识别改用 LLM 判定 · 方案

> 状态：**方案待实施**（当前 Excel 建单已满足需求，本方案后续迭代）
> 关联：`~/.claude/agents/年度运营计划编制.md`、`skills/annual-operations-plan/references/workorder-format-rules.md`

## 背景与差距

当前工单识别用**正则评分**（`parsing_rules` 表 + `priority_rules` 表），局限明显：
- 正则只能匹配关键词，无法理解语义（"变桨异响" 和 "变桨轴承磨损" 正则判为同档，但严重度可能不同）
- 上下文丢失（同一句话里"安全培训"是 P1 关键词，但实际是"已完成安全培训"=例行项 P3）
- 新增业务场景必须手写正则，不可扩展

年度运营计划编制 agent 已用 LLM 做工单识别与分级（编制期人工+专家评审，但识别逻辑在 prompt 里）。两套应统一为 LLM 判定。

## 目标

1. **判定逻辑改 LLM**：听记/文本 → LLM 提取工单 + 自动定级，废弃正则评分主路径
2. **对齐运营计划 agent 的分级**：P0/P1/P2（P0红/P1橙/P2蓝），替换当前 P1/P2/P3
3. **对齐编号**：WO-XXX（WO-000=进场普查，WO-001起正式），替换 RW-2026-XXXX
4. **对齐字段**：补运营计划 11 列里缺失的「谁的停机最长/根因/对目标价值/前置条件/交付物验收标准」
5. **正则降级为 fallback**：无 LLM key 或断网时仍可用

## 对齐映射表（运营计划 agent → 本系统）

| 维度 | 运营计划 agent | 本系统当前 | 改成 |
|---|---|---|---|
| 优先级 | P0/P1/P2（红/橙/蓝） | P1/P2/P3 | **P0/P1/P2** |
| 编号 | WO-XXX（WO-000普查, WO-001起正式） | RW-2026-XXXX | **WO-XXXX**（保留 WO-000 普查语义） |
| 类型 | 项目工单🔴/设备检修🔵/定期运营🟢/双细则🟣 | 纠偏/客户沟通/隐患整改/非标/其他 | **四色分类**（作为 type 主分类，原六类降为子标签） |
| 来源 | 目标→拆解→工单 | 年度计划/告警/判定会/手动 | 增加「运营计划」来源 code=`ops_plan` |
| 判定 | 编制期 LLM+专家 | 正则评分 | **LLM 判定**（正则 fallback） |

## LLM 判定设计

### 1. 统一 system prompt（对齐运营计划 agent）

```
[STAGE:workorder-identify] 你是新能源电站运维工单识别助手。
从输入内容（听记/AI表格/运营计划拆解）识别需要闭环跟进的事项，判定为工单。

判定规则（对齐年度运营计划编制 agent）：
- P0 红：进场普查、安全红线、人身/设备事故、合同扣款、全站停运
- P1 橙：合同指标偏差（电量/故障时长/双细则考核）、监视告警触发、判定会决议
- P2 蓝：例行检修、定期运营、月度汇报、文档盘点

工单类型（四色）：
- 项目工单🔴：针对合同指标偏差的纠偏/整改
- 设备检修🔵：按周期的定检/预试/校核
- 定期运营🟢：月度/季度例行汇报、台账、培训
- 双细则🟣：AGC/AVC/功率预测/涉网试验考核项

输出 JSON 数组，每条含：
title, type(项目工单|设备检修|定期运营|双细则), priority(P0|P1|P2),
person, project, deadline(YYYY-MM-DD), root_cause(谁的停机最长/根因),
action, value(对目标价值), prerequisite(前置条件), acceptance(验收标准)
```

### 2. 字段补全

`work_orders` 表新增列（迁移）：
- `root_cause` Text —— 谁的停机最长/根因
- `value` Text —— 对目标的价值
- `prerequisite` Text —— 前置条件
- `acceptance` Text —— 交付物/验收标准

工单详情页展示这些字段。

### 3. 优先级与编号联动

- `priority` 枚举改 `P0|P1|P2`，影响：`sla_definitions`、`approval_flows`、`notification_policies`、前端 `priorityMap`
- 工单编号生成改 `WO-XXXX`（WO-000 保留给进场普查，WO-0001 起）
- SLA 重映射：P0=1天、P1=3天、P2=7天

### 4. 正则降级

保留 `parsing_rules` 表，仅在 LLM 不可用时（无 key/超时）走正则评分，作为兜底。日志记录走了哪条路径。

## 实施步骤（后续）

1. 迁移 0003：work_orders 加 4 字段；priority 枚举数据迁移 P1→P0?P2→P1?P3→P2（按映射）；sla/approval/notification 三表的 priority 列同步改
2. `llm_service.py`：换用上面的 system prompt；`parse_minutes` 主走 LLM
3. `priority_service.py`：`match_priority` 改调 LLM（输入文本→P0/P1/P2），正则 fallback
4. `workorders.py` `_next_code`：改 WO-XXXX 格式
5. 前端 `wo-display.ts`：priorityMap 改 P0/P1/P2；工单详情页补 4 字段展示
6. seed 数据：重灌 P0/P1/P2 + WO 编号 + 四色类型
7. 测试更新

## 现状结论

- 当前正则判定能用但局限，Excel 建单已满足近期需求
- LLM 判定方案已就绪，待接入百炼 key 后实施
- 优先级命名 P0/P1/P2 与运营计划 agent 对齐是必须项（不论 LLM 是否上线）

/** 工单显示映射：状态/优先级/来源/升级 —— 全站统一 */

import { useConfigStore } from "@/stores/config";

export const statusMap: Record<string, { label: string; tag: string }> = {
  pending: { label: "待派发", tag: "tag-gray" },
  scheduled: { label: "已排期", tag: "tag-blue" },
  approving: { label: "审批中", tag: "tag-blue" },
  dispatched: { label: "已派发", tag: "tag-amber" },
  executing: { label: "执行中", tag: "tag-blue" },
  verifying: { label: "待验收", tag: "tag-amber" },
  closed: { label: "已闭环", tag: "tag-green" },
  overdue: { label: "已逾期", tag: "tag-red" },
  rejected: { label: "已驳回", tag: "tag-gray" },
  judging: { label: "已回填", tag: "tag-amber" },
  // alert 五阶段（细阶段，用于主单流程展示）
  confirming: { label: "分析确认", tag: "tag-amber" },
  dispatching: { label: "派发工单", tag: "tag-amber" },
  tracking: { label: "已派工单", tag: "tag-blue" },
  reexamining: { label: "指标复核", tag: "tag-amber" },
  recovered: { label: "已恢复", tag: "tag-green" },
};

export const statusLabel = (s: string) => useConfigStore().statusName(s, statusMap[s]?.label ?? s);
export const statusTag = (s: string) => statusMap[s]?.tag ?? "tag-gray";

/** TDesign 主题映射（给 t-tag theme 用） */
export const statusTheme = (s: string): string => {
  const m: Record<string, string> = {
    pending: "default", scheduled: "primary", approving: "primary", dispatched: "warning",
    executing: "primary", verifying: "warning", closed: "success",
    overdue: "danger", rejected: "default",
  };
  return m[s] || "default";
};

export const priorityMap: Record<string, { label: string; tag: string }> = {
  P1: { label: "P1 紧急", tag: "tag-red" },
  P2: { label: "P2 普通", tag: "tag-amber" },
  P3: { label: "P3 低优先", tag: "tag-blue" },
};
export const priorityLabel = (p: string) => priorityMap[p]?.label ?? p;
export const priorityTag = (p: string) => priorityMap[p]?.tag ?? "tag-blue";

export const priorityTheme = (p: string): string => {
  const m: Record<string, string> = { P1: "danger", P2: "warning", P3: "primary" };
  return m[p] || "primary";
};

// 工单类型（统一口径）：source_code 现承载「工单类型」，10 内置 + 后台新增。
// 后台新增类型（custom_*）由 configStore 动态供名，此处兜底内置 10 类固有色/名。
export const sourceMap: Record<string, { label: string; cls: string; color: string }> = {
  plan: { label: "运营计划工单", cls: "src-plan", color: "#2563eb" },
  power_gen: { label: "发电量异常工单", cls: "src-alert", color: "#dc2626" },
  curtailment: { label: "限电量异常工单", cls: "src-alert", color: "#d97706" },
  dual_rule: { label: "双细则异常工单", cls: "src-alert", color: "#7c3aed" },
  reliability: { label: "设备可靠性异常工单", cls: "src-alert", color: "#ea580c" },
  info_quality: { label: "信息化使用异常工单", cls: "src-alert", color: "#2563eb" },
  contract: { label: "应签未签工单", cls: "src-alert", color: "#0891b2" },
  cost: { label: "成本费用工单", cls: "src-alert", color: "#059669" },
  satisfaction: { label: "客户满意度工单", cls: "src-alert", color: "#db2777" },
  meeting: { label: "关键会议工单", cls: "src-meeting", color: "#d97706" },
};
export const sourceLabel = (s: string) => useConfigStore().sourceName(s, sourceMap[s]?.label ?? s);
export const sourceTagClass = (s: string) => sourceMap[s]?.cls ?? "";

export const escLabel: Record<number, string> = { 0: "", 1: "P3 预警", 2: "P2 升级", 3: "P1 严重" };
export const escTag = (lvl: number) => (lvl >= 3 ? "tag-red" : "tag-amber");

/** 是否已关联真实钉钉审批单（排除本地占位 "OA-YYYYMMDD-NNN"） */
export const hasLiveOA = (oaId: string | null | undefined): boolean =>
  !!oaId && !oaId.startsWith("OA-");

/** 审批流步骤定义（展示口径三步；数据层旁支状态经 STAGE 就近归并，见 flowProgress） */
export const FLOW_STEPS = ["pending", "executing", "closed"] as const;

/** alert 五阶段顺序（与后端 alert_phase 对齐） */
export const ALERT_PHASES = ["confirming", "dispatching", "tracking", "reexamining", "recovered"] as const;

/** 根据当前状态计算审批流进度。
 *  alert 主单（有 alert_phase）→ 五阶段：分析确认 → 派发工单 → 已派工单(跟踪) → 指标复核 → 已恢复
 *  普通工单 / 措施工单 → 3步口径：待派发 → 执行中 → 已闭环（用户 09-03 拍板）
 */
export function flowProgress(
  status: string,
  metricType?: string | null,
  alertPhase?: string | null,
): { idx: number; steps: { code: string; state: "done" | "active" | "warn" | "todo" }[] } {
  // 异常主单（metric_type 非空 且 已回填进阶段）→ 五阶段闭环
  if (metricType && alertPhase) {
    const idx = ALERT_PHASES.indexOf(alertPhase as any);
    const cur = idx < 0 ? 0 : idx;
    return {
      idx: cur,
      steps: ALERT_PHASES.map((code, i) => ({
        code,
        state: (i < cur ? "done" : i === cur ? "active" : "todo") as "done" | "active" | "todo",
      })),
    };
  }

  // 普通工单 / 措施工单 / 待回填主单 → 三步口径（旁支状态就近归并，OA 驱动只推进状态不改步骤口径）
  const STEP_CODES: readonly string[] = FLOW_STEPS;
  const STAGE: Record<string, number> = {
    pending: 0,
    scheduled: 0,
    approving: 1,
    dispatched: 1,
    executing: 1,
    verifying: 1,
    overdue: 1,
    closed: 2,
    rejected: 0,
  };
  const idx = STAGE[status] ?? 0;
  const steps = STEP_CODES.map((code, i) => {
    if (status === "rejected") return { code, state: i === 0 ? ("warn" as const) : ("todo" as const) };
    if (i < idx) return { code, state: "done" as const };
    if (i === idx) return { code, state: status === "overdue" ? ("warn" as const) : ("active" as const) };
    return { code, state: "todo" as const };
  });
  return { idx, steps };
}

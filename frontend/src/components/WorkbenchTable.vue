<template>
  <div class="workbench">
    <div ref="topScroller" class="top-scroller" aria-label="工单表格横向滚动" @scroll="syncFromTop">
      <div class="top-scroll-content"></div>
    </div>
    <t-table
      ref="tableRef"
      class="table-viewport"
      :data="items"
      :columns="columns"
      row-key="id"
      :loading="loading"
      hover
      resizable
      :selected-row-keys="selKeys"
      size="small"
      cell-empty-content="—"
      @select-change="onSelectChange"
      @row-click="onRowClick"
      :pagination="pagination"
      @page-change="onPageChange"
    >
      <!-- 信息块：仅保留系统工单号，其余业务信息分行展示。 -->
      <template #info="{ row }">
        <div class="info">
          <div class="info-code">系统单号 {{ row.code }}</div>
          <div class="info-title" :title="row.title">{{ row.title }}</div>
          <div class="info-grid">
            <span><b>项目</b>{{ row.project_name || "—" }}</span>
            <span><b>区域</b>{{ row.region || "—" }}</span>
            <span><b>类型</b>{{ sourceLabel(row.source_code) }}</span>
            <span><b>优先级</b>{{ priorityLabel(row.priority) }}</span>
            <span v-if="row.escalation_level > 0" class="info-alert"><b>预警</b>{{ escLabel[row.escalation_level] }}</span>
          </div>
          <div class="info-deliverable"><b>交付物</b><span :title="row.task_deliverable || ''">{{ row.task_deliverable || "—" }}</span></div>
        </div>
      </template>

      <!-- 责任人 / 审批人 -->
      <template #who="{ row }">
        <div class="who">
          <div class="who-line"><span class="who-k">责任人</span><span class="who-v">{{ row.person_name || "—" }}</span></div>
          <div class="who-line"><span class="who-k">审批人</span><span class="who-v">{{ row.approver_name || "—" }}</span></div>
        </div>
      </template>

      <!-- 时间列 -->
      <template #time="{ row }">
        <div class="time">
          <div>
            <span class="time-dd" :class="{ 'time-overdue': row.is_overdue || row.status === 'overdue' }">{{ row.deadline || "—" }}</span>
            <span v-if="row.is_overdue || row.status === 'overdue'" class="time-badge">+{{ row.overdue_days }}天</span>
          </div>
          <div class="time-ps">计划开始 {{ row.planned_start_date || "—" }}</div>
        </div>
      </template>

      <!-- 流程点灯 -->
      <template #flow="{ row }">
        <div class="flow">
          <div class="flow-steps">
            <template v-for="(s, i) in flowSteps(row)" :key="s.code">
              <span v-if="i > 0" class="flow-line"></span>
              <span class="flow-step" :class="'st-' + s.state">
                <span class="flow-label">{{ s.label }}</span>
                <span class="flow-dot">{{ stepIcon(s.state) }}</span>
              </span>
            </template>
          </div>
          <div class="flow-phase">{{ flowPhase(row) }}</div>
        </div>
      </template>

      <!-- 触发原因 + 行动要求 -->
      <template #req="{ row }">
        <div class="req">
          <div class="req-item"><span class="req-label">触发原因</span><span class="req-text" :title="row.reason">{{ row.reason || "—" }}</span></div>
          <div class="req-item"><span class="req-label">行动要求</span><span class="req-text" :title="row.action">{{ row.action || "—" }}</span></div>
        </div>
      </template>

      <!-- 处理 / 回填 -->
      <template #handle="{ row }">
        <div class="hand">
          <div v-if="row.judgment_status" class="hand-item">
            <span class="hand-label">判断</span>
            <span class="tag" :class="judgmentTheme(row.judgment_status)">{{ judgmentLabel(row.judgment_status) }}</span>
          </div>
          <div v-if="row.measure_progress && row.measure_progress.total" class="hand-item">
            <span class="hand-label">措施闭环</span>
            <span class="hand-measure">{{ row.measure_progress.closed }}/{{ row.measure_progress.total }}</span>
            <span class="hand-bar"><span class="hand-fill" :style="{ width: pct(row.measure_progress.closed, row.measure_progress.total) + '%', background: row.measure_progress.closed === row.measure_progress.total ? 'var(--green)' : 'var(--blue)' }"></span></span>
          </div>
          <div v-if="(row.occurrences || []).length" class="hand-item">
            <span class="hand-label">最近异常</span>
            <span class="hand-text">{{ (row.occurrences || []).length }}次 · {{ (row.occurrences || [])[0]?.occurred_at || "—" }}</span>
          </div>
          <div v-if="!row.judgment_status && !(row.measure_progress && row.measure_progress.total) && !(row.occurrences || []).length" class="hand-empty">—</div>
        </div>
      </template>

      <!-- 操作列 -->
      <template #op="{ row }">
        <div class="op">
          <span v-if="dingtalkDriving(row)" class="tag tag-green" title="已关联钉钉审批单，流转由钉钉驱动">钉钉驱动</span>
          <template v-for="(b, bi) in opButtons(row)" :key="bi">
            <span v-if="b.kind === 'hint'" class="op-hint">{{ b.text }}</span>
            <t-button v-else-if="b.kind === 'drawer'" size="small" :theme="b.primary ? 'primary' : 'default'" variant="outline"
              @click.stop="openDrawer(b.drawer!, row)">{{ b.label }}</t-button>
            <t-button v-else size="small" :theme="b.primary ? 'primary' : 'default'" :variant="b.primary ? 'base' : 'outline'"
              :loading="!!busy[row.id + ':' + b.action!]" :disabled="b.disabled" @click.stop="runTransition(row, b.action!)">{{ b.label }}</t-button>
          </template>
          <t-button size="small" theme="default" variant="text" @click.stop="$emit('row-click', row)">详情 →</t-button>
        </div>
      </template>
    </t-table>

    <!-- 抽屉：派发（发起OA审批） -->
    <t-drawer v-model:visible="dispatchDrawer.visible" header="发起审批 · 派发工单" size="420px" :footer="false">
      <div class="dr-info" v-if="dispatchDrawer.wo">
        <div class="di"><b>编号</b><span>{{ dispatchDrawer.wo.code }}</span></div>
        <div class="di"><b>标题</b><span>{{ dispatchDrawer.wo.title }}</span></div>
        <div class="di"><b>提示</b><span class="muted">发起前依赖的必填字段缺失会被拦截</span></div>
      </div>
      <div class="fld">
        <label>责任人<span class="req">*</span></label>
        <t-select v-model="dispatchDrawer.person_id" placeholder="输入姓名搜索责任人" filterable clearable :options="executorOptions" />
      </div>
      <div class="fld">
        <label>审批人<span class="req">*</span></label>
        <t-select v-model="dispatchDrawer.approver_id" placeholder="输入姓名搜索审批人" filterable clearable :options="approverOptions" />
      </div>
      <div class="dr-foot">
        <t-button theme="default" variant="outline" @click="dispatchDrawer.visible = false">取消</t-button>
        <t-button theme="primary" :loading="dispatchDrawer.submitting" @click="confirmDispatchDrawer">确认派发</t-button>
      </div>
    </t-drawer>

    <!-- 抽屉：分析确认 · 填写措施工单（alert 待回填/分析确认阶段） -->
    <t-drawer v-model:visible="measuresDrawer.visible" header="分析确认 · 填写措施工单" size="640px" :footer="false">
      <div class="dr-info" v-if="measuresDrawer.wo">
        <div class="di"><b>编号</b><span>{{ measuresDrawer.wo.code }}</span></div>
        <div class="di"><b>标题</b><span>{{ measuresDrawer.wo.title }}</span></div>
        <div v-if="measuresDrawer.wo.status === 'pending'" class="fld" style="margin-top:12px">
          <label>根因分析<span class="req">*</span></label>
          <t-textarea v-model="measuresDrawer.reason" placeholder="分析异常/事项的根本原因" :autosize="{ minRows: 3, maxRows: 6 }" />
        </div>
        <div class="measure-head">
          <span>📋 措施草稿（{{ measuresDrawer.tasks.length }}条）</span>
          <t-button size="small" variant="text" @click="addMeasureTask">＋ 添加工单</t-button>
        </div>
        <div v-for="(t, i) in measuresDrawer.tasks" :key="i" class="measure-card">
          <div class="measure-card-hd" @click="t.expanded = !t.expanded">
            <span class="m-idx">{{ i + 1 }}</span>
            <span class="m-title">{{ t.title || "（未填写标题）" }}</span>
            <span class="m-arrow">{{ t.expanded ? "▲" : "▼" }}</span>
          </div>
          <div class="measure-card-bd" v-show="t.expanded">
            <div class="fld"><label>工单标题<span class="req">*</span></label><t-input v-model="t.title" placeholder="措施工单标题" /></div>
            <div class="fld"><label>工单类型</label><t-select v-model="t.type_id" placeholder="请选择工单类型" clearable :options="woTypeOptions" /></div>
            <div class="fld"><label>触发原因</label><t-textarea v-model="t.reason" :autosize="{ minRows: 2 }" :placeholder="'由 ' + measuresDrawer.wo.code + ' 触发'" /></div>
            <div class="fld"><label>行动要求</label><t-textarea v-model="t.action" :autosize="{ minRows: 2 }" placeholder="具体要做什么、达到什么标准" /></div>
            <div class="fld"><label>责任人<span class="req">*</span></label><SearchableSelect :model-value="t.person_id" :options="users || []" placeholder="搜索姓名…" @update:model-value="(v: number | undefined) => t.person_id = v" /></div>
            <div class="fld"><label>审批人<span class="req">*</span></label><SearchableSelect :model-value="t.approver_id" :options="users || []" placeholder="搜索姓名…" @update:model-value="(v: number | undefined) => t.approver_id = v" /></div>
            <div class="measure-meta">
              <t-date-picker v-model="t.planned_start_date" placeholder="计划开始" clearable allow-input />
              <t-date-picker v-model="t.deadline" placeholder="计划完成" clearable allow-input />
            </div>
            <div class="measure-del"><t-button size="small" variant="text" theme="danger" :disabled="measuresDrawer.tasks.length <= 1" @click="measuresDrawer.tasks.splice(i, 1)">✕ 删除</t-button></div>
          </div>
        </div>
      </div>
      <div class="dr-foot">
        <template v-if="measuresDrawer.wo && measuresDrawer.wo.status === 'pending'">
          <t-button theme="primary" :loading="measuresDrawer.submitting" @click="submitBackfill">提交回填 → 进入分析确认</t-button>
        </template>
        <template v-else>
          <t-button theme="default" variant="outline" :loading="measuresDrawer.submitting" @click="saveMeasureTasks">💾 保存草稿</t-button>
          <t-button theme="primary" :loading="measuresDrawer.submitting" @click="confirmAnalysis">确认分析 · 生成措施工单</t-button>
        </template>
      </div>
    </t-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from "vue";
import { toast, confirmDialog } from "@/utils/feedback";
import { getWoTypes } from "@/api/config";
import { getWorkOrder, updateWorkOrder, transitionWorkOrder, type WorkOrder } from "@/api/workorders";
import { backfillWO } from "@/api/pool";
import {
  sourceLabel, priorityLabel,
  escLabel, flowProgress, hasLiveOA, statusMap,
} from "@/utils/wo-display";
import SearchableSelect from "@/components/SearchableSelect.vue";

defineOptions({ name: "WorkbenchTable" });

const props = defineProps<{
  items: WorkOrder[];
  loading?: boolean;
  total?: number;
  page?: number;
  pageSize?: number;
  users?: any[];
  selectedRowKeys?: (string | number)[];
}>();

const emit = defineEmits<{
  (e: "update:selected-row-keys", v: (string | number)[]): void;
  (e: "row-click", row: any): void;
  (e: "reload"): void;
  (e: "page-change", p: { current: number; pageSize: number }): void;
}>();

const selKeys = computed(() => props.selectedRowKeys ?? []);
const topScroller = ref<HTMLElement | null>(null);
const tableViewport = ref<HTMLElement | null>(null);
const tableRef = ref<{ $el?: HTMLElement } | null>(null);
let syncingHorizontalScroll = false;

onMounted(async () => {
  await nextTick();
  const viewport = tableRef.value?.$el?.querySelector<HTMLElement>(".t-table__content");
  if (!viewport) return;
  tableViewport.value = viewport;
  viewport.addEventListener("scroll", syncFromTable, { passive: true });
});

function syncFromTop() {
  if (syncingHorizontalScroll || !topScroller.value || !tableViewport.value) return;
  syncingHorizontalScroll = true;
  tableViewport.value.scrollLeft = topScroller.value.scrollLeft;
  syncingHorizontalScroll = false;
}

function syncFromTable() {
  if (syncingHorizontalScroll || !topScroller.value || !tableViewport.value) return;
  syncingHorizontalScroll = true;
  topScroller.value.scrollLeft = tableViewport.value.scrollLeft;
  syncingHorizontalScroll = false;
}

/* ---------- 显示辅助 ---------- */
const stepIcon = (s: string) => (s === "done" ? "✓" : s === "active" ? "●" : s === "warn" ? "⚠" : "○");
const pct = (a: number, b: number) => (b > 0 ? Math.round((a / b) * 100) : 0);
// 异常主单（非措施工单且带 metric_type）→ 五阶段；措施工单走普通三步
const isAnomalyHost = (row: WorkOrder) => !!row.metric_type && !row.is_measure;

function flowSteps(row: WorkOrder) {
  const fp = flowProgress(row.status, row.metric_type, row.alert_phase);
  return fp.steps.map((s) => ({ code: s.code, state: s.state, label: statusMap[s.code]?.label ?? s.code }));
}
function flowPhase(row: WorkOrder) {
  const phase = isAnomalyHost(row) && row.alert_phase ? "五阶段闭环" : "三步口径";
  const cur = row.alert_phase ? (statusMap[row.alert_phase]?.label ?? row.alert_phase) : (statusMap[row.status]?.label ?? row.status);
  return `${phase} · ${cur}`;
}

function judgmentLabel(v: string): string {
  const m: Record<string, string> = {
    approved: "已批准", rejected: "已驳回", judging: "判断中",
    no_action_needed: "无需措施", degraded: "已降级", pending_judge: "待判断",
    approved_suggested: "通过(有建议)", approved_as_is: "通过",
  };
  return m[v] || v;
}
function judgmentTheme(v: string): string {
  const m: Record<string, string> = {
    approved: "tag-green", approved_suggested: "tag-green", approved_as_is: "tag-green",
    rejected: "tag-red", judging: "tag-amber", pending_judge: "tag-amber",
    degraded: "tag-gray", no_action_needed: "tag-gray",
  };
  return m[v] || "tag-gray";
}

const dingtalkDriving = (row: WorkOrder) => hasLiveOA(row.oa_id);

function guardOaDriven(row: WorkOrder): boolean {
  if (hasLiveOA(row.oa_id)) {
    toast.warning("该工单已由钉钉OA审批流驱动，请在钉钉OA审批中更改状态");
    return true;
  }
  return false;
}

/* ---------- 操作列按钮编排 ---------- */
interface OpBtn {
  kind?: "button" | "drawer" | "hint";
  label?: string;
  action?: string;
  drawer?: "dispatch" | "measures";
  primary?: boolean;
  disabled?: boolean;
  text?: string;
}
function opButtons(row: WorkOrder): OpBtn[] {
  if (isAnomalyHost(row)) {
    if (row.alert_phase === "confirming") {
      return [
        { kind: "drawer", drawer: "measures", label: "✍️ 填写措施工单", primary: true },
        { kind: "button", action: "close", label: "无需措施·闭环" },
      ];
    }
    if (row.alert_phase === "dispatching") {
      return [{ kind: "button", action: "dispatch_measures", label: "派发措施工单", primary: true }];
    }
    if (row.alert_phase === "tracking") {
      const t = row.measure_progress?.total ?? 0;
      return [{ kind: "hint", text: `等待措施闭环${t ? " " + row.measure_progress?.closed + "/" + t : ""}` }];
    }
    if (row.alert_phase === "reexamining") {
      return [{ kind: "button", action: "confirm_recovered", label: "✓ 指标恢复·闭环", primary: true }];
    }
    return [];
  }
  const ops: OpBtn[] = [];
  // 已关联真实钉钉审批单：状态由钉钉审批流驱动，不显示手动流转按钮（重置作兜底）
  if (dingtalkDriving(row)) {
    if (["approving", "dispatched", "executing", "verifying"].includes(row.status)) {
      ops.push({ kind: "hint", text: "钉钉审批流转中 · 去钉钉OA处理" });
    }
    if (row.status !== "pending" && row.status !== "closed") {
      ops.push({ kind: "button", action: "reset", label: "重置" });
    }
    return ops;
  }
  if (row.status === "pending" || row.status === "approving") {
    ops.push({ kind: "drawer", drawer: "dispatch", label: "发起审批·派发", primary: true });
  }
  if (row.status === "dispatched") ops.push({ kind: "button", action: "start_exec", label: "开始执行", primary: true });
  if (row.status === "executing") ops.push({ kind: "button", action: "submit_evidence", label: "提交佐证", primary: true });
  if (row.status === "verifying") ops.push({ kind: "button", action: "close", label: "验收闭环", primary: true });
  if (row.status === "approving") ops.push({ kind: "button", action: "reject", label: "驳回" });
  if (row.status !== "pending" && row.status !== "closed") ops.push({ kind: "button", action: "reset", label: "重置" });
  return ops;
}

const busy = reactive<Record<string, boolean>>({});
function runTransition(row: WorkOrder, action: string) {
  if (action === "reset" || action === "close") {
    const message = action === "reset"
      ? `确认把工单 ${row.code} 重置为「待派发(未发起)」？已发起的审批/执行记录将被清空。`
      : `确认验收通过并闭环工单 ${row.code}？`;
    confirmDialog(message).then((ok) => {
      if (ok) doTransition(row, action);
    });
    return;
  }
  if (guardOaDriven(row)) return;
  doTransition(row, action);
}
async function doTransition(row: WorkOrder, action: string) {
  const k = row.id + ":" + action;
  busy[k] = true;
  try {
    await transitionWorkOrder(row.id, action);
    toast.success("已操作：" + actionLabel(action));
    emit("reload");
  } catch (e: any) {
    toast.error(e.message || "操作失败");
  } finally {
    busy[k] = false;
  }
}
function actionLabel(a: string): string {
  const m: Record<string, string> = {
    dispatch: "派发", start_exec: "开始执行", submit_evidence: "提交佐证",
    close: "闭环", reject: "驳回", reset: "重置",
    confirm_analysis: "确认分析", dispatch_measures: "派发措施", confirm_recovered: "确认恢复",
  };
  return m[a] || a;
}

/* ---------- 派发抽屉 ---------- */
const dispatchDrawer = reactive({ visible: false, submitting: false, wo: null as WorkOrder | null, person_id: undefined as number | undefined, approver_id: undefined as number | undefined });
const executorOptions = computed(() =>
  (props.users || []).map((u) => ({ value: u.id, label: `${u.name}${u.department ? " · " + u.department : ""}` }))
);
const approverOptions = computed(() =>
  (props.users || []).filter((u) => u.role === "approver" || u.role === "admin")
    .map((u) => ({ value: u.id, label: `${u.name}${u.department ? " · " + u.department : ""}` }))
);
function openDispatchDrawer(row: WorkOrder) {
  dispatchDrawer.wo = row;
  dispatchDrawer.person_id = row.person_id ?? undefined;
  dispatchDrawer.approver_id = row.approver_id ?? undefined;
  dispatchDrawer.visible = true;
}
async function confirmDispatchDrawer() {
  const wo = dispatchDrawer.wo; if (!wo) return;
  if (dispatchDrawer.submitting) return;
  if (!dispatchDrawer.person_id || !dispatchDrawer.approver_id) {
    toast.warning("请选择责任人和审批人后再派发");
    return;
  }
  dispatchDrawer.submitting = true;
  try {
    if (dispatchDrawer.person_id !== wo.person_id || dispatchDrawer.approver_id !== wo.approver_id) {
      await updateWorkOrder(wo.id, { person_id: dispatchDrawer.person_id, approver_id: dispatchDrawer.approver_id });
    }
    await transitionWorkOrder(wo.id, "dispatch");
    dispatchDrawer.visible = false;
    toast.success("已派发");
    emit("reload");
  } catch (e: any) {
    toast.error("派发失败：" + (e.message || "未知错误"));
  } finally {
    dispatchDrawer.submitting = false;
  }
}

/* ---------- 措施工单抽屉 ---------- */
interface MeasureTask { title: string; person_id: number | undefined; approver_id: number | undefined; planned_start_date: string; deadline: string; reason: string; action: string; type_id: number | null; expanded: boolean; }
const measuresDrawer = reactive({ visible: false, submitting: false, wo: null as WorkOrder | null, reason: "", tasks: [] as MeasureTask[] });
let measuresLoadSeq = 0;
const woTypeOptions = ref<{ value: number; label: string }[]>([]);

function resolveUserId(t: any, idKey: string, nameKey: string): number | undefined {
  if (typeof t[idKey] === "number") return t[idKey];
  const name = (t[nameKey] || "").trim();
  if (!name) return undefined;
  const u = (props.users || []).find((x) => x.name === name);
  return u ? u.id : undefined;
}

function openDrawer(kind: "dispatch" | "measures", row: WorkOrder) {
  if (kind === "dispatch" && guardOaDriven(row)) return;
  if (kind === "dispatch") { openDispatchDrawer(row); return; }
  const seq = ++measuresLoadSeq;
  getWorkOrder(row.id).then((full) => {
    if (seq !== measuresLoadSeq) return;
    measuresDrawer.wo = full;
    measuresDrawer.reason = "";
    const tasks = (full as any).triggered_wo_tasks;
    if (Array.isArray(tasks) && tasks.length > 0) {
      measuresDrawer.tasks = tasks.map((t: any) => ({
        title: t.title || "",
        person_id: resolveUserId(t, "person_id", "person_name"),
        approver_id: resolveUserId(t, "approver_id", "approver_name"),
        planned_start_date: t.planned_start_date || "", deadline: t.deadline || "",
        reason: t.reason || full.reason || `由 ${full.code} 触发`, action: t.action || "",
        type_id: t.type_id ?? null, expanded: false,
      }));
    } else {
      measuresDrawer.tasks = [{ title: "", person_id: undefined, approver_id: undefined, planned_start_date: "", deadline: "", reason: `由 ${full.code} 触发`, action: "", type_id: null, expanded: true }];
    }
    measuresDrawer.visible = true;
  }).catch((e: any) => {
    if (seq === measuresLoadSeq) toast.error("加载措施草稿失败：" + (e.message || "未知错误"));
  });
  if (!woTypeOptions.value.length) {
    getWoTypes().then((wt) => { woTypeOptions.value = wt.map((t: any) => ({ value: t.id, label: t.name })); }).catch(() => {});
  }
}
function addMeasureTask() {
  measuresDrawer.tasks.push({
    title: "", person_id: undefined, approver_id: undefined, planned_start_date: "", deadline: "",
    reason: measuresDrawer.wo ? `由 ${measuresDrawer.wo.code} 触发` : "",
    action: "", type_id: null, expanded: true,
  });
}
function cleanTasks(): any[] {
  return measuresDrawer.tasks
    .filter((t) => (t.title || "").trim())
    .map(({ expanded, ...rest }) => ({ ...rest, type_id: rest.type_id ? rest.type_id : null }));
}
function validateTasks(): string | null {
  const titled = measuresDrawer.tasks.filter((t) => (t.title || "").trim());
  for (let i = 0; i < titled.length; i++) {
    const t = titled[i];
    const miss: string[] = [];
    if (t.person_id == null) miss.push("责任人");
    if (t.approver_id == null) miss.push("审批人");
    if (!(t.planned_start_date || "").trim()) miss.push("计划开始");
    if (!(t.deadline || "").trim()) miss.push("计划完成");
    if (miss.length) return `第${i + 1}条「${(t.title || "").trim()}」缺：${miss.join("、")}`;
  }
  return null;
}
async function submitBackfill() {
  const wo = measuresDrawer.wo; if (!wo) return;
  if (!measuresDrawer.reason.trim()) { toast.warning("请先填写根因分析"); return; }
  const tasks = cleanTasks();
  if (!tasks.length) { toast.warning("请至少添加一条措施工单（填标题）"); return; }
  const v = validateTasks();
  if (v) { toast.warning(v); return; }
  measuresDrawer.submitting = true;
  try {
    await updateWorkOrder(wo.id, { triggered_wo_tasks: tasks });
    await backfillWO(wo.id, { reason: measuresDrawer.reason });
    measuresDrawer.visible = false;
    toast.success("已回填，进入分析确认");
    emit("reload");
  } catch (e: any) { toast.error("回填失败：" + e.message); } finally { measuresDrawer.submitting = false; }
}
async function saveMeasureTasks() {
  const wo = measuresDrawer.wo; if (!wo) return;
  const tasks = cleanTasks();
  if (!tasks.length) { toast.warning("请先填写措施工单标题再保存草稿"); return; }
  measuresDrawer.submitting = true;
  try {
    await updateWorkOrder(wo.id, { triggered_wo_tasks: tasks });
    measuresDrawer.visible = false;
    toast.success("草稿已保存");
    emit("reload");
  } catch (e: any) { toast.error("保存失败：" + e.message); } finally { measuresDrawer.submitting = false; }
}
async function confirmAnalysis() {
  const wo = measuresDrawer.wo; if (!wo) return;
  const tasks = cleanTasks();
  if (!tasks.length) { toast.warning("请至少添加一个措施工单"); return; }
  const v = validateTasks();
  if (v) { toast.warning(v); return; }
  measuresDrawer.submitting = true;
  try {
    await updateWorkOrder(wo.id, { triggered_wo_tasks: tasks });
    await transitionWorkOrder(wo.id, "confirm_analysis");
    measuresDrawer.visible = false;
    toast.success("已生成措施工单，阶段推进到「派发工单」");
    emit("reload");
  } catch (e: any) { toast.error("确认分析失败：" + e.message); } finally { measuresDrawer.submitting = false; }
}

/* ---------- 表格 / 多选 / 分页 ---------- */
const pagination = computed(() => ({
  current: props.page ?? 1, pageSize: props.pageSize ?? 20, total: props.total ?? 0,
  showJumper: true, showPageSize: true, pageSizeOptions: [10, 20, 50],
}));

function onSelectChange(keys: (string | number)[]) {
  emit("update:selected-row-keys", keys);
}
function onRowClick(ctx: { row: any; e: MouseEvent }) {
  const el = ctx.e.target as HTMLElement;
  if (el && el.closest("input,button,label")) return;
  emit("row-click", ctx.row);
}
function onPageChange(p: { current: number; pageSize: number }) {
  emit("page-change", p);
}

const columns = [
  { colKey: "row-select", type: "multiple" as const, width: 44, fixed: "left" as const },
  { colKey: "info", title: "工单信息", width: 300 },
  { colKey: "who", title: "责任人 / 审批人", width: 120 },
  { colKey: "time", title: "时间", width: 120 },
  { colKey: "flow", title: "流程进度", width: 248 },
  { colKey: "req", title: "触发原因 · 行动要求", width: 260 },
  { colKey: "handle", title: "处理 / 回填", width: 170 },
  { colKey: "op", title: "操作", width: 190, fixed: "right" as const },
];
</script>

<style scoped>
/* 只保留一条置顶横向滑条；操作列始终固定在右侧。 */
.workbench {
  --td-scrollbar-color: rgba(0, 0, 0, 0.35);
  --td-scrollbar-hover-color: rgba(0, 0, 0, 0.55);
}
.top-scroller { position: sticky; top: 0; z-index: 3; overflow-x: auto; overflow-y: hidden; height: 12px; margin: 0 0 8px; background: var(--card, #fff); }
.top-scroll-content { width: 1px; min-width: 1452px; height: 1px; }
.table-viewport { max-width: 100%; }
.table-viewport :deep(.t-table__content) { overflow-x: auto; scrollbar-width: none; }
.table-viewport :deep(.t-table__content::-webkit-scrollbar) { display: none; }
.table-viewport :deep(.t-table__content > table) { min-width: 1452px; }
.workbench :deep(.t-table__content) { scrollbar-width: none; }
.workbench :deep(.t-table__content::-webkit-scrollbar) { display: none; }
.workbench :deep(.t-table__row) { cursor: pointer; }
.info-code { font-family: monospace; font-size: 11px; color: var(--muted); margin-bottom: 4px; }
.info-title { font-weight: 600; font-size: 13px; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 8px; margin-top: 5px; font-size: 11px; color: #444; }
.info-grid span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.info-grid b, .info-deliverable b { margin-right: 4px; color: var(--muted); font-weight: 500; }
.info-alert { color: var(--red); }
.info-deliverable { display: flex; gap: 2px; margin-top: 4px; font-size: 11px; color: #444; }
.info-deliverable span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.who-line { font-size: 12px; line-height: 1.7; }
.who-k { color: var(--muted); font-size: 11px; margin-right: 4px; }
.who-v { color: #333; }
/* 来源标签配色（原列表页 .src-* 迁入，保证标签有底色） */
.src-plan { background: #dbeafe; color: #1e40af; }
.src-alert { background: #fee2e2; color: #991b1b; }
.src-meeting { background: #fef3c7; color: #92400e; }
.src-manual { background: #e0e7ff; color: #3730a3; }
.src-measure { background: #e0f2fe; color: #0369a1; }
.time-dd { font-weight: 600; font-size: 13px; }
.time-overdue { color: var(--red); }
.time-badge { color: var(--red); font-weight: 700; font-size: 11px; margin-left: 4px; }
.time-ps { font-size: 11px; color: var(--muted); margin-top: 2px; }
.req-item { margin-bottom: 6px; }
.req-item:last-child { margin-bottom: 0; }
.req-label { display: block; font-size: 11px; color: var(--muted); font-weight: 600; }
.req-text { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 12px; color: #333; }
.hand-item { margin-bottom: 6px; }
.hand-item:last-child { margin-bottom: 0; }
.hand-label { font-size: 11px; color: var(--muted); display: block; }
.hand-measure { font-size: 12px; font-weight: 600; }
.hand-bar { display: inline-block; width: 60px; height: 6px; background: #eee; border-radius: 3px; vertical-align: middle; margin-left: 6px; overflow: hidden; }
.hand-fill { display: block; height: 6px; border-radius: 3px; }
.hand-text { font-size: 12px; }
.hand-empty { color: var(--muted); }
.op { display: flex; flex-direction: column; gap: 5px; align-items: flex-start; }
.op-hint { font-size: 11px; color: var(--muted); padding: 2px 0; }
.flow-steps { display: flex; align-items: flex-start; }
.flow-step { display: flex; flex-direction: column; align-items: center; gap: 2px; flex: 1 1 42px; min-width: 42px; }
.flow-label { font-size: 10px; color: #999; white-space: nowrap; letter-spacing: -0.5px; max-width: 100%; overflow: hidden; }
.flow-dot { width: 14px; height: 14px; border-radius: 50%; border: 2px solid #ccc; background: #fff; display: flex; align-items: center; justify-content: center; font-size: 9px; color: #fff; }
.st-done .flow-label { color: var(--green); }
.st-done .flow-dot { background: var(--green); border-color: var(--green); }
.st-active .flow-label { color: var(--blue); font-weight: 600; }
.st-active .flow-dot { background: var(--blue); border-color: var(--blue); box-shadow: 0 0 0 2px #cfe0ff; }
.st-warn .flow-dot { background: var(--amber); border-color: var(--amber); }
.flow-line { flex: none; width: 6px; height: 2px; background: #e3e3e3; margin-top: 6px; }
.flow-phase { font-size: 11px; color: var(--muted); margin-top: 4px; }
.dr-info { background: #f8f9fb; border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; margin-bottom: 14px; }
.di { display: flex; gap: 8px; font-size: 12px; margin-bottom: 3px; }
.di b { color: #555; min-width: 52px; }
.muted { color: var(--muted); }
.fld { margin-bottom: 12px; }
.fld label { display: block; font-size: 12px; color: #555; margin-bottom: 5px; font-weight: 600; }
.req { color: var(--red); }
.dr-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border); }
.measure-head { display: flex; justify-content: space-between; align-items: center; margin: 6px 0 10px; font-weight: 600; font-size: 13px; }
.measure-card { border: 1px solid var(--border); border-radius: 6px; margin-bottom: 8px; overflow: hidden; }
.measure-card-hd { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: #fafafa; cursor: pointer; }
.m-idx { font-size: 12px; color: var(--brand); font-weight: 600; }
.m-title { font-size: 12px; font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.m-arrow { font-size: 11px; color: var(--muted); }
.measure-card-bd { padding: 10px 12px; border-top: 1px solid #f0f0f0; }
.measure-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.measure-meta > * { width: 100%; }
.measure-del { text-align: right; margin-top: 8px; }
</style>

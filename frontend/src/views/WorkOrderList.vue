<template>
  <div class="wo-list">
    <div class="page-header">
      <div>
        <h1>工单列表</h1>
        <p class="meta">全部工单 · 筛选查询</p>
      </div>
      <t-space>
        <t-button theme="default" variant="outline" @click="openAgentHtmlImport">🖇️ 导入 Agent 复盘 HTML</t-button>
        <t-button theme="default" variant="outline" @click="exportCSV">导出 CSV</t-button>
        <t-button theme="primary" @click="router.push('/create')">＋ 新建工单</t-button>
      </t-space>
    </div>

    <t-card>
      <!-- 筛选 -->
      <div class="filters">
        <t-input v-model="filters.search" placeholder="搜索工单标题..." clearable @change="reload" style="width:200px" />
        <t-select v-model="filters.project_id" placeholder="项目" clearable @change="reload" style="width:160px">
          <t-option v-for="p in projects" :key="p.id" :value="p.id" :label="p.name" />
        </t-select>
        <t-select v-model="filters.region" placeholder="区域" clearable @change="reload" style="width:120px">
          <t-option v-for="r in regions" :key="r" :value="r" :label="r" />
        </t-select>
        <t-select v-model="filters.source_code" placeholder="来源" clearable @change="reload" style="width:120px">
          <t-option v-for="s in sources" :key="s.code" :value="s.code" :label="s.name" />
        </t-select>
        <t-select v-model="filters.status" placeholder="状态" clearable @change="reload" style="width:120px">
          <t-option v-for="s in statuses" :key="s.code" :value="s.code" :label="s.name" />
        </t-select>
        <t-select v-model="filters.priority" placeholder="优先级" clearable @change="reload" style="width:120px">
          <t-option value="P1" label="P1 紧急" />
          <t-option value="P2" label="P2 普通" />
          <t-option value="P3" label="P3 低优先" />
        </t-select>
        <t-input v-model="filters.person_name" placeholder="责任人搜索" @change="reload" style="width:160px" clearable />
        <t-button theme="default" variant="outline" @click="resetFilters">重置</t-button>
      </div>

      <t-table
        :data="list.items"
        :columns="columns"
        row-key="id"
        :loading="loading"
        hover
        @row-click="goDetail"
        :pagination="pagination"
        @page-change="onPageChange"
        size="small"
        cell-empty-content="—"
      >
        <template #code="{ row }">
          <t-link theme="primary" hover="color">{{ row.code }}</t-link>
        </template>
        <template #source_code="{ row }">
          <span class="src-tag" :class="sourceTagClass(row.source_code)">{{ sourceLabel(row.source_code) }}</span>
        </template>
        <template #priority="{ row }">
          <t-tag :theme="priorityTheme(row.priority)" size="small">{{ priorityLabel(row.priority) }}</t-tag>
        </template>
        <template #status="{ row }">
          <t-tag :theme="statusTheme(row.status)" size="small">{{ statusLabel(row.status) }}</t-tag>
        </template>
        <template #deadline="{ row }">
          <span :style="{ color: row.status === 'overdue' ? 'var(--red)' : '' }">{{ row.deadline }}</span>
        </template>
        <template #escalation="{ row }">
          <t-tag v-if="row.escalation_level > 0" :theme="row.escalation_level >= 3 ? 'danger' : 'warning'" size="small">
            {{ escLabel[row.escalation_level] }}
          </t-tag>
          <span v-else>—</span>
        </template>
        <template #action="{ row }">
          <t-button
            v-if="row.status === 'pending' || row.status === 'approving'"
            size="small"
            theme="primary"
            variant="outline"
            :loading="dispatching[row.id]"
            @click.stop="doDispatch(row)"
          >发起审批</t-button>
          <t-button
            v-if="row.status !== 'pending'"
            size="small"
            theme="default"
            variant="outline"
            @click.stop="doReset(row)"
          >重置</t-button>
        </template>
      </t-table>
    </t-card>

    <!-- 派发确认对话框 -->
    <t-dialog
      v-model:visible="dispatchDialog.visible"
      header="确认派发工单"
      :confirm-btn="{ content: '确认派发', loading: dispatchDialog.submitting }"
      :cancel-btn="'取消'"
      @confirm="confirmDispatch"
      @cancel="cancelDispatch"
      width="560"
    >
      <div class="dispatch-info" v-if="dispatchDialog.wo">
        <div class="di-row"><span class="di-label">工单编号</span><span>{{ dispatchDialog.wo.code }}</span></div>
        <div class="di-row"><span class="di-label">标题</span><span>{{ dispatchDialog.wo.title }}</span></div>
        <div class="di-row"><span class="di-label">项目</span><span>{{ dispatchDialog.wo.project_name || "—" }}</span></div>
        <div class="di-row"><span class="di-label">区域</span><span>{{ dispatchDialog.wo.region || "—" }}</span></div>
        <div class="di-row"><span class="di-label">来源</span><span>{{ sourceLabel(dispatchDialog.wo.source_code) }}</span></div>
        <div class="di-row"><span class="di-label">类型</span><span>{{ dispatchDialog.wo.type_name || "—" }}</span></div>
        <div class="di-row"><span class="di-label">计划开始</span><span>{{ dispatchDialog.wo.planned_start_date || "—" }}</span></div>
        <div class="di-row"><span class="di-label">截止日期</span><span>{{ dispatchDialog.wo.deadline || "—" }}</span></div>
        <div class="di-row"><span class="di-label">触发原因</span><span class="di-wrap">{{ dispatchDialog.wo.reason || "—" }}</span></div>
        <div class="di-row"><span class="di-label">行动要求</span><span class="di-wrap">{{ dispatchDialog.wo.action || "—" }}</span></div>
        <div class="di-row di-edit">
          <span class="di-label">责任人</span>
          <t-select v-model="dispatchDialog.person_id" placeholder="输入姓名搜索责任人" filterable clearable style="width:280px" :options="executorOptions" />
        </div>
        <div class="di-row di-edit">
          <span class="di-label">审批人</span>
          <t-select v-model="dispatchDialog.approver_id" placeholder="输入姓名搜索审批人" filterable clearable style="width:280px" :options="approverOptions" />
        </div>
      </div>
    </t-dialog>

    <!-- 导入 Agent 复盘 HTML 对话框 -->
    <t-dialog v-model:visible="agentImport.visible" header="导入 Agent 复盘 HTML" :footer="false" width="760">
      <div class="agent-import">
        <p class="ai-hint">粘贴「指标异常处置SOP」复盘的 HTML（或选本地 .html 文件），自动解析出措施草稿并生成一条「异常指标」工单进入判断流程——在工单详情里人工选择工单类型后点「生成措施工单并闭环」才会上列表。</p>
        <div class="ai-toolbar">
          <t-button size="small" variant="outline" @click="pickAgentHtmlFile">📂 选择 .html 文件</t-button>
          <span v-if="agentImport.filename" class="ai-filename">已载入：{{ agentImport.filename }}</span>
        </div>
        <input ref="agentHtmlInput" type="file" accept=".html,.htm" style="display:none" @change="onAgentHtmlFile" />
        <t-textarea v-model="agentImport.html" placeholder="在此粘贴 HTML 内容…" :autosize="{ minRows: 9, maxRows: 18 }" />

        <div v-if="agentImport.result" class="ai-result">
          <div v-if="agentImport.result.already_imported" class="ai-warn">⚠️ {{ agentImport.result.message }}</div>
          <template v-else>
            <div class="ai-ok">
              ✅ 已生成 <b>{{ agentImport.result.created }}</b> 条异常指标工单（含 <b>{{ agentImport.result.results?.[0]?.task_count ?? agentImport.result.parsed_count ?? 0 }}</b> 条措施草稿），已进入判断流程
              <span v-if="agentImport.result.skipped_duplicate">（跳过 {{ agentImport.result.skipped_duplicate }} 个重复）</span>
            </div>
            <div v-if="agentImport.result.project" class="ai-meta">
              项目 <b>{{ agentImport.result.project }}</b> ·
              指标 <b>{{ agentImport.result.trigger?.indicator || '—' }}</b> ·
              周期 <b>{{ agentImport.result.trigger?.period || '—' }}</b> ·
              解析 <b>{{ agentImport.result.parsed_count }}</b> 张
            </div>
            <ul v-if="agentImport.result.results?.length" class="ai-list">
              <li v-for="r in agentImport.result.results.slice(0, 12)" :key="r.code">
                <b>{{ r.code }}</b>
                <span class="ai-meta" v-if="r.task_count">· {{ r.task_count }} 条措施待生成</span>
                <span class="ai-unmapped">{{ r.unmapped?.length ? '留空待填：' + r.unmapped.join('；') : '字段齐全' }}</span>
              </li>
            </ul>
          </template>
        </div>

        <div class="ai-footer">
          <t-button theme="primary" :loading="agentImport.submitting" @click="submitAgentHtml">导入</t-button>
          <t-button theme="default" @click="agentImport.visible = false">关闭</t-button>
        </div>
      </div>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listWorkOrders, transitionWorkOrder, updateWorkOrder, type WorkOrderList } from "@/api/workorders";
import { getProjects, getSources, getStatuses, getUsersAll, type ConfigItem } from "@/api/config";
import { importAgentHtml, type AgentHtmlImportResult } from "@/api/imports";
import {
  statusLabel, statusTheme, priorityLabel, priorityTheme,
  sourceLabel, sourceTagClass, escLabel,
} from "@/utils/wo-display";

defineOptions({ name: "WorkOrderList" });

const route = useRoute();
const router = useRouter();
const loading = ref(false);
const list = ref<WorkOrderList>({ items: [], total: 0, page: 1, page_size: 20 });
const projects = ref<any[]>([]);
const sources = ref<ConfigItem[]>([]);
const statuses = ref<ConfigItem[]>([]);
const regions = ["华北", "华中", "华东", "华南", "西北", "西南", "东北"];
const page = ref(1);
const pageSize = ref(20);

const filters = reactive<any>({ project_id: undefined, source_code: undefined, status: undefined, priority: undefined, person_name: undefined, search: undefined });
const dispatching = reactive<Record<number, boolean>>({});
const allUsers = ref<any[]>([]);
const executors = ref<any[]>([]);
const approvers = ref<any[]>([]);
const dispatchDialog = reactive({
  visible: false,
  submitting: false,
  wo: null as any,
  person_id: undefined as number | undefined,
  approver_id: undefined as number | undefined,
});

const agentImport = reactive({
  visible: false,
  submitting: false,
  filename: "",
  html: "",
  result: null as AgentHtmlImportResult | null,
});
const agentHtmlInput = ref<HTMLInputElement | null>(null);

function openAgentHtmlImport() {
  agentImport.result = null;
  agentImport.filename = "";
  agentImport.visible = true;
}

function pickAgentHtmlFile() {
  agentHtmlInput.value?.click();
}

function onAgentHtmlFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (!f) return;
  const reader = new FileReader();
  reader.onload = () => {
    agentImport.html = String(reader.result || "");
    agentImport.filename = f.name;
  };
  reader.readAsText(f, "utf-8");
}

async function submitAgentHtml() {
  if (!agentImport.html.trim()) {
    alert("请先粘贴或选择 HTML 文件");
    return;
  }
  agentImport.submitting = true;
  try {
    agentImport.result = await importAgentHtml(agentImport.html);
    await reload();
  } catch (e: any) {
    alert("导入失败：" + (e.message || "未知错误"));
  } finally {
    agentImport.submitting = false;
  }
}

const executorOptions = computed(() =>
  executors.value.map((u: any) => ({
    value: u.id,
    label: `${u.name}${u.department ? ' · ' + u.department : ''}`,
  }))
);

const approverOptions = computed(() =>
  approvers.value.map((u: any) => ({
    value: u.id,
    label: `${u.name}${u.department ? ' · ' + u.department : ''}`,
  }))
);

const pagination = reactive({
  current: 1, pageSize: 20, total: 0, showJumper: true, showPageSize: true,
  pageSizeOptions: [10, 20, 50],
});

const columns = [
  { colKey: "code", title: "编号", width: 130 },
  { colKey: "source_code", title: "来源", width: 90 },
  { colKey: "project_name", title: "项目", width: 160, ellipsis: true },
  { colKey: "region", title: "区域", width: 100 },
  { colKey: "title", title: "标题", minWidth: 200, ellipsis: true },
  { colKey: "type_name", title: "类型", width: 90 },
  { colKey: "priority", title: "优先级", width: 100 },
  { colKey: "person_name", title: "责任人", width: 90 },
  { colKey: "approver_name", title: "审批人", width: 90 },
  { colKey: "planned_start_date", title: "计划开始", width: 110 },
  { colKey: "deadline", title: "截止", width: 110 },
  { colKey: "status", title: "状态", width: 90 },
  { colKey: "escalation", title: "告警", width: 90 },
  { colKey: "action", title: "操作", width: 110, fixed: "right" },
];

async function reload() {
  loading.value = true;
  try {
    const params: any = { page: page.value, page_size: pageSize.value };
    for (const [k, v] of Object.entries(filters)) {
      if (v !== undefined && v !== "" && v !== null) params[k] = v;
    }
    list.value = await listWorkOrders(params);
    pagination.total = list.value.total;
    pagination.current = page.value;
  } catch (e: any) { console.error(e); }
  finally { loading.value = false; }
}

function onPageChange(p: any) {
  page.value = p.current;
  pageSize.value = p.pageSize;
  reload();
}

function resetFilters() {
  Object.keys(filters).forEach((k) => (filters[k] = undefined));
  page.value = 1; reload();
}

function goDetail({ row }: any) { router.push(`/work-orders/${row.id}`); }

async function doDispatch(row: any) {
  // 先获取完整工单信息（含责任人/审批人姓名）
  try {
    const { getWorkOrder } = await import("@/api/workorders");
    const wo = await getWorkOrder(row.id);
    dispatchDialog.wo = wo;
    dispatchDialog.person_id = wo.person_id ?? undefined;
    dispatchDialog.approver_id = wo.approver_id ?? undefined;
    dispatchDialog.visible = true;
  } catch (e: any) {
    alert('获取工单信息失败：' + (e.message || '未知错误'));
  }
}

async function confirmDispatch() {
  const wo = dispatchDialog.wo;
  if (!wo) return;
  dispatchDialog.submitting = true;
  try {
    // 如果责任人/审批人变了，先更新
    if (dispatchDialog.person_id !== wo.person_id || dispatchDialog.approver_id !== wo.approver_id) {
      await updateWorkOrder(wo.id, {
        person_id: dispatchDialog.person_id,
        approver_id: dispatchDialog.approver_id,
      });
    }
    // 发起派发
    await transitionWorkOrder(wo.id, 'dispatch');
    dispatchDialog.visible = false;
    await reload();
  } catch (e: any) {
    alert('派发失败：' + (e.message || '未知错误'));
  } finally {
    dispatchDialog.submitting = false;
  }
}

function cancelDispatch() {
  dispatchDialog.visible = false;
  dispatchDialog.wo = null;
}

function exportCSV() {
  const rows = list.value.items;
  const head = ["编号", "来源", "项目", "区域", "标题", "类型", "优先级", "责任人", "审批人", "计划开始", "截止", "状态"];
  const lines = [head.join(",")];
  for (const w of rows) {
    lines.push([w.code, sourceLabel(w.source_code), w.project_name || "", w.region || "", `"${w.title}"`, w.type_name || "", w.priority, w.person_name || "", w.approver_name || "", w.planned_start_date || "", w.deadline || "", statusLabel(w.status)].join(","));
  }
  const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `工单列表_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
}

async function doReset(row: any) {
  if (!confirm(`确认把工单 ${row.code} 重置为「待派发(未发起)」？已发起的审批/执行记录将被清空。`)) return;
  try {
    await transitionWorkOrder(row.id, "reset");
    await reload();
  } catch (e: any) {
    alert("重置失败：" + (e.message || "未知错误"));
  }
}

onMounted(async () => {
  const q = route.query;
  filters.status = q.status || undefined;
  filters.source_code = q.source_code || undefined;
  filters.priority = q.priority || undefined;
  const [p, s, st, u] = await Promise.all([getProjects(), getSources(), getStatuses(), getUsersAll()]);
  projects.value = p; sources.value = s; statuses.value = st;
  allUsers.value = u;
  // 责任人 = 全员，审批人 = 审批人角色+管理员
  executors.value = u;
  approvers.value = u.filter((x: any) => x.role === 'approver' || x.role === 'admin');
  await reload();
});
</script>

<style scoped>
.wo-list .page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { color: var(--muted); font-size: 12px; margin-top: 4px; }
.filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.src-tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 700; }
.src-plan { background: #dbeafe; color: #1e40af; }
.src-alert { background: #fee2e2; color: #991b1b; }
.src-meeting { background: #fef3c7; color: #92400e; }
.src-manual { background: #e0e7ff; color: #3730a3; }
.dispatch-info { display: flex; flex-direction: column; gap: 10px; }
.di-row { display: flex; align-items: center; gap: 12px; font-size: 13px; }
.di-label { width: 80px; flex-shrink: 0; color: var(--muted); font-weight: 600; }
.di-wrap { word-break: break-all; line-height: 1.5; }
.di-edit { padding-top: 8px; border-top: 1px solid var(--border); margin-top: 4px; }
.agent-import { display: flex; flex-direction: column; gap: 12px; }
.ai-hint { color: var(--muted); font-size: 12px; margin: 0; }
.ai-toolbar { display: flex; align-items: center; gap: 10px; }
.ai-filename { color: var(--muted); font-size: 12px; }
.ai-result { background: #f6f8fb; border: 1px solid var(--border); border-radius: 6px; padding: 12px 14px; }
.ai-ok { color: #0f6e56; font-size: 13px; margin-bottom: 6px; }
.ai-warn { color: #b9770e; font-size: 13px; }
.ai-meta { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
.ai-list { margin: 0; padding-left: 4px; list-style: none; max-height: 200px; overflow: auto; }
.ai-list li { font-size: 12px; padding: 3px 0; display: flex; gap: 8px; align-items: baseline; }
.ai-unmapped { color: #b9770e; }
.ai-footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
</style>

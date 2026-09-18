<template>
  <div class="wo-list">
    <div class="page-header">
      <div>
        <h1>工单列表</h1>
        <p class="meta">全部工单 · 宽表工作台 · 就地流转</p>
      </div>
      <t-space>
        <t-button theme="default" variant="outline" :disabled="!selectedRowKeys.length" @click="batchDispatch">
          📤 批量派发<template v-if="selectedRowKeys.length">({{ selectedRowKeys.length }})</template>
        </t-button>
        <t-button theme="default" variant="outline" :disabled="!selectedRowKeys.length" @click="batchReset">
          批量重置<template v-if="selectedRowKeys.length">({{ selectedRowKeys.length }})</template>
        </t-button>
        <t-button theme="default" variant="outline" :disabled="!selectedRowKeys.length" @click="exportSelectedCSV">
          导出选中<template v-if="selectedRowKeys.length">({{ selectedRowKeys.length }})</template>
        </t-button>
        <t-button theme="default" variant="outline" @click="openAgentHtmlImport">🖇️ 导入 Agent 复盘 HTML</t-button>
        <t-button theme="default" variant="outline" @click="exportCSV(list.items)">导出当前页 CSV</t-button>
        <t-button theme="primary" @click="router.push('/create')">＋ 新建工单</t-button>
      </t-space>
    </div>

    <t-card>
      <!-- 筛选 -->
      <div class="filters">
        <t-input v-model="filters.search" placeholder="搜索工单标题..." clearable @change="applyFilters" @enter="applyFilters" style="width:200px" />
        <t-select v-model="filters.project_id" placeholder="项目" clearable filterable @change="applyFilters" style="width:180px">
          <t-option v-for="p in projectOptions" :key="p.id" :value="p.id" :label="p.name" />
        </t-select>
        <t-select v-model="filters.region" placeholder="区域" clearable @change="applyFilters" style="width:120px">
          <t-option v-for="r in regions" :key="r" :value="r" :label="r" />
        </t-select>
        <t-select v-model="filters.source_code" placeholder="工单类型" clearable @change="applyFilters" style="width:130px">
          <t-option v-for="s in sources" :key="s.code" :value="s.code" :label="s.name" />
        </t-select>
        <t-select v-model="filters.status" placeholder="状态" clearable @change="applyFilters" style="width:120px">
          <t-option v-for="s in statuses" :key="s.code" :value="s.code" :label="s.name" />
        </t-select>
        <t-select v-model="filters.priority" placeholder="优先级" clearable @change="applyFilters" style="width:120px">
          <t-option value="P1" label="P1 紧急" />
          <t-option value="P2" label="P2 普通" />
          <t-option value="P3" label="P3 低优先" />
        </t-select>
        <t-input v-model="filters.person_name" placeholder="责任人搜索" @change="applyFilters" @enter="applyFilters" style="width:160px" clearable />
        <t-button theme="default" variant="outline" @click="resetFilters">重置</t-button>
      </div>

      <WorkbenchTable
        :items="list.items"
        :loading="loading"
        :total="list.total"
        :page="page"
        :page-size="pageSize"
        :users="allUsers"
        v-model:selected-row-keys="selectedRowKeys"
        @row-click="goDetail"
        @reload="reload"
        @page-change="onPageChange"
      />
    </t-card>

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
import { toast, confirmDialog } from "@/utils/feedback";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listWorkOrders, transitionWorkOrder, type WorkOrderList } from "@/api/workorders";
import { getStatuses, getUsersAll, getWoTypes, type ConfigItem } from "@/api/config";
import { importAgentHtml, type AgentHtmlImportResult } from "@/api/imports";
import { statusLabel, sourceLabel } from "@/utils/wo-display";
import WorkbenchTable from "@/components/WorkbenchTable.vue";
import { downloadCsv } from "@/utils/csv";
import dayjs from "dayjs";

defineOptions({ name: "WorkOrderList" });

const route = useRoute();
const router = useRouter();
const loading = ref(false);
let reloadSeq = 0;
const list = ref<WorkOrderList>({ items: [], total: 0, page: 1, page_size: 20 });
const sources = ref<ConfigItem[]>([]);
const statuses = ref<ConfigItem[]>([]);
const regions = ["华北", "华中", "华东", "华南", "西北", "西南", "东北"];
const page = ref(1);
const pageSize = ref(20);
const allUsers = ref<any[]>([]);
const selectedRowKeys = ref<(string | number)[]>([]);

const filters = reactive<any>({ project_id: undefined, region: undefined, source_code: undefined, status: undefined, priority: undefined, person_name: undefined, search: undefined });

// 项目下拉只列当前列表里真实出现过的项目（后端按列表范围已去重 + 按区域收窄）
const projectOptions = computed(() => list.value.project_options || []);

const agentImport = reactive({
  visible: false,
  submitting: false,
  filename: "",
  html: "",
  result: null as AgentHtmlImportResult | null,
});
const agentHtmlInput = ref<HTMLInputElement | null>(null);

async function reload() {
  const seq = ++reloadSeq;
  loading.value = true;
  try {
    const params: any = { page: page.value, page_size: pageSize.value };
    for (const [k, v] of Object.entries(filters)) {
      if (v !== undefined && v !== "" && v !== null) params[k] = v;
    }
    const res = await listWorkOrders(params);
    if (seq !== reloadSeq) return;
    list.value = res;
    // 下拉来源已改为「列表内项目」：若已选项目在新结果里不存在（如切换区域后），清掉并重拉一次
    if (filters.project_id && !(res.project_options || []).some((p: any) => p.id === filters.project_id)) {
      filters.project_id = undefined;
      page.value = 1;
      return reload();
    }
    selectedRowKeys.value = [];
    if (res.items.length === 0 && res.total > 0 && page.value > 1) {
      page.value = 1;
      return reload();
    }
  } catch (e: any) {
    if (seq === reloadSeq) toast.error("工单列表加载失败：" + (e.message || "未知错误"));
  } finally {
    if (seq === reloadSeq) loading.value = false;
  }
}
function applyFilters() { page.value = 1; reload(); }
function onPageChange(p: any) { page.value = p.current; pageSize.value = p.pageSize; reload(); }
function resetFilters() { Object.keys(filters).forEach((k) => (filters[k] = undefined)); page.value = 1; reload(); }
function goDetail(row: any) { if (row && row.id) router.push(`/work-orders/${row.id}`); }

/* ---------- 批量操作 ---------- */
function selectedRows(): any[] {
  const set = new Set(selectedRowKeys.value.map(String));
  return list.value.items.filter((r) => set.has(String(r.id)));
}
async function batchDispatch() {
  const rows = selectedRows().filter((r) => r.status === "pending" || r.status === "approving");
  if (!rows.length) { toast.warning("请在「待派发/审批中」的工单里勾选"); return; }
  if (!(await confirmDialog(`确认批量派发 ${rows.length} 条工单？`))) return;
  let ok = 0, fail = 0;
  for (const r of rows) {
    try { await transitionWorkOrder(r.id, "dispatch"); ok++; } catch { fail++; }
  }
  toast.success(`批量派发完成：成功 ${ok}${fail ? "，失败 " + fail : ""}`);
  if (ok) reload();
}
async function batchReset() {
  const rows = selectedRows();
  if (!rows.length) { toast.warning("请先勾选工单"); return; }
  if (!(await confirmDialog(`确认把勾选的 ${rows.length} 条工单重置为「待派发」？`))) return;
  let ok = 0, fail = 0;
  for (const r of rows) {
    try { await transitionWorkOrder(r.id, "reset"); ok++; } catch { fail++; }
  }
  toast.success(`批量重置完成：成功 ${ok}${fail ? "，失败 " + fail : ""}`);
  if (ok) reload();
}

/* ---------- 导出 ---------- */
function exportCSV(rows: any[]) {
  if (!rows.length) { toast.warning("当前没有可导出的工单"); return; }
  const head = ["编号", "项目", "区域", "标题", "触发原因", "行动要求", "工单类型", "优先级", "责任人", "审批人", "计划开始", "截止", "状态"];
  const data = rows.map((w) => [w.code, w.project_name, w.region, w.title, w.reason, w.action,
    sourceLabel(w.source_code), w.priority, w.person_name, w.approver_name, w.planned_start_date,
    w.deadline, statusLabel(w.status)]);
  downloadCsv([head, ...data], `工单列表_${dayjs().format("YYYY-MM-DD")}.csv`);
}
function exportSelectedCSV() {
  const rows = selectedRows();
  if (!rows.length) { toast.warning("请先勾选工单"); return; }
  exportCSV(rows);
}

/* ---------- 导入 Agent HTML ---------- */
function openAgentHtmlImport() {
  agentImport.result = null;
  agentImport.filename = "";
  agentImport.visible = true;
}
function pickAgentHtmlFile() { agentHtmlInput.value?.click(); }
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
  if (!agentImport.html.trim()) { toast.warning("请先粘贴或选择 HTML 文件"); return; }
  agentImport.submitting = true;
  try {
    agentImport.result = await importAgentHtml(agentImport.html);
    await reload();
  } catch (e: any) {
    toast.error("导入失败：" + (e.message || "未知错误"));
  } finally {
    agentImport.submitting = false;
  }
}

onMounted(async () => {
  const q = route.query;
  if (q.status === "closed") { router.replace("/closed"); return; }
  filters.status = q.status || undefined;
  filters.source_code = q.source_code || undefined;
  filters.priority = q.priority || undefined;
  filters.project_id = q.project_id ? Number(q.project_id) : undefined;
  filters.region = q.region || undefined;
  const [s, st, u] = await Promise.all([getWoTypes(), getStatuses(), getUsersAll()]);
  sources.value = s;
  statuses.value = st.filter((x: any) => x.code !== "closed");
  allUsers.value = u;
  await reload();
});

watch(
  () => route.query,
  (q) => {
    if (q.status === "closed") { router.replace("/closed"); return; }
    if (q.status === undefined && q.source_code === undefined && q.priority === undefined && q.project_id === undefined && q.region === undefined) return;
    filters.status = q.status || undefined;
    filters.source_code = q.source_code || undefined;
    filters.priority = q.priority || undefined;
    filters.project_id = q.project_id ? Number(q.project_id) : undefined;
    filters.region = q.region || undefined;
    page.value = 1;
    reload();
  },
);
</script>

<style scoped>
.wo-list .page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; flex-wrap: wrap; gap: 12px; }
.page-header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { color: var(--muted); font-size: 12px; margin-top: 4px; }
.filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
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

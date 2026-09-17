<template>
  <div class="wo-create">
    <div class="header">
      <div><h1>新建工单</h1><div class="meta">手动创建 · 从 Excel 导入</div></div>
    </div>

    <div class="tabs">
      <button type="button" class="tab" :class="{ active: tab === 'manual' }" @click="tab = 'manual'">手动填写</button>
      <button type="button" class="tab" :class="{ active: tab === 'excel' }" @click="tab = 'excel'">从 Excel 导入</button>
    </div>

    <!-- 手动填写 -->
    <div v-if="tab === 'manual' && configLoading" class="card form-loading">正在加载项目和人员…</div>
    <PageError v-else-if="tab === 'manual' && configError" title="表单配置加载失败" :message="configError" @action="loadConfig" />
    <div v-else v-show="tab === 'manual'" class="card">
      <div class="form-row">
        <div class="form-group">
          <label><span class="req">*</span>项目名称</label>
          <t-select v-model="form.project_id" placeholder="输入项目名称 / 编码搜索" filterable clearable :options="projectOptions" @change="onProjectChange" />
        </div>
        <div class="form-group">
          <label><span class="req">*</span>工单类型</label>
          <t-select v-model="form.type_id" placeholder="选择工单类型" :options="typeOptions" />
        </div>
        <div class="form-group">
          <label><span class="req">*</span>来源</label>
          <t-select v-model="form.source_code" placeholder="选择来源" :options="sourceOptions" />
        </div>
        <div class="form-group">
          <label><span class="req">*</span>优先级</label>
          <t-select v-model="form.priority" :options="priorityOptions" @change="autoDeadline" />
        </div>
        <div class="form-group form-full">
          <label><span class="req">*</span>标题</label>
          <t-input v-model="form.title" placeholder="一句话概括工单内容" maxlength="120" />
        </div>
        <div class="form-group form-full">
          <label>触发原因</label>
          <t-textarea v-model="form.reason" placeholder="偏差描述或触发条件" :autosize="{ minRows: 3, maxRows: 6 }" />
        </div>
        <div class="form-group form-full">
          <label><span class="req">*</span>行动要求</label>
          <t-textarea v-model="form.action" placeholder="具体要做什么、达到什么标准" :autosize="{ minRows: 3, maxRows: 6 }" />
        </div>
        <div class="form-group">
          <label><span class="req">*</span>责任人</label>
          <SearchableSelect v-model="form.person_id" :options="allUsers" placeholder="搜索姓名…" />
        </div>
        <div class="form-group">
          <label><span class="req">*</span>审批人</label>
          <SearchableSelect v-model="form.approver_id" :options="allUsers" placeholder="搜索姓名…" />
        </div>
        <div class="form-group">
          <label>计划开始</label>
          <t-date-picker v-model="form.planned_start_date" format="YYYY-MM-DD" value-type="YYYY-MM-DD" clearable />
        </div>
        <div class="form-group">
          <label>区域</label>
          <t-select v-model="form.region" placeholder="选择区域" clearable :options="regionOptions" />
        </div>
        <div class="form-group">
          <label><span class="req">*</span>截止日期</label>
          <t-date-picker v-model="form.deadline" format="YYYY-MM-DD" value-type="YYYY-MM-DD" />
        </div>
      </div>
      <div class="form-actions">
        <t-button variant="outline" @click="router.push('/work-orders')">取消</t-button>
        <t-button theme="primary" :loading="submitting" @click="submitManual">提交 → 发起钉钉OA审批</t-button>
      </div>
    </div>

    <!-- 从 Excel 导入 -->
    <div v-show="tab === 'excel'" class="card">
      <div class="card-hd">
        <h3>📊 从 Excel/CSV 导入</h3>
        <span class="count">支持列：标题/项目/责任人/截止日期/类型/描述/行动要求</span>
        <t-button variant="outline" size="small" @click="onDownloadTemplate">下载模板</t-button>
      </div>
      <div class="upload-area" @dragover.prevent @drop.prevent="onDrop">
        <input type="file" accept=".csv,.xlsx,.xls" @change="onFilePick" ref="fileInput" hidden />

        <!-- 预览确认 -->
        <div v-if="preview" class="preview-box">
          <div class="preview-hd">
            <span>解析出 <b>{{ preview.total }}</b> 行，<b class="ok-text">{{ preview.ok_count }}</b> 行可录入，<b class="err-text">{{ preview.err_count }}</b> 行有问题（默认不勾选）</span>
            <span class="preview-actions">
              <t-button size="small" theme="primary" :loading="confirming" :disabled="!selectedRows.length" @click="onConfirmImport">
                确认录入 {{ selectedRows.length }} 条
              </t-button>
              <t-button size="small" variant="outline" @click="resetImport">重新上传</t-button>
            </span>
          </div>
          <t-table
            row-key="line"
            :data="preview.rows"
            :columns="previewColumns"
            v-model:selected-row-keys="selectedRowKeys"
            @select-change="onSelectChange"
            size="small"
            max-height="340"
            cell-empty-content="—"
          />
        </div>

        <!-- 未上传 -->
        <div v-else-if="!tableResult" @click="fileInput?.click()" class="upload-prompt">
          📁 点击选择文件，或拖拽到此处（先预览、确认后再录入）
        </div>

        <!-- 导入结果 -->
        <div v-else class="upload-result">
          <div v-if="tableResult.created" class="ok">✅ 成功创建 {{ tableResult.created }} 条工单</div>
          <div v-if="tableResult.errors.length" class="err">⚠️ {{ tableResult.errors.length }} 行出错：{{ tableResult.errors.join('；') }}</div>
          <t-button variant="outline" size="small" @click="resetImport">重新上传</t-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { toast } from "@/utils/feedback";
import { computed, h, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { createWorkOrder } from "@/api/workorders";
import { getProjectsAll, getSources, getWoTypes, getUsersAll, getPersonProjectMap, type ConfigItem } from "@/api/config";
import { importTablePreview, importTableConfirm, downloadTemplate, type ImportPreviewResult, type ImportPreviewRow } from "@/api/imports";
import SearchableSelect from "@/components/SearchableSelect.vue";
import PageError from "@/components/PageError.vue";
import { useConfigStore } from "@/stores/config";
import dayjs from "dayjs";

const router = useRouter();

const REGIONS = ["华北", "华中", "华东", "华南", "西北", "西南", "东北"];
const submitting = ref(false);
const configLoading = ref(true);
const configError = ref("");
const tab = ref<"manual" | "excel">("manual");

const projects = ref<any[]>([]);
const sources = ref<ConfigItem[]>([]);
const woTypes = ref<ConfigItem[]>([]);
const allUsers = ref<any[]>([]);
const personMap = ref<any[]>([]);
// 项目下拉：与项目管理页一致——按编码排序，展示「编码 · 名称」，支持按名称/编码模糊搜索
const projectOptions = computed(() =>
  projects.value.map((p) => ({ value: p.id, label: `${p.code} · ${p.name}` }))
);
const typeOptions = computed(() => woTypes.value.map((t) => ({ value: t.id, label: t.name })));
const sourceOptions = computed(() => sources.value.map((s) => ({ value: s.code, label: s.name })));
const priorityOptions = [
  { value: "P1", label: "P1 紧急" },
  { value: "P2", label: "P2 普通" },
  { value: "P3", label: "P3 低优先" },
];
const regionOptions = REGIONS.map((r) => ({ value: r, label: r }));

const form = reactive({
  project_id: undefined as number | undefined,
  type_id: undefined as number | undefined,
  source_code: "manual",
  priority: "P2",
  title: "", reason: "", action: "",
  person_id: undefined as number | undefined,
  approver_id: undefined as number | undefined,
  planned_start_date: "",
  deadline: "",
  region: "",
});

async function onProjectChange() {
  form.person_id = undefined;
  const project = projects.value.find((p) => p.id === form.project_id);
  form.region = REGIONS.includes(project?.region) ? project.region : "";
  if (!project) return;
  const entry = personMap.value.find((p) => p.project_id === form.project_id);
  if (entry) {
    const def = entry.persons.find((pp: any) => pp.is_default);
    form.person_id = def?.id ?? entry.persons[0]?.id;
  }
}

function autoDeadline() {
  const days = useConfigStore().slaDays(form.priority, { P1: 1, P2: 3, P3: 7 }[form.priority] ?? 7);
  const d = new Date(); d.setDate(d.getDate() + days);
  form.deadline = dayjs(d).format("YYYY-MM-DD");
}

async function submitManual() {
  if (submitting.value) return;
  const missing = [
    !form.project_id && "项目名称",
    !form.type_id && "工单类型",
    !form.source_code && "来源",
    !form.priority && "优先级",
    !form.title.trim() && "标题",
    !form.action.trim() && "行动要求",
    !form.person_id && "责任人",
    !form.approver_id && "审批人",
    !form.deadline && "截止日期",
  ].filter(Boolean);
  if (missing.length) { toast.warning(`请填写必填项：${missing.join("、")}`); return; }
  submitting.value = true;
  try {
    await createWorkOrder({
      title: form.title, reason: form.reason || undefined, action: form.action,
      project_id: form.project_id, type_id: form.type_id, source_code: form.source_code,
      priority: form.priority, person_id: form.person_id, approver_id: form.approver_id,
      region: form.region || undefined,
      planned_start_date: form.planned_start_date || undefined,
      deadline: form.deadline,
    });
    router.push("/work-orders");
  } catch (e: any) { toast.error("提交失败：" + e.message); }
  finally { submitting.value = false; }
}

async function loadConfig() {
  configLoading.value = true;
  configError.value = "";
  try {
    const [p, s, t, u, pm] = await Promise.all([getProjectsAll(), getSources(), getWoTypes(), getUsersAll(), getPersonProjectMap()]);
    // 编码数字序，避免下拉按拼音散乱；项目和类型由使用者明确选择。
    projects.value = [...p].sort((a, b) => String(a.code || "").localeCompare(String(b.code || ""), undefined, { numeric: true }));
    sources.value = s; woTypes.value = t; allUsers.value = u; personMap.value = pm;
    autoDeadline();
  } catch (e: any) {
    configError.value = e.message || "请稍后重试";
  } finally {
    configLoading.value = false;
  }
}
onMounted(loadConfig);

// Excel 导入：上传 → 预览勾选 → 确认录入
const tableResult = ref<{ created: number; errors: string[]; total: number } | null>(null);
const preview = ref<ImportPreviewResult | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const selectedRowKeys = ref<(string | number)[]>([]);
const selectedRows = ref<ImportPreviewRow[]>([]);
const confirming = ref(false);

const previewColumns = [
  { colKey: "line", title: "行", width: 56 },
  { colKey: "title", title: "标题", ellipsis: true },
  {
    colKey: "project_label", title: "项目", ellipsis: true,
    cell: (_: any, { row }: any) =>
      row.project_label
        ? h("span", row.project_label)
        : h("span", { style: { color: "#d54941" } }, row.project_name ? "未匹配" : "缺项目"),
  },
  {
    colKey: "person_name", title: "责任人", width: 90, ellipsis: true,
    cell: (_: any, { row }: any) =>
      row.person_name
        ? h("span", row.person_name)
        : h("span", { style: { color: row.person_ok ? "#999" : "#d54941" } }, row.person_ok ? "—" : "未匹配"),
  },
  { colKey: "type_name", title: "类型", width: 90, ellipsis: true },
  { colKey: "priority", title: "优先级", width: 76 },
  { colKey: "deadline", title: "截止", width: 104 },
  {
    colKey: "error", title: "问题", ellipsis: true,
    cell: (_: any, { row }: any) =>
      row.error ? h("span", { style: { color: "#d54941" } }, row.error) : "—",
  },
];

function onFilePick(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (f) doPreview(f);
}
function onDrop(e: DragEvent) {
  e.preventDefault();
  const f = e.dataTransfer?.files?.[0];
  if (f) doPreview(f);
}
async function doPreview(file: File) {
  preview.value = null;
  tableResult.value = null;
  try {
    const res = await importTablePreview(file);
    preview.value = res;
    // 默认勾选所有可录入（ok）的行
    selectedRowKeys.value = res.rows.filter((r) => r.ok).map((r) => r.line);
    selectedRows.value = res.rows.filter((r) => r.ok);
  } catch (e: any) {
    toast.error("解析失败：" + e.message);
  }
}
function onSelectChange(keys: (string | number)[], ctx: any) {
  selectedRowKeys.value = keys;
  selectedRows.value = (ctx?.selectedRowData || []).slice();
}
async function onConfirmImport() {
  if (!selectedRows.value.length) { toast.warning("请先勾选要录入的行"); return; }
  confirming.value = true;
  try {
    tableResult.value = await importTableConfirm(selectedRows.value.map((r) => r.raw));
    preview.value = null;
    toast.success(`已录入 ${tableResult.value.created} 条`);
  } catch (e: any) {
    toast.error("确认录入失败：" + e.message);
  } finally {
    confirming.value = false;
  }
}
function resetImport() {
  preview.value = null;
  tableResult.value = null;
  selectedRowKeys.value = [];
  selectedRows.value = [];
  if (fileInput.value) fileInput.value.value = "";
}
async function onDownloadTemplate() {
  try { await downloadTemplate(); toast.success("模板已下载，请按表头填写后上传"); }
  catch (e: any) { toast.error("下载失败：" + e.message); }
}
</script>

<style scoped>
.wo-create .header { margin-bottom: 20px; }
.header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { font-size: 12px; color: var(--muted); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 20px; }
.tab { padding: 10px 20px; cursor: pointer; font: inherit; font-weight: 600; color: var(--muted); background: transparent; border: 0; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tab.active { color: var(--brand); border-bottom-color: var(--brand); }
.tab:hover { color: var(--brand); background: var(--brand-light); }
.tab:focus-visible { outline: 2px solid var(--brand); outline-offset: -2px; }
.card { background: var(--card); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow); }
.form-loading { color: var(--muted); text-align: center; padding: 48px 20px; }
.card-hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.card-hd h3 { font-size: 15px; font-weight: 700; }
.count { font-size: 12px; color: var(--muted); }
.upload-area { min-height: 160px; border: 2px dashed #d1d5db; border-radius: 10px; display: flex; align-items: center; justify-content: center; cursor: pointer; }
.upload-area:hover { border-color: var(--brand); background: #f8fafc; }
.upload-prompt { color: var(--muted); font-size: 14px; }
.upload-result { text-align: center; padding: 20px; }
.ok { color: var(--green); font-weight: 600; margin-bottom: 8px; }
.err { color: var(--red); font-size: 12px; margin-bottom: 8px; }
.preview-box { width: 100%; padding: 12px; text-align: left; cursor: default; }
.preview-hd { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 10px; font-size: 13px; color: #4b5563; flex-wrap: wrap; }
.preview-actions { display: flex; gap: 8px; }
.ok-text { color: var(--green); }
.err-text { color: var(--red); }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.form-full { grid-column: 1 / -1; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; font-size: 12px; font-weight: 600; color: #4b5563; margin-bottom: 4px; }
.form-group .req { color: var(--red); }
.form-group :deep(.t-input), .form-group :deep(.t-textarea), .form-group :deep(.t-date-picker) { width: 100%; }
.form-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
@media (max-width: 700px) { .form-row { grid-template-columns: 1fr; } }
</style>

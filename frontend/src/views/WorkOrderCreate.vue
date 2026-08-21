<template>
  <div class="wo-create">
    <div class="header">
      <div><h1>新建工单 <span style="color:red;font-size:12px">v2</span></h1><div class="meta">手动创建 · 从 Excel 导入</div></div>
    </div>

    <div class="tabs">
      <div class="tab" :class="{ active: tab === 'manual' }" @click="tab = 'manual'">✏️ 手动填写</div>
      <div class="tab" :class="{ active: tab === 'excel' }" @click="tab = 'excel'">📊 从 Excel 导入</div>
    </div>

    <!-- 手动填写 -->
    <div v-show="tab === 'manual'" class="card">
      <div class="form-row">
        <div class="form-group">
          <label><span class="req">*</span>项目名称</label>
          <select v-model="form.project_id" @change="onProjectChange">
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </div>
        <div class="form-group">
          <label><span class="req">*</span>工单类型</label>
          <select v-model="form.type_id">
            <option v-for="t in woTypes" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </div>
        <div class="form-group">
          <label><span class="req">*</span>来源</label>
          <select v-model="form.source_code">
            <option v-for="s in sources" :key="s.code" :value="s.code">{{ s.name }}</option>
          </select>
        </div>
        <div class="form-group">
          <label><span class="req">*</span>优先级</label>
          <select v-model="form.priority">
            <option value="P1">P1 紧急</option>
            <option value="P2">P2 普通</option>
            <option value="P3">P3 低优先</option>
          </select>
        </div>
        <div class="form-group form-full">
          <label><span class="req">*</span>标题</label>
          <input v-model="form.title" placeholder="一句话概括工单内容" />
        </div>
        <div class="form-group form-full">
          <label>触发原因</label>
          <textarea v-model="form.reason" placeholder="偏差描述或触发条件"></textarea>
        </div>
        <div class="form-group form-full">
          <label><span class="req">*</span>行动要求</label>
          <textarea v-model="form.action" placeholder="具体要做什么、达到什么标准"></textarea>
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
          <input type="date" v-model="form.planned_start_date" />
        </div>
        <div class="form-group">
          <label>区域</label>
          <select v-model="form.region">
            <option value="">—</option>
            <option v-for="r in REGIONS" :key="r" :value="r">{{ r }}</option>
          </select>
        </div>
        <div class="form-group">
          <label><span class="req">*</span>截止日期</label>
          <input type="date" v-model="form.deadline" />
        </div>
      </div>
      <div class="form-actions">
        <button class="btn btn-out" @click="router.push('/work-orders')">取消</button>
        <button class="btn btn-pri" @click="submitManual" :disabled="submitting">
          {{ submitting ? "提交中…" : "提交 → 发起钉钉OA审批" }}
        </button>
      </div>
    </div>

    <!-- 从 Excel 导入 -->
    <div v-show="tab === 'excel'" class="card">
      <div class="card-hd"><h3>📊 从 Excel/CSV 导入</h3><span class="count">支持列：标题/项目/责任人/截止日期/类型/描述/行动</span></div>
      <div class="upload-area" @dragover.prevent @drop.prevent="onDrop">
        <input type="file" accept=".csv,.xlsx,.xls" @change="onFilePick" ref="fileInput" hidden />
        <div v-if="!tableResult" @click="fileInput?.click()" class="upload-prompt">
          📁 点击选择文件，或拖拽到此处
        </div>
        <div v-else class="upload-result">
          <div v-if="tableResult.created" class="ok">✅ 成功创建 {{ tableResult.created }} 条工单</div>
          <div v-if="tableResult.errors.length" class="err">⚠️ {{ tableResult.errors.length }} 行出错：{{ tableResult.errors.join('；') }}</div>
          <button class="btn btn-out btn-sm" @click="tableResult = null">重新上传</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { createWorkOrder } from "@/api/workorders";
import { getProjectsAll, getSources, getWoTypes, getUsersAll, getPersonProjectMap, type ConfigItem } from "@/api/config";
import { importTable } from "@/api/imports";
import SearchableSelect from "@/components/SearchableSelect.vue";

const router = useRouter();

const REGIONS = ["华北", "华中", "华东", "华南", "西北", "西南", "东北"];
const submitting = ref(false);
const tab = ref<"manual" | "excel">("manual");

const projects = ref<any[]>([]);
const sources = ref<ConfigItem[]>([]);
const woTypes = ref<ConfigItem[]>([]);
const allUsers = ref<any[]>([]);
const personMap = ref<any[]>([]);

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
  const entry = personMap.value.find((p) => p.project_id === form.project_id);
  if (entry) {
    const def = entry.persons.find((pp: any) => pp.is_default);
    form.person_id = def?.id ?? entry.persons[0]?.id;
  }
}

function autoDeadline() {
  const days = { P1: 1, P2: 3, P3: 7 }[form.priority] ?? 7;
  const d = new Date(); d.setDate(d.getDate() + days);
  form.deadline = d.toISOString().slice(0, 10);
}

async function submitManual() {
  if (!form.title || !form.action || !form.deadline || !form.project_id) {
    alert("请填写必填字段"); return;
  }
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
  } catch (e: any) { alert("提交失败：" + e.message); }
  finally { submitting.value = false; }
}

onMounted(async () => {
  const [p, s, t, u, pm] = await Promise.all([getProjectsAll(), getSources(), getWoTypes(), getUsersAll(), getPersonProjectMap()]);
  projects.value = p; sources.value = s; woTypes.value = t; allUsers.value = u; personMap.value = pm;
  if (p.length) form.project_id = p[0].id;
  if (t.length) form.type_id = t[0].id;
  onProjectChange(); autoDeadline();
});

// Excel 导入
const tableResult = ref<{ created: number; errors: string[]; total: number } | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

function onFilePick(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (f) doUpload(f);
}
function onDrop(e: DragEvent) {
  e.preventDefault();
  const f = e.dataTransfer?.files?.[0];
  if (f) doUpload(f);
}
async function doUpload(file: File) {
  try { tableResult.value = await importTable(file); }
  catch (e: any) { alert("导入失败：" + e.message); }
}
</script>

<style scoped>
.wo-create .header { margin-bottom: 20px; }
.header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { font-size: 12px; color: var(--muted); }
.tabs { display: flex; gap: 0; border-bottom: 2px solid var(--border); margin-bottom: 20px; }
.tab { padding: 10px 20px; cursor: pointer; font-size: 13px; font-weight: 600; color: var(--muted); border-bottom: 2px solid transparent; margin-bottom: -2px; }
.tab.active { color: var(--brand); border-bottom-color: var(--brand); }
.card { background: var(--card); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow); }
.card-hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.card-hd h3 { font-size: 15px; font-weight: 700; }
.count { font-size: 12px; color: var(--muted); }
.upload-area { min-height: 160px; border: 2px dashed #d1d5db; border-radius: 10px; display: flex; align-items: center; justify-content: center; cursor: pointer; }
.upload-area:hover { border-color: var(--brand); background: #f8fafc; }
.upload-prompt { color: var(--muted); font-size: 14px; }
.upload-result { text-align: center; padding: 20px; }
.ok { color: var(--green); font-weight: 600; margin-bottom: 8px; }
.err { color: var(--red); font-size: 12px; margin-bottom: 8px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.form-full { grid-column: 1 / -1; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; font-size: 12px; font-weight: 600; color: #4b5563; margin-bottom: 4px; }
.form-group .req { color: var(--red); }
.form-group input, .form-group select, .form-group textarea { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; font-family: inherit; }
.form-group textarea { resize: vertical; min-height: 70px; }
.form-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.btn { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-pri { background: var(--brand); color: #fff; }
.btn-pri:hover { background: var(--brand-dark); }
.btn-pri:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-out { background: #fff; color: #4b5563; border: 1px solid var(--border); }
.btn-out:hover { background: #f9fafb; }
@media (max-width: 700px) { .form-row { grid-template-columns: 1fr; } }
</style>
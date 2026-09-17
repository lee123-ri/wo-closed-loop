<template>
  <div class="config-page">
    <div class="header"><div><h1>规则配置</h1><div class="meta">全部可配置 · 改完即时生效</div></div></div>
    <PageError v-if="loadError" title="规则配置加载失败" :message="loadError" @action="retryLoad" />
    <template v-else>

    <!-- 工单类型 -->
    <div class="card">
      <div class="card-hd"><h3>📚 工单类型</h3><button class="btn btn-pri btn-sm" @click="openType()">＋ 新增</button></div>
      <t-table :data="woTypes" :columns="typeColumns" row-key="id" size="small" cell-empty-content="—" hover>
        <template #type_code="{ row }"><code>{{ row.type_code }}</code></template>
        <template #name="{ row }"><b @dblclick="editType(row)">{{ row.name }}</b></template>
        <template #desc="{ row }"><span class="desc">{{ row.desc || '—' }}</span></template>
        <template #approver="{ row }">{{ userName(row.default_approver_id) }}</template>
        <template #priority="{ row }"><t-tag :theme="priorityTheme(row.default_priority)" size="small">{{ priorityLabel(row.default_priority) }}</t-tag></template>
        <template #action="{ row }">
          <t-space :size="4">
            <t-button size="small" variant="outline" @click="editType(row)">编辑</t-button>
            <t-button size="small" variant="outline" theme="danger" @click="delType(row.id)">删除</t-button>
          </t-space>
        </template>
      </t-table>
    </div>

    <!-- 来源 / 状态 -->
    <div class="card">
      <div class="card-hd"><h3>🏷️ 来源与状态</h3><button class="btn btn-pri btn-sm" @click="openDef()">＋ 新增</button></div>
      <div class="grid2">
        <div><div class="sub-hd">来源</div>
          <div class="chip-list"><span v-for="s in sources" :key="s.id" class="chip" @dblclick="editDef(s)"><span class="dot" :style="{background: s.color}"></span>{{ s.name }}<span class="chip-del" @click="delDef(s.id)">×</span></span></div>
        </div>
        <div><div class="sub-hd">状态</div>
          <div class="chip-list"><span v-for="s in statuses" :key="s.id" class="chip" @dblclick="editDef(s)"><span class="dot" :style="{background: s.color}"></span>{{ s.name }}<span class="chip-del" @click="delDef(s.id)">×</span></span></div>
        </div>
      </div>
    </div>

    <!-- 异常指标大类 -->
    <div class="card">
      <div class="card-hd"><h3>🧭 异常指标大类</h3><span class="count">监视告警细分 · 每类默认责任人</span></div>
      <div class="region-pmo-grid">
        <div v-for="c in anomalyCategories" :key="c.id" class="region-pmo-row">
          <span class="region-label"><span class="dot" style="display:inline-block" :style="{ background: c.color }"></span>{{ c.name }}<code class="role-code">{{ c.code }}</code></span>
          <SearchableSelect
            :model-value="categoryUserId(c)"
            :options="allUsers"
            placeholder="默认责任人…"
            class="region-pmo-select"
            @update:model-value="(v: number | undefined) => onCategoryPersonChange(c, v)"
          />
        </div>
      </div>
    </div>

    <!-- 优先级规则 -->
    <div class="card">
      <div class="card-hd"><h3>🎯 优先级判定规则</h3><button class="btn btn-pri btn-sm" @click="openPriority()">＋ 新增</button></div>
      <t-table :data="priorityRules" :columns="ruleColumns" row-key="id" size="small" cell-empty-content="—" hover>
        <template #idx="{ rowIndex }">{{ rowIndex + 1 }}</template>
        <template #pattern="{ row }"><code @dblclick="editPriority(row)">{{ row.pattern }}</code></template>
        <template #label="{ row }"><span @dblclick="editPriority(row)">{{ row.label }}</span></template>
        <template #priority="{ row }"><t-tag :theme="priorityTheme(row.priority)" size="small">{{ priorityLabel(row.priority) }}</t-tag></template>
        <template #enabled="{ row }"><span class="toggle" :class="{ on: row.enabled }" @click="togglePriority(row)">{{ row.enabled ? '开' : '关' }}</span></template>
        <template #action="{ row }">
          <t-space :size="4">
            <t-button size="small" variant="outline" @click="editPriority(row)">编辑</t-button>
            <t-button size="small" variant="outline" theme="danger" @click="delPriority(row.id)">删除</t-button>
          </t-space>
        </template>
      </t-table>
    </div>

    <!-- SLA -->
    <div class="card">
      <div class="card-hd"><h3>⏱ SLA 定义</h3></div>
      <t-table :data="slaList" :columns="slaColumns" row-key="id" size="small" cell-empty-content="—">
        <template #priority="{ row }"><t-tag :theme="priorityTheme(row.priority)" size="small">{{ priorityLabel(row.priority) }}</t-tag></template>
        <template #deadline_days="{ row }"><input type="number" v-model.number="row.deadline_days" class="inline-inp" /></template>
        <template #warn_before_hours="{ row }"><input type="number" v-model.number="row.warn_before_hours" class="inline-inp" /></template>
        <template #escalate_hours="{ row }"><input type="number" v-model.number="row.escalate_hours" class="inline-inp" /></template>
        <template #action="{ row }"><t-button size="small" theme="primary" :loading="writing" @click="saveSla(row)">保存</t-button></template>
      </t-table>
    </div>

    <!-- 区域PMO -->
    <div class="card">
      <div class="card-hd"><h3>📍 区域PMO配置</h3><span class="count">异常指标工单默认责任人</span></div>
      <div class="region-pmo-grid">
        <div v-for="r in REGIONS" :key="r" class="region-pmo-row">
          <span class="region-label">{{ r }}</span>
          <SearchableSelect
            :model-value="regionPMO[r]?.user_id"
            :options="allUsers"
            placeholder="输入姓名搜索…"
            class="region-pmo-select"
            @update:model-value="(v: number | undefined) => onRegionPMOChange(r, v)"
          />
        </div>
      </div>
    </div>

    <!-- 角色人员配置 -->
    <div class="card">
      <div class="card-hd"><h3>👤 角色人员配置</h3><span class="count">审批流按角色引用，人名在此配置</span></div>
      <div class="region-pmo-grid">
        <div v-for="r in roleAssignments" :key="r.role_code" class="region-pmo-row">
          <span class="region-label"><b>{{ r.role_name }}</b><code class="role-code">{{ r.role_code }}</code></span>
          <SearchableSelect
            :model-value="r.user_id"
            :options="allUsers"
            placeholder="输入姓名搜索…"
            class="region-pmo-select"
            @update:model-value="(v: number | undefined) => onRoleChange(r.role_code, v)"
          />
        </div>
      </div>
    </div>

    <!-- 审批流 -->
    <div class="card">
      <div class="card-hd"><h3>🔄 审批流</h3><span class="count">双击节点编辑</span></div>
      <div class="flow-grid">
        <div v-for="f in approvalFlows" :key="f.id" class="flow-card" :class="flowClass(f.priority)">
          <div class="flow-hd"><h4>{{ emoji(f.priority) }} {{ f.name }}</h4></div>
          <div class="flow-nodes">
            <div v-for="(n,i) in f.nodes" :key="i" class="flow-node" @dblclick="editNode(f,i)">
              <div class="node-title">{{ n.title }}</div><div class="node-sub">{{ n.sub }}</div>
              <span class="node-type" :class="n.type">{{ nodeTypeLabel(n.type) }}</span>
              <div v-if="n.timeout_days" class="node-timeout">⏱ {{ n.timeout_days }}天</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 工单类型编辑弹窗 -->
    <t-dialog v-model:visible="typeModal.open" :header="(typeModal.editing ? '编辑' : '新增') + '工单类型'" width="640" :footer="false">
      <div class="modal-body-scroll">
          <!-- 基本信息 -->
          <h4 class="modal-section-title">基本信息</h4>
          <div class="form-row">
            <div class="form-group"><label>编码</label><input v-model="typeModal.type_code" :disabled="!!typeModal.editing" /></div>
            <div class="form-group"><label>名称</label><input v-model="typeModal.name" /></div>
          </div>
          <div class="form-group"><label>说明</label><input v-model="typeModal.desc" /></div>
          <div class="form-row">
            <div class="form-group"><label>审批人</label><select v-model="typeModal.default_approver_id"><option :value="undefined">无</option><option v-for="u in approvers" :key="u.id" :value="u.id">{{ u.name }}</option></select></div>
            <div class="form-group"><label>优先级</label><select v-model="typeModal.default_priority"><option value="P1">P1</option><option value="P2">P2</option><option value="P3">P3</option></select></div>
          </div>

          <!-- SOP 知识库 -->
          <h4 class="modal-section-title">📋 SOP 知识库</h4>
          <div class="form-group"><label>指引编号</label><input v-model="typeModal.guidance_ref" placeholder="如 YWSYB-GLZY-012" /></div>
          <div class="form-group"><label>目的</label><textarea v-model="typeModal.sop_purpose" rows="2" placeholder="规范XX的全流程管控"></textarea></div>
          <div class="form-group"><label>流程</label><textarea v-model="typeModal.sop_scope" rows="2" placeholder="描述工作流程和环节"></textarea></div>
          <div class="form-group">
            <label>标准步骤（JSON 格式）</label>
            <textarea v-model="typeModal.sop_steps" rows="6" placeholder='[{"step":1,"action":"...","standard":"...","role":"..."}]'></textarea>
            <span class="form-hint">JSON 数组，每项含 step/action/standard/role</span>
          </div>
          <div class="form-group"><label>验收标准</label><textarea v-model="typeModal.sop_acceptance" rows="2" placeholder="描述验收标准"></textarea></div>
          <div class="form-group">
            <label>升级规则（JSON 格式）</label>
            <textarea v-model="typeModal.sop_escalation" rows="3" placeholder='{"timeout_hours":24,"action":"升级至XX","target":"XX"}'></textarea>
            <span class="form-hint">JSON 对象，含 timeout_hours/action/target</span>
          </div>
          <div class="form-group">
            <label>关联指引（JSON 格式）</label>
            <textarea v-model="typeModal.sop_related_guidance" rows="3" placeholder='[{"ref":"YWSYB-GLZY-001","title":"XX指引"}]'></textarea>
            <span class="form-hint">JSON 数组，每项含 ref/title</span>
          </div>
          <div class="form-group">
            <label class="checkbox-label"><input type="checkbox" v-model="typeModal.sop_backfill_required" /> 要求回填</label>
          </div>
        </div>
        <div class="modal-actions"><t-button variant="outline" @click="typeModal.open = false">取消</t-button><t-button theme="primary" :loading="writing" @click="saveType">保存</t-button></div>
    </t-dialog>

    <!-- 通用弹窗 -->
    <t-dialog v-model:visible="modal.open" :header="modalTitle" width="420" :footer="false">
        <template v-if="modal.type === 'def'">
          <div class="form-group"><label>类别</label><select v-model="modal.category"><option value="source">来源</option><option value="status">状态</option></select></div>
          <div class="form-group"><label>编码</label><input v-model="modal.code" /></div>
          <div class="form-group"><label>名称</label><input v-model="modal.name" /></div>
          <div class="form-group"><label>颜色</label><input v-model="modal.color" /></div>
        </template>
        <template v-if="modal.type === 'priority'">
          <div class="form-group"><label>正则</label><input v-model="modal.pattern" /></div>
          <div class="form-group"><label>说明</label><input v-model="modal.label" /></div>
          <div class="form-group"><label>优先级</label><select v-model="modal.priority"><option value="P1">P1</option><option value="P2">P2</option><option value="P3">P3</option></select></div>
        </template>
        <div class="modal-actions"><t-button variant="outline" @click="modal.open = false">取消</t-button><t-button theme="primary" :loading="writing" @click="confirmModal">保存</t-button></div>
    </t-dialog>

    <!-- 审批流节点弹窗 -->
    <t-dialog v-model:visible="nodeModal.open" header="编辑审批节点" width="420" :footer="false">
        <div class="form-group"><label>名称</label><input v-model="nodeModal.title" /></div>
        <div class="form-group"><label>说明</label><input v-model="nodeModal.sub" /></div>
        <div class="form-group"><label>角色</label><input v-model="nodeModal.role" /></div>
        <div class="form-group"><label>超时(天)</label><input type="number" v-model.number="nodeModal.timeout_days" /></div>
        <div class="modal-actions"><t-button variant="outline" @click="nodeModal.open = false">取消</t-button><t-button theme="primary" :loading="writing" @click="saveNode">保存</t-button></div>
    </t-dialog>
    </template>
  </div>
</template>

<script setup lang="ts">
import { toast, confirmDialog } from "@/utils/feedback";
import { computed, onMounted, reactive, ref } from "vue";
import { getSources, getStatuses, getProjects, getUsers, getUsersAll, getPriorityRules, getSla, getApprovalFlows, getRegionPMOs, getRoleAssignments, getAnomalyCategories } from "@/api/config";
import * as CC from "@/api/config-crud";
import { setRegionPMO, deleteRegionPMO, updateRoleAssignment, updateAnomalyCategory } from "@/api/config";
import SearchableSelect from "@/components/SearchableSelect.vue";
import PageError from "@/components/PageError.vue";
import { priorityLabel, priorityTheme } from "@/utils/wo-display";

const REGIONS = ["华北", "华中", "华东", "华南", "西北", "西南", "东北"];
const sources = ref<any[]>([]);
const statuses = ref<any[]>([]);
const users = ref<any[]>([]);
const allUsers = ref<any[]>([]);
const approvers = computed(() => users.value.filter((u) => u.role === "approver" || u.role === "admin"));
const woTypes = ref<any[]>([]);
const priorityRules = ref<any[]>([]);
const slaList = ref<any[]>([]);
const approvalFlows = ref<any[]>([]);
const regionPMO = reactive<Record<string, any>>({});
const roleAssignments = ref<any[]>([]);
const anomalyCategories = ref<any[]>([]);
const writing = ref(false);
const loadError = ref("");

async function writeConfig(action: () => Promise<unknown>): Promise<boolean> {
  if (writing.value) return false;
  writing.value = true;
  try {
    await action();
  } catch (e: any) {
    toast.error("操作失败：" + (e.message || "未知错误"));
    return false;
  } finally {
    writing.value = false;
  }
  try { await loadAll(); }
  catch (e: any) { toast.warning("操作已保存，但刷新失败：" + (e.message || "未知错误")); }
  return true;
}

const typeColumns: any[] = [
  { colKey: "type_code", title: "编码", width: 130 },
  { colKey: "name", title: "名称", width: 140 },
  { colKey: "desc", title: "说明" },
  { colKey: "approver", title: "审批人", width: 90 },
  { colKey: "priority", title: "优先级", width: 90 },
  { colKey: "action", title: "操作", width: 150 },
];
const ruleColumns: any[] = [
  { colKey: "idx", title: "#", width: 46 },
  { colKey: "pattern", title: "正则", width: 190 },
  { colKey: "label", title: "说明" },
  { colKey: "priority", title: "优先级", width: 90 },
  { colKey: "enabled", title: "启用", width: 64 },
  { colKey: "action", title: "操作", width: 150 },
];
const slaColumns: any[] = [
  { colKey: "priority", title: "优先级", width: 90 },
  { colKey: "deadline_days", title: "截止天数", width: 100 },
  { colKey: "warn_before_hours", title: "到期前预警(h)", width: 120 },
  { colKey: "escalate_hours", title: "违约升级(h)", width: 120 },
  { colKey: "action", title: "操作", width: 80 },
];

function userName(id: number | null) { return id ? users.value.find((u) => u.id === id)?.name || "—" : "—"; }

// 工单类型弹窗（含 SOP 字段）
const typeModal = reactive({
  open: false, editing: null as any,
  type_code: "", name: "", desc: "", default_approver_id: undefined as number | undefined, default_priority: "P2",
  // SOP 字段
  guidance_ref: "",
  sop_purpose: "",
  sop_scope: "",
  sop_steps: "",
  sop_acceptance: "",
  sop_escalation: "",
  sop_related_guidance: "",
  sop_backfill_required: true,
});
function openType() {
  typeModal.editing = null;
  typeModal.type_code = ""; typeModal.name = ""; typeModal.desc = "";
  typeModal.default_approver_id = undefined; typeModal.default_priority = "P2";
  typeModal.guidance_ref = ""; typeModal.sop_purpose = ""; typeModal.sop_scope = "";
  typeModal.sop_steps = ""; typeModal.sop_acceptance = ""; typeModal.sop_escalation = "";
  typeModal.sop_related_guidance = ""; typeModal.sop_backfill_required = true;
  typeModal.open = true;
}
function editType(t: any) {
  typeModal.editing = t;
  typeModal.type_code = t.type_code; typeModal.name = t.name; typeModal.desc = t.desc || "";
  typeModal.default_approver_id = t.default_approver_id; typeModal.default_priority = t.default_priority;
  typeModal.guidance_ref = t.guidance_ref || "";
  typeModal.sop_purpose = t.sop_purpose || "";
  typeModal.sop_scope = t.sop_scope || "";
  typeModal.sop_steps = t.sop_steps ? JSON.stringify(t.sop_steps, null, 2) : "";
  typeModal.sop_acceptance = t.sop_acceptance || "";
  typeModal.sop_escalation = t.sop_escalation ? JSON.stringify(t.sop_escalation, null, 2) : "";
  typeModal.sop_related_guidance = t.sop_related_guidance ? JSON.stringify(t.sop_related_guidance, null, 2) : "";
  typeModal.sop_backfill_required = t.sop_backfill_required !== false;
  typeModal.open = true;
}
async function saveType() {
  try {
    const data: any = {
      name: typeModal.name, desc: typeModal.desc,
      default_approver_id: typeModal.default_approver_id, default_priority: typeModal.default_priority,
      type_code: typeModal.type_code,
      guidance_ref: typeModal.guidance_ref || null,
      sop_purpose: typeModal.sop_purpose || null,
      sop_scope: typeModal.sop_scope || null,
      sop_acceptance: typeModal.sop_acceptance || null,
      sop_backfill_required: typeModal.sop_backfill_required,
    };
    // 解析 JSON 字段
    try { data.sop_steps = typeModal.sop_steps ? JSON.parse(typeModal.sop_steps) : null; } catch { toast.warning("标准步骤 JSON 格式错误"); return; }
    try { data.sop_escalation = typeModal.sop_escalation ? JSON.parse(typeModal.sop_escalation) : null; } catch { toast.warning("升级规则 JSON 格式错误"); return; }
    try { data.sop_related_guidance = typeModal.sop_related_guidance ? JSON.parse(typeModal.sop_related_guidance) : null; } catch { toast.warning("关联指引 JSON 格式错误"); return; }
    const saved = await writeConfig(() => typeModal.editing
      ? CC.updateWoType(typeModal.editing.id, data)
      : CC.addWoType(data));
    if (saved) typeModal.open = false;
  } catch (e: any) { toast.error(e.message); }
}
async function delType(id: number) { if (await confirmDialog("删除？")) await writeConfig(() => CC.delWoType(id)); }

// 通用弹窗
const modal = reactive({ open: false, type: "" as string, category: "source", code: "", name: "", color: "", pattern: "", label: "", priority: "P2", editing: null as any });
const modalTitle = computed(() => ({ def: modal.editing ? "编辑来源/状态" : "新增来源/状态", priority: modal.editing ? "编辑优先级规则" : "新增优先级规则" }[modal.type] || ""));
function openDef() { modal.editing = null; modal.type = "def"; modal.category = "source"; modal.code = ""; modal.name = ""; modal.color = ""; modal.open = true; }
function editDef(s: any) { modal.editing = s; modal.type = "def"; modal.category = s.category; modal.code = s.code; modal.name = s.name; modal.color = s.color || ""; modal.open = true; }
function openPriority() { modal.editing = null; modal.type = "priority"; modal.pattern = ""; modal.label = ""; modal.priority = "P2"; modal.open = true; }
function editPriority(r: any) { modal.editing = r; modal.type = "priority"; modal.pattern = r.pattern; modal.label = r.label; modal.priority = r.priority; modal.open = true; }
async function confirmModal() {
  const saved = await writeConfig(async () => {
    if (modal.type === "def") {
      if (modal.editing) await CC.updateConfigDef(modal.editing.id, { name: modal.name, color: modal.color || undefined });
      else await CC.addConfigDef({ category: modal.category, code: modal.code, name: modal.name, color: modal.color || undefined });
    } else if (modal.type === "priority") {
      if (modal.editing) await CC.updatePriorityRuleApi(modal.editing.id, { pattern: modal.pattern, label: modal.label, priority: modal.priority });
      else await CC.addPriorityRuleApi({ pattern: modal.pattern, label: modal.label || "新规则", priority: modal.priority });
    }
  });
  if (saved) modal.open = false;
}
async function delDef(id: number) { if (await confirmDialog("删除？")) await writeConfig(() => CC.delConfigDef(id)); }
async function delPriority(id: number) { if (await confirmDialog("删除？")) await writeConfig(() => CC.delPriorityRuleApi(id)); }
async function togglePriority(r: any) { await writeConfig(() => CC.updatePriorityRuleApi(r.id, { enabled: !r.enabled })); }

// SLA
async function saveSla(s: any) {
  const saved = await writeConfig(() => CC.updateSla(s.id, {
    deadline_days: s.deadline_days, warn_before_hours: s.warn_before_hours, escalate_hours: s.escalate_hours,
  }));
  if (saved) toast.success(`${s.priority} SLA 已保存`);
}

// 审批流节点
const nodeModal = reactive({ open: false, flow: null as any, idx: -1, title: "", sub: "", role: "", timeout_days: 0 });
function editNode(f: any, i: number) {
  const n = f.nodes[i];
  if (n.type === "start" || n.type === "end") { toast.warning("起始/结束节点不可编辑"); return; }
  nodeModal.flow = f; nodeModal.idx = i; nodeModal.title = n.title; nodeModal.sub = n.sub; nodeModal.role = n.role || ""; nodeModal.timeout_days = n.timeout_days || 0; nodeModal.open = true;
}
async function saveNode() {
  const f = nodeModal.flow; const n = f.nodes[nodeModal.idx];
  const nodes = f.nodes.map((item: any, index: number) => index === nodeModal.idx
    ? { ...n, title: nodeModal.title, sub: nodeModal.sub, role: nodeModal.role, timeout_days: nodeModal.timeout_days }
    : item);
  if (await writeConfig(() => CC.updateApprovalFlow(f.id, { nodes }))) nodeModal.open = false;
}
function flowClass(p: string) { return p === "P1" ? "p1" : p === "P2" ? "p2" : "p3"; }
function emoji(p: string) { return p === "P1" ? "🔴" : p === "P2" ? "🟠" : "🔵"; }
function nodeTypeLabel(t: string) { return ({ start: "起始", approval: "审批", exec: "执行", end: "结束" } as any)[t] || t; }

async function loadAll() {
  loadError.value = "";
  let s, st, u, wt, pr, sla, flows;
  try {
    [s, st, u, wt, pr, sla, flows] = await Promise.all([
      getSources(), getStatuses(), getUsers(), CC.getWoTypesFull(), getPriorityRules(), getSla(), getApprovalFlows(),
    ]);
  } catch (e: any) {
    loadError.value = e.message || "请稍后重试";
    throw e;
  }
  sources.value = s; statuses.value = st; users.value = u; woTypes.value = wt; priorityRules.value = pr; slaList.value = sla; approvalFlows.value = flows;
  // 加载全部用户（用于区域PMO选择）
  try {
    allUsers.value = await getUsersAll();
  } catch { allUsers.value = u; }
  // 加载区域PMO配置（失败不影响页面）
  try {
    const rpmo = await getRegionPMOs();
    for (const r of REGIONS) {
      regionPMO[r] = rpmo.find((x: any) => x.region === r) || null;
    }
  } catch { /* 接口可能尚未部署 */ }
  // 加载角色→人员配置（失败不影响页面）
  try {
    roleAssignments.value = await getRoleAssignments();
  } catch { /* 接口可能尚未部署 */ }
  // 加载异常指标大类配置（失败不影响页面）
  try {
    anomalyCategories.value = await getAnomalyCategories();
  } catch { /* 接口可能尚未部署 */ }
}
async function onRegionPMOChange(region: string, userId: number | undefined) {
  if (userId) {
    // 设置 PMO
    try {
      const result = await setRegionPMO({ region, user_id: userId });
      regionPMO[region] = result;
    } catch (e: any) { toast.error("保存失败：" + e.message); }
  } else {
    // 清除 PMO
    const existing = regionPMO[region];
    if (existing?.id) {
      try {
        await deleteRegionPMO(existing.id);
        regionPMO[region] = null;
      } catch (e: any) { toast.error("删除失败：" + e.message); }
    }
  }
}
async function onRoleChange(code: string, userId: number | undefined) {
  try {
    const result = await updateRoleAssignment(code, { user_id: userId ?? null });
    const idx = roleAssignments.value.findIndex((r) => r.role_code === code);
    if (idx >= 0) roleAssignments.value[idx] = result;
  } catch (e: any) { toast.error("保存失败：" + e.message); }
}

// 异常指标大类：默认责任人按姓名存取，前端做 姓名↔用户id 映射
function categoryUserId(c: any): number | undefined {
  const name = c.extra?.default_person_name;
  if (!name) return undefined;
  const u = allUsers.value.find((x: any) => x.name === name);
  return u ? u.id : undefined;
}
async function onCategoryPersonChange(c: any, userId: number | undefined) {
  try {
    const name = userId ? (allUsers.value.find((u: any) => u.id === userId)?.name ?? null) : null;
    const result = await updateAnomalyCategory(c.id, { default_person_name: name });
    const idx = anomalyCategories.value.findIndex((x) => x.id === c.id);
    if (idx >= 0) anomalyCategories.value[idx] = result;
  } catch (e: any) { toast.error("保存失败：" + e.message); }
}
function retryLoad() { loadAll().catch(() => {}); }
onMounted(retryLoad);
</script>

<style scoped>
.config-page .header { margin-bottom: 20px; } .header h1 { font-size: var(--fs-h1); font-weight: 700; } .meta { font-size: 12px; color: var(--muted); }
.card { background: var(--card); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow); margin-bottom: 16px; }
.card-hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.card-hd h3 { font-size: 15px; font-weight: 700; } .count { font-size: 12px; color: var(--muted); }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; } .sub-hd { font-weight: 600; font-size: 13px; margin-bottom: 8px; }
.chip-list { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; background: #f8fafc; border: 1px solid var(--border); border-radius: 14px; font-size: 12px; cursor: pointer; }
.dot { width: 8px; height: 8px; border-radius: 50%; } .chip-del { cursor: pointer; color: var(--red); margin-left: 4px; font-weight: 700; }
.desc { color: var(--muted); font-size: 12px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.toggle { cursor: pointer; padding: 2px 10px; border-radius: 10px; font-size: 11px; font-weight: 600; background: #f3f4f6; color: #6b7280; }
.toggle.on { background: #ecfdf5; color: var(--green); }
.inline-inp { width: 70px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 4px; font-size: 12px; }
.flow-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.flow-card { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.flow-card.p1 { border-top: 3px solid var(--red); } .flow-card.p2 { border-top: 3px solid var(--amber); } .flow-card.p3 { border-top: 3px solid var(--brand); }
.flow-hd h4 { font-size: 14px; margin-bottom: 14px; } .flow-nodes { display: flex; flex-direction: column; gap: 8px; }
.flow-node { background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; text-align: center; cursor: pointer; }
.flow-node:hover { border-color: var(--brand); } .node-title { font-weight: 700; font-size: 13px; } .node-sub { font-size: 11px; color: var(--muted); }
.node-type { font-size: 10px; margin-top: 4px; padding: 2px 8px; border-radius: 6px; display: inline-block; font-weight: 600; background: #f3f4f6; color: #6b7280; }
.node-type.start { background: #ecfdf5; color: var(--green); } .node-type.approval { background: #eff6ff; color: var(--brand); } .node-type.exec { background: #fffbeb; color: var(--amber); }
.node-timeout { font-size: 10px; color: var(--muted); }
.modal-section-title { font-size: 13px; font-weight: 700; color: var(--brand); margin: 16px 0 10px; padding-top: 12px; border-top: 1px solid var(--border); }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; font-size: 12px; font-weight: 600; color: #4b5563; margin-bottom: 4px; }
.form-group input, .form-group select, .form-group textarea { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
.form-group textarea { font-family: monospace; resize: vertical; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-hint { font-size: 10px; color: var(--muted); margin-top: 2px; display: block; }
.checkbox-label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px; font-weight: 400; }
.checkbox-label input { width: auto; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.modal-body-scroll { max-height: 60vh; overflow-y: auto; padding-right: 4px; }
.region-pmo-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.region-pmo-row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: #f8fafc; border-radius: 8px; border: 1px solid var(--border); }
.region-label { font-weight: 700; font-size: 13px; min-width: 40px; flex-shrink: 0; }
.region-pmo-select { flex: 1; min-width: 0; }
</style>

<template>
  <div class="config-page">
    <div class="header"><div><h1>规则配置</h1><div class="meta">全部可配置 · 改完即时生效</div></div></div>

    <!-- 工单类型 -->
    <div class="card">
      <div class="card-hd"><h3>📚 工单类型</h3><button class="btn btn-pri btn-sm" @click="openType()">＋ 新增</button></div>
      <table>
        <thead><tr><th>编码</th><th>名称</th><th>说明</th><th>审批人</th><th>优先级</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="t in woTypes" :key="t.id">
            <td><code>{{ t.type_code }}</code></td>
            <td @dblclick="editType(t)"><b>{{ t.name }}</b></td>
            <td class="desc">{{ t.desc || '—' }}</td>
            <td>{{ userName(t.default_approver_id) }}</td>
            <td><span class="tag" :class="priorityTag(t.default_priority)">{{ priorityLabel(t.default_priority) }}</span></td>
            <td>
              <button class="btn btn-sm btn-out" @click="editType(t)">编辑</button>
              <button class="btn btn-sm btn-out" style="color:var(--red)" @click="delType(t.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
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

    <!-- 优先级规则 -->
    <div class="card">
      <div class="card-hd"><h3>🎯 优先级判定规则</h3><button class="btn btn-pri btn-sm" @click="openPriority()">＋ 新增</button></div>
      <table>
        <thead><tr><th>#</th><th>正则</th><th>说明</th><th>优先级</th><th>启用</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="(r, i) in priorityRules" :key="r.id">
            <td>{{ i+1 }}</td>
            <td @dblclick="editPriority(r)"><code>{{ r.pattern }}</code></td>
            <td @dblclick="editPriority(r)">{{ r.label }}</td>
            <td><span class="tag" :class="priorityTag(r.priority)">{{ priorityLabel(r.priority) }}</span></td>
            <td><span class="toggle" :class="{on: r.enabled}" @click="togglePriority(r)">{{ r.enabled ? '开' : '关' }}</span></td>
            <td><button class="btn btn-sm btn-out" @click="editPriority(r)">编辑</button><button class="btn btn-sm btn-out" style="color:var(--red)" @click="delPriority(r.id)">删除</button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- SLA -->
    <div class="card">
      <div class="card-hd"><h3>⏱ SLA 定义</h3></div>
      <table>
        <thead><tr><th>优先级</th><th>截止天数</th><th>到期前预警(h)</th><th>违约升级(h)</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="s in slaList" :key="s.id">
            <td><span class="tag" :class="priorityTag(s.priority)">{{ priorityLabel(s.priority) }}</span></td>
            <td><input type="number" v-model.number="s.deadline_days" class="inline-inp" /></td>
            <td><input type="number" v-model.number="s.warn_before_hours" class="inline-inp" /></td>
            <td><input type="number" v-model.number="s.escalate_hours" class="inline-inp" /></td>
            <td><button class="btn btn-pri btn-sm" @click="saveSla(s)">保存</button></td>
          </tr>
        </tbody>
      </table>
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
    <div v-if="typeModal.open" class="modal-mask" @click.self="typeModal.open = false">
      <div class="modal modal-wide">
        <h3>{{ typeModal.editing ? '编辑' : '新增' }}工单类型</h3>
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
        <div class="modal-actions"><button class="btn btn-out" @click="typeModal.open = false">取消</button><button class="btn btn-pri" @click="saveType">保存</button></div>
      </div>
    </div>

    <!-- 通用弹窗 -->
    <div v-if="modal.open" class="modal-mask" @click.self="modal.open = false">
      <div class="modal">
        <h3>{{ modalTitle }}</h3>
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
        <div class="modal-actions"><button class="btn btn-out" @click="modal.open = false">取消</button><button class="btn btn-pri" @click="confirmModal">保存</button></div>
      </div>
    </div>

    <!-- 审批流节点弹窗 -->
    <div v-if="nodeModal.open" class="modal-mask" @click.self="nodeModal.open = false">
      <div class="modal">
        <h3>编辑审批节点</h3>
        <div class="form-group"><label>名称</label><input v-model="nodeModal.title" /></div>
        <div class="form-group"><label>说明</label><input v-model="nodeModal.sub" /></div>
        <div class="form-group"><label>角色</label><input v-model="nodeModal.role" /></div>
        <div class="form-group"><label>超时(天)</label><input type="number" v-model.number="nodeModal.timeout_days" /></div>
        <div class="modal-actions"><button class="btn btn-out" @click="nodeModal.open = false">取消</button><button class="btn btn-pri" @click="saveNode">保存</button></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { getSources, getStatuses, getProjects, getUsers, getUsersAll, getPriorityRules, getSla, getApprovalFlows, getRegionPMOs, getRoleAssignments } from "@/api/config";
import * as CC from "@/api/config-crud";
import { setRegionPMO, deleteRegionPMO, updateRoleAssignment } from "@/api/config";
import SearchableSelect from "@/components/SearchableSelect.vue";
import { priorityLabel, priorityTag } from "@/utils/wo-display";

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
    try { data.sop_steps = typeModal.sop_steps ? JSON.parse(typeModal.sop_steps) : null; } catch { alert("标准步骤 JSON 格式错误"); return; }
    try { data.sop_escalation = typeModal.sop_escalation ? JSON.parse(typeModal.sop_escalation) : null; } catch { alert("升级规则 JSON 格式错误"); return; }
    try { data.sop_related_guidance = typeModal.sop_related_guidance ? JSON.parse(typeModal.sop_related_guidance) : null; } catch { alert("关联指引 JSON 格式错误"); return; }
    if (typeModal.editing) await CC.updateWoType(typeModal.editing.id, data);
    else await CC.addWoType(data);
    typeModal.open = false; await loadAll();
  } catch (e: any) { alert(e.message); }
}
async function delType(id: number) { if (!confirm("删除？")) return; await CC.delWoType(id); await loadAll(); }

// 通用弹窗
const modal = reactive({ open: false, type: "" as string, category: "source", code: "", name: "", color: "", pattern: "", label: "", priority: "P2", editing: null as any });
const modalTitle = computed(() => ({ def: modal.editing ? "编辑来源/状态" : "新增来源/状态", priority: modal.editing ? "编辑优先级规则" : "新增优先级规则" }[modal.type] || ""));
function openDef() { modal.editing = null; modal.type = "def"; modal.category = "source"; modal.code = ""; modal.name = ""; modal.color = ""; modal.open = true; }
function editDef(s: any) { modal.editing = s; modal.type = "def"; modal.category = s.category; modal.code = s.code; modal.name = s.name; modal.color = s.color || ""; modal.open = true; }
function openPriority() { modal.editing = null; modal.type = "priority"; modal.pattern = ""; modal.label = ""; modal.priority = "P2"; modal.open = true; }
function editPriority(r: any) { modal.editing = r; modal.type = "priority"; modal.pattern = r.pattern; modal.label = r.label; modal.priority = r.priority; modal.open = true; }
async function confirmModal() {
  try {
    if (modal.type === "def") {
      if (modal.editing) await CC.updateConfigDef(modal.editing.id, { name: modal.name, color: modal.color || undefined });
      else await CC.addConfigDef({ category: modal.category, code: modal.code, name: modal.name, color: modal.color || undefined });
    } else if (modal.type === "priority") {
      if (modal.editing) await CC.updatePriorityRuleApi(modal.editing.id, { pattern: modal.pattern, label: modal.label, priority: modal.priority });
      else await CC.addPriorityRuleApi({ pattern: modal.pattern, label: modal.label || "新规则", priority: modal.priority });
    }
    modal.open = false; await loadAll();
  } catch (e: any) { alert(e.message); }
}
async function delDef(id: number) { if (!confirm("删除？")) return; await CC.delConfigDef(id); await loadAll(); }
async function delPriority(id: number) { if (!confirm("删除？")) return; await CC.delPriorityRuleApi(id); await loadAll(); }
async function togglePriority(r: any) { await CC.updatePriorityRuleApi(r.id, { enabled: !r.enabled }); await loadAll(); }

// SLA
async function saveSla(s: any) { await CC.updateSla(s.id, { deadline_days: s.deadline_days, warn_before_hours: s.warn_before_hours, escalate_hours: s.escalate_hours }); alert(`${s.priority} SLA 已保存`); }

// 审批流节点
const nodeModal = reactive({ open: false, flow: null as any, idx: -1, title: "", sub: "", role: "", timeout_days: 0 });
function editNode(f: any, i: number) {
  const n = f.nodes[i];
  if (n.type === "start" || n.type === "end") { alert("起始/结束节点不可编辑"); return; }
  nodeModal.flow = f; nodeModal.idx = i; nodeModal.title = n.title; nodeModal.sub = n.sub; nodeModal.role = n.role || ""; nodeModal.timeout_days = n.timeout_days || 0; nodeModal.open = true;
}
async function saveNode() {
  const f = nodeModal.flow; const n = f.nodes[nodeModal.idx];
  n.title = nodeModal.title; n.sub = nodeModal.sub; n.role = nodeModal.role; n.timeout_days = nodeModal.timeout_days;
  await CC.updateApprovalFlow(f.id, { nodes: f.nodes }); nodeModal.open = false; await loadAll();
}
function flowClass(p: string) { return p === "P1" ? "p1" : p === "P2" ? "p2" : "p3"; }
function emoji(p: string) { return p === "P1" ? "🔴" : p === "P2" ? "🟠" : "🔵"; }
function nodeTypeLabel(t: string) { return ({ start: "起始", approval: "审批", exec: "执行", end: "结束" } as any)[t] || t; }

async function loadAll() {
  const [s, st, u, wt, pr, sla, flows] = await Promise.all([
    getSources(), getStatuses(), getUsers(), CC.getWoTypesFull(), getPriorityRules(), getSla(), getApprovalFlows(),
  ]);
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
}
async function onRegionPMOChange(region: string, userId: number | undefined) {
  if (userId) {
    // 设置 PMO
    try {
      const result = await setRegionPMO({ region, user_id: userId });
      regionPMO[region] = result;
    } catch (e: any) { alert("保存失败：" + e.message); }
  } else {
    // 清除 PMO
    const existing = regionPMO[region];
    if (existing?.id) {
      try {
        await deleteRegionPMO(existing.id);
        regionPMO[region] = null;
      } catch (e: any) { alert("删除失败：" + e.message); }
    }
  }
}
async function onRoleChange(code: string, userId: number | undefined) {
  try {
    const result = await updateRoleAssignment(code, { user_id: userId ?? null });
    const idx = roleAssignments.value.findIndex((r) => r.role_code === code);
    if (idx >= 0) roleAssignments.value[idx] = result;
  } catch (e: any) { alert("保存失败：" + e.message); }
}
onMounted(loadAll);
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
table { width: 100%; border-collapse: collapse; font-size: 13px; } th { background: #f8fafc; padding: 10px 12px; text-align: left; font-weight: 600; border-bottom: 2px solid var(--border); font-size: 11px; color: var(--muted); }
td { padding: 9px 12px; border-bottom: 1px solid var(--border); } .desc { color: var(--muted); font-size: 12px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; border-radius: 12px; padding: 24px; width: 420px; max-width: 90vw; max-height: 85vh; overflow-y: auto; }
.modal-wide { width: 640px; }
.modal h3 { font-size: 16px; margin-bottom: 16px; }
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
.tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.tag-blue { background: #eff6ff; color: var(--brand); } .tag-amber { background: #fffbeb; color: var(--amber); } .tag-red { background: #fef2f2; color: var(--red); }
.btn { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-pri { background: var(--brand); color: #fff; } .btn-out { background: #fff; color: #4b5563; border: 1px solid var(--border); } .btn-sm { padding: 4px 10px; font-size: 11px; }
</style>
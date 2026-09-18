<template>
  <div class="config-page">
    <div class="header"><div><h1>规则配置</h1><div class="meta">按运行链路归类；配置状态和实际消费位置均明确标注</div></div></div>
    <PageError v-if="loadError" title="规则配置加载失败" :message="loadError" @action="retryLoad" />
    <template v-else>
    <div class="config-guide">
      <span><b>工单类型</b>：来源/类型/异常大类三合一，10 内置 + 后台极简新增，配审批人与责任人</span>
      <span><b>自动判定</b>：优先级正则（仅智能解析/导入/机器人）</span>
      <span><b>时效与升级</b>：SLA 期限、平台升级路径</span>
      <span><b>组织映射</b>：区域负责人、角色人员</span>
    </div>

    <!-- 工单类型（统一口径：来源/工单类型/异常指标大类三合一） -->
    <div class="card">
      <div class="card-hd"><div><h3>📚 工单类型</h3><span class="count">流程区分保留：异常类走五阶段、运营计划走计划流、其余三步；每类配默认审批人（异常类再配默认责任人）</span></div><button class="btn btn-pri btn-sm" @click="openNewType()">＋ 新增（只输名字）</button></div>
      <div class="region-pmo-grid">
        <div v-for="t in woTypeList" :key="t.id" class="region-pmo-row">
          <span class="region-label"><span class="dot" style="display:inline-block" :style="{ background: t.color }"></span>{{ t.name }}<code class="role-code">{{ t.code }}</code><span class="flow-badge">{{ flowLabel(t) }}</span></span>
          <SearchableSelect
            :model-value="approverUserId(t)"
            :options="allUsers"
            placeholder="默认审批人…"
            class="region-pmo-select"
            @update:model-value="(v: number | undefined) => onTypeApproverChange(t, v)"
          />
          <SearchableSelect
            v-if="isAnomalyType(t.code)"
            :model-value="personUserId(t)"
            :options="allUsers"
            placeholder="默认责任人…"
            class="region-pmo-select"
            @update:model-value="(v: number | undefined) => onTypePersonChange(t, v)"
          />
        </div>
      </div>
    </div>

    <!-- 状态 -->
    <div class="card">
      <div class="card-hd"><h3>🏷️ 工单状态</h3></div>
      <div class="grid2">
        <div><div class="sub-hd">状态</div>
          <div class="chip-list"><span v-for="s in statuses" :key="s.id" class="chip" @dblclick="editDef(s)"><span class="dot" :style="{background: s.color}"></span>{{ s.name }}</span></div>
        </div>
      </div>
    </div>

    <!-- 优先级规则 -->
    <div class="card">
      <div class="card-hd"><div><h3>🎯 自动优先级判定</h3><span class="count">已接入智能解析、导入、机器人建单；手工指定优先级优先</span></div><button class="btn btn-pri btn-sm" @click="openPriority()">＋ 新增</button></div>
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
      <div class="card-hd"><div><h3>⏱ SLA 定义</h3><span class="count">已接入默认截止日、SLA 扫描和管理看板违约统计</span></div></div>
      <t-table :data="slaList" :columns="slaColumns" row-key="id" size="small" cell-empty-content="—">
        <template #priority="{ row }"><t-tag :theme="priorityTheme(row.priority)" size="small">{{ priorityLabel(row.priority) }}</t-tag></template>
        <template #deadline_days="{ row }"><input type="number" v-model.number="row.deadline_days" class="inline-inp" /></template>
        <template #warn_before_hours="{ row }"><input type="number" v-model.number="row.warn_before_hours" class="inline-inp" /></template>
        <template #escalate_hours="{ row }"><input type="number" v-model.number="row.escalate_hours" class="inline-inp" /></template>
        <template #action="{ row }"><t-button size="small" theme="primary" :loading="writing" @click="saveSla(row)">保存</t-button></template>
      </t-table>
    </div>

    <!-- 区域负责人（PMO） -->
    <div class="card">
      <div class="card-hd"><div><h3>📍 区域负责人（PMO）</h3><span class="count">已接入：区域数据可见范围 + 异常指标默认责任人兜底</span></div></div>
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
      <div class="card-hd"><h3>👤 角色人员映射</h3><span class="count">已接入工单模板的默认审批人角色解析</span></div>
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

    <!-- 数据权限（角色 → 可见范围） -->
    <div class="card">
      <div class="card-hd"><div><h3>🔐 数据权限（角色 → 可见范围）</h3><span class="count">每个角色能看到哪些工单；多选取并集去重</span></div></div>
      <div class="scope-grid">
        <div v-for="r in roleScopes" :key="r.role_code" class="scope-row">
          <span class="region-label"><b>{{ r.role_name }}</b><code class="role-code">{{ r.role_code }}</code></span>
          <label v-for="s in SCOPE_OPTIONS" :key="s.value" class="scope-check" :class="{ disabled: r.is_locked }">
            <input type="checkbox" :checked="hasScope(r, s.value)" :disabled="r.is_locked" @change="toggleScope(r, s.value)" />
            {{ s.label }}
          </label>
        </div>
      </div>
      <div class="scope-hint">管理员固定「全部」不可改；「区域」仅对区域 PMO 生效，具体负责哪几个大区由上方「区域负责人（PMO）」配置；其他角色勾「区域」无对应大区时，该范围视作空。</div>
    </div>

    <!-- 审批流 -->
    <div class="card">
      <div class="card-hd"><div><h3>🔄 平台升级路径</h3><span class="count">已接入平台节点展示和逾期升级目标；不修改钉钉 OA 模板</span></div></div>
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

    <!-- 新增工单类型弹窗（极简：只输名字） -->
    <t-dialog v-model:visible="newTypeModal.open" header="新增工单类型" width="420" :footer="false">
      <div class="form-group"><label>名称</label><input v-model="newTypeModal.name" placeholder="如：安全生产工单" /></div>
      <div class="form-hint" style="margin:4px 0 12px">自动生成编码 custom_N，流程按「运营计划工单」走；审批人/责任人可在下方列表里补。</div>
      <div class="modal-actions"><t-button variant="outline" @click="newTypeModal.open = false">取消</t-button><t-button theme="primary" :loading="writing" @click="saveNewType">保存</t-button></div>
    </t-dialog>

    <!-- 通用弹窗 -->
    <t-dialog v-model:visible="modal.open" :header="modalTitle" width="420" :footer="false">
        <template v-if="modal.type === 'def'">
          <div class="form-group"><label>类别</label><select v-model="modal.category"><option value="status">状态</option></select></div>
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
import { getStatuses, getProjects, getUsers, getUsersAll, getPriorityRules, getSla, getApprovalFlows, getRegionPMOs, getRoleAssignments, getRoleScopes, updateRoleScope, getWoTypes, addWorkOrderType, updateWorkOrderType } from "@/api/config";
import * as CC from "@/api/config-crud";
import { setRegionPMO, deleteRegionPMO, updateRoleAssignment } from "@/api/config";
import SearchableSelect from "@/components/SearchableSelect.vue";
import PageError from "@/components/PageError.vue";
import { priorityLabel, priorityTheme } from "@/utils/wo-display";

const REGIONS = ["华北", "华中", "华东", "华南", "西北", "西南", "东北"];
const SCOPE_OPTIONS = [
  { value: "self", label: "自己相关" },
  { value: "region", label: "区域" },
  { value: "all", label: "全部" },
];
const statuses = ref<any[]>([]);
const users = ref<any[]>([]);
const allUsers = ref<any[]>([]);
const woTypeList = ref<any[]>([]);
const priorityRules = ref<any[]>([]);
const slaList = ref<any[]>([]);
const approvalFlows = ref<any[]>([]);
const regionPMO = reactive<Record<string, any>>({});
const roleAssignments = ref<any[]>([]);
const roleScopes = ref<any[]>([]);
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

// 工单类型（统一口径）：极简新增 + 逐类配审批人/责任人
const ANOMALY_CODES = new Set(["power_gen", "curtailment", "dual_rule", "reliability", "info_quality", "contract", "cost", "satisfaction"]);
const FLOW_LABEL: Record<string, string> = { alert: "五阶段", plan: "计划流", default: "三步" };
const newTypeModal = reactive({ open: false, name: "" });
function openNewType() { newTypeModal.name = ""; newTypeModal.open = true; }
async function saveNewType() {
  if (!newTypeModal.name.trim()) { toast.warning("请填写类型名"); return; }
  const saved = await writeConfig(() => addWorkOrderType({ name: newTypeModal.name.trim() }));
  if (saved) newTypeModal.open = false;
}
function isAnomalyType(code: string) { return ANOMALY_CODES.has(code); }
function flowLabel(t: any) { return FLOW_LABEL[(t.extra || {}).flow] || "三步"; }
function typeUserName(t: any, key: string) {
  const n = (t.extra || {})[key] || "";
  return allUsers.value.find((u) => u.name === n)?.id;
}
const approverUserId = (t: any) => typeUserName(t, "default_approver_name");
const personUserId = (t: any) => typeUserName(t, "default_person_name");
async function onTypeApproverChange(t: any, v: number | undefined) {
  const name = v ? allUsers.value.find((u) => u.id === v)?.name || "" : "";
  await writeConfig(() => updateWorkOrderType(t.id, { default_approver_name: name || null }));
}
async function onTypePersonChange(t: any, v: number | undefined) {
  const name = v ? allUsers.value.find((u) => u.id === v)?.name || "" : "";
  await writeConfig(() => updateWorkOrderType(t.id, { default_person_name: name || null }));
}

// 通用弹窗
const modal = reactive({ open: false, type: "" as string, category: "status", code: "", name: "", color: "", pattern: "", label: "", priority: "P2", editing: null as any });
const modalTitle = computed(() => ({ def: modal.editing ? "编辑状态" : "新增状态", priority: modal.editing ? "编辑优先级规则" : "新增优先级规则" }[modal.type] || ""));
function openDef() { modal.editing = null; modal.type = "def"; modal.category = "status"; modal.code = ""; modal.name = ""; modal.color = ""; modal.open = true; }
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
  let st, u, wt, pr, sla, flows;
  try {
    [st, u, wt, pr, sla, flows] = await Promise.all([
      getStatuses(), getUsers(), getWoTypes(), getPriorityRules(), getSla(), getApprovalFlows(),
    ]);
  } catch (e: any) {
    loadError.value = e.message || "请稍后重试";
    throw e;
  }
  statuses.value = st; users.value = u; woTypeList.value = wt; priorityRules.value = pr; slaList.value = sla; approvalFlows.value = flows;
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
  // 加载数据范围角色配置（失败不影响页面）
  try {
    roleScopes.value = await getRoleScopes();
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

// 数据范围角色：勾选可见范围（多取并集）
function hasScope(r: any, s: string) {
  return (r.scopes || []).includes(s);
}
async function toggleScope(r: any, s: string) {
  const scopes: string[] = Array.isArray(r.scopes) ? r.scopes : [];
  const next = scopes.includes(s) ? scopes.filter((x) => x !== s) : [...scopes, s];
  try {
    const saved = await updateRoleScope(r.role_code, next);
    const idx = roleScopes.value.findIndex((x) => x.role_code === r.role_code);
    if (idx >= 0) roleScopes.value[idx] = saved;
  } catch (e: any) { toast.error("保存失败：" + (e.message || "未知错误")); }
}

function retryLoad() { loadAll().catch(() => {}); }
onMounted(retryLoad);
</script>

<style scoped>
.config-page .header { margin-bottom: 20px; } .header h1 { font-size: var(--fs-h1); font-weight: 700; } .meta { font-size: 12px; color: var(--muted); }
.config-guide { display: flex; flex-wrap: wrap; gap: 8px; margin: -6px 0 16px; }
.config-guide span { background: #f0f5ff; border: 1px solid #d9e6ff; border-radius: 999px; color: #4b5563; font-size: 12px; padding: 5px 10px; }
.config-guide b { color: var(--brand); }
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
.scope-grid { display: flex; flex-direction: column; gap: 10px; }
.scope-row { display: flex; align-items: center; gap: 18px; padding: 8px 12px; background: #f8fafc; border-radius: 8px; border: 1px solid var(--border); }
.scope-row .region-label { min-width: 120px; }
.scope-check { display: flex; align-items: center; gap: 5px; font-size: 13px; cursor: pointer; }
.scope-check input { width: auto; }
.scope-check.disabled { opacity: 0.45; cursor: not-allowed; }
.scope-hint { font-size: 12px; color: var(--muted); margin-top: 10px; line-height: 1.6; }
</style>

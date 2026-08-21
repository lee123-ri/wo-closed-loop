<template>
  <div class="wo-detail" v-if="wo">
    <div class="header">
      <div>
        <h1>{{ wo.code }} — {{ wo.title }}</h1>
        <div class="meta"><span class="clickable" @click="router.push('/work-orders')">← 返回列表</span></div>
      </div>
      <div class="header-actions">
        <!-- alert 判断流程专用按钮 -->
        <template v-if="wo.source_code === 'alert'">
          <button v-if="wo.status === 'judging'" class="btn btn-pri btn-sm" @click="dispatchMeasure">
            📋 生成措施工单并闭环
          </button>
          <button v-if="wo.status === 'judging'" class="btn btn-out btn-sm" @click="transition('close')">
            无需措施，直接闭环
          </button>
        </template>
        <!-- 普通工单标准按钮 -->
        <template v-else>
          <button v-if="wo.status === 'pending' || wo.status === 'approving'" class="btn btn-pri btn-sm" @click="openDispatchConfirm">派发 → 发起OA审批</button>
          <button v-if="wo.status === 'dispatched'" class="btn btn-pri btn-sm" @click="transition('start_exec')">开始执行</button>
          <button v-if="wo.status === 'executing'" class="btn btn-pri btn-sm" @click="transition('submit_evidence')">提交佐证 → 验收</button>
          <button v-if="wo.status === 'verifying'" class="btn btn-pri btn-sm" @click="transition('close')">验收通过 · 闭环</button>
          <button v-if="wo.status === 'approving'" class="btn btn-out btn-sm" @click="transition('reject')">驳回</button>
        </template>
        <button class="btn btn-out btn-sm" @click="router.push('/work-orders')">返回</button>
      </div>
    </div>

    <!-- 审批流 / 判断流程可视化 -->
    <div class="card">
      <div class="card-hd"><h3>{{ wo.source_code === 'alert' ? '判断流程' : '审批流转' }}</h3></div>
      <div class="flow">
        <template v-for="(s, i) in flow.steps" :key="s.code">
          <div v-if="i > 0" class="flow-arrow" :class="{ done: s.state === 'done' }"></div>
          <div class="flow-step" :class="s.state">
            <div class="circle">{{ stepIcon(s.state, i) }}</div>
            <div class="label">{{ statusLabel(s.code) }}</div>
          </div>
        </template>
      </div>
      <div v-if="wo.oa_id" class="oa-link">关联OA审批单：<span class="clickable">{{ wo.oa_id }}</span></div>
    </div>

    <div class="grid2">
      <!-- 基本信息 -->
      <div class="card">
        <div class="card-hd"><h3>基本信息</h3></div>
        <div class="info-grid">
          <div class="lbl">来源</div><div class="val"><span class="src-tag" :class="sourceTagClass(wo.source_code)">{{ sourceLabel(wo.source_code) }}</span></div>
          <div class="lbl">优先级</div><div class="val"><span class="tag" :class="priorityTag(wo.priority)">{{ priorityLabel(wo.priority) }}</span></div>
          <div class="lbl">状态</div>
          <div class="val">
            <span class="tag" :class="statusTag(wo.status)">{{ statusLabel(wo.status) }}</span>
            <span v-if="wo.escalation_level > 0" class="tag" :class="escTag(wo.escalation_level)">{{ escLabel[wo.escalation_level] }}</span>
          </div>
          <div class="lbl">项目</div><div class="val">{{ wo.project_name || "—" }}</div>
          <div class="lbl">区域</div><div class="val">{{ wo.region || "—" }}</div>
          <div class="lbl">工单类型</div><div class="val">{{ wo.type_name || "—" }}</div>
          <div class="lbl">责任人</div>
          <div class="val" v-if="wo.status === 'pending' || wo.status === 'approving' || wo.status === 'judging'">
            <SearchableSelect :model-value="wo.person_id ?? undefined" :options="allUsers" placeholder="搜索姓名…" @update:model-value="(v: number | undefined) => savePerson('person_id', v)" />
          </div>
          <div class="val" v-else><b>{{ wo.person_name }}</b></div>
          <div class="lbl">审批人</div>
          <div class="val" v-if="wo.status === 'pending' || wo.status === 'approving' || wo.status === 'judging'">
            <SearchableSelect :model-value="wo.approver_id ?? undefined" :options="allUsers" placeholder="搜索姓名…" @update:model-value="(v: number | undefined) => savePerson('approver_id', v)" />
          </div>
          <div class="val" v-else>{{ wo.approver_name || "—" }}</div>
          <div class="lbl">计划开始</div><div class="val">{{ wo.planned_start_date || "—" }}</div>
          <div class="lbl">截止日期</div>
          <div class="val" :class="{ 'text-red': wo.status === 'overdue' }">
            {{ wo.deadline }}
            <span v-if="wo.status === 'overdue'" class="tag tag-red">超期{{ wo.overdue_days }}天</span>
          </div>
          <div class="lbl">创建时间</div><div class="val">{{ wo.created_date }}</div>
          <div class="lbl">OA单号</div><div class="val">{{ wo.oa_id || "—" }}</div>
          <div class="lbl">完成时间</div><div class="val">{{ wo.completed_date || "—" }}</div>
        </div>
      </div>

      <!-- 时间线 -->
      <div class="card">
        <div class="card-hd"><h3>时间线</h3></div>
        <div class="timeline">
          <div v-for="(lg, i) in logs" :key="lg.id" class="tl-item" :class="i === 0 ? 'active' : 'done'">
            <div class="tl-title">{{ lg.note || `${statusLabel(lg.from_status || '')} → ${statusLabel(lg.to_status)}` }}</div>
            <div class="tl-time">{{ formatTime(lg.created_at) }} · {{ lg.operator_name || "系统" }}</div>
          </div>
          <div v-if="!logs.length" class="tl-empty">暂无流转记录（状态流转时自动记录）</div>
        </div>
      </div>
    </div>

    <!-- 工单详情 -->
    <div class="card">
      <div class="card-hd"><h3>工单详情</h3></div>
      <div class="detail-blocks">
        <div class="detail-block">
          <label>触发原因</label>
          <div class="detail-val">{{ wo.reason || "—" }}</div>
        </div>
        <div class="detail-block">
          <label>行动要求</label>
          <div class="detail-val">{{ wo.action || "—" }}</div>
        </div>
        <div class="detail-block" v-if="wo.conclusion">
          <label>执行结论</label>
          <div class="detail-val conclusion">{{ wo.conclusion }}</div>
        </div>
      </div>
    </div>

    <!-- 回填 · alert来源始终显示；其他来源在派发后显示 -->
    <div class="card" v-if="wo.status !== 'closed' && (wo.source_code === 'alert' || (wo.status !== 'pending' && wo.status !== 'approving'))">
      <div class="card-hd"><h3>回填 · 原因与措施</h3>
        <span v-if="wo.source_code === 'alert'" class="badge-alert">监视告警</span>
      </div>
      <div v-if="backfill.work_order_id">
        <!-- 已回填内容展示 -->
        <div class="backfill-status" v-if="backfill.reason || backfill.action">
          <div class="detail-block">
            <label>根因分析</label>
            <div class="detail-val">{{ backfill.reason || "—" }}</div>
          </div>
          <div class="detail-block">
            <label>应对措施</label>
            <div class="detail-val">{{ backfill.action || "—" }}</div>
          </div>
          <div class="detail-block" v-if="backfill.triggered_wo_id">
            <label>触发新工单</label>
            <div class="detail-val">
              <span class="clickable" @click="$router.push(`/work-orders/${backfill.triggered_wo_id}`)">
                {{ backfill.triggered_wo_code || backfill.triggered_wo_id }}
              </span>
            </div>
          </div>
          <!-- 多措施工单链接 -->
          <div class="detail-block" v-if="wo.triggered_wo_tasks && Array.isArray(wo.triggered_wo_tasks) && wo.triggered_wo_tasks.length > 0 && wo.triggered_wo_tasks[0].code">
            <label>已生成措施工单</label>
            <div class="detail-val">
              <div v-for="(t, i) in wo.triggered_wo_tasks" :key="i" style="margin-bottom:4px">
                <span class="clickable" @click="$router.push('/work-orders/' + t.id)">
                  {{ t.code }}
                </span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="empty-backfill">尚未回填</div>
      </div>

      <!-- 判断Agent 导出/导入（alert 待回填阶段显示） -->
      <div v-if="wo.source_code === 'alert' && wo.status === 'pending'" class="judgment-toolbar">
        <div class="judgment-toolbar-title">🤖 判断Agent（离线协作）</div>
        <div class="judgment-toolbar-desc">
          ① 导出 → ② Agent归因分析 → ③ 导入结果自动回填
        </div>
        <div class="judgment-toolbar-actions">
          <button class="btn btn-out btn-sm" @click="handleExportJudgment">📥 导出</button>
          <button class="btn btn-pri btn-sm" @click="triggerImport" :disabled="importing">
            {{ importing ? '导入中…' : '📤 导入Agent结果' }}
          </button>
          <input ref="importFileInput" type="file" accept=".json,.html,.htm" style="display:none" @change="handleImportJudgment" />
        </div>
        <div v-if="importError" class="judgment-import-error">{{ importError }}</div>
        <div v-if="importSuccess" class="judgment-import-success">{{ importSuccess }}</div>
      </div>

      <!-- 待回填阶段：编辑表单 -->
      <div v-if="wo.source_code !== 'alert' || wo.status === 'pending'" class="backfill-form">
        <div class="form-group">
          <label>根因分析</label>
          <textarea v-model="bfForm.reason" placeholder="分析异常/事项的根本原因"></textarea>
        </div>
        <div class="form-group">
          <label>应对措施</label>
          <textarea v-model="bfForm.action" placeholder="采取了什么措施、达到什么效果"></textarea>
        </div>
        <div class="form-actions">
          <button class="btn btn-pri" @click="submitBackfill" :disabled="bfSubmitting">
            {{ bfSubmitting ? '提交中…' : '提交回填' }}
          </button>
        </div>
      </div>

      <!-- 已回填阶段：多措施工单配置（每条可展开） -->
      <div v-if="wo.source_code === 'alert' && wo.status === 'judging'" class="measure-wo-form">
        <div class="measure-wo-title">📋 措施工单（可多个，点击展开查看详情）</div>
        <div v-for="(t, i) in measureTasks" :key="i" class="measure-task-card">
          <div class="task-card-header" @click="t.expanded = !t.expanded">
            <span class="task-idx">{{ i + 1 }}</span>
            <span class="task-title-preview">{{ t.title || '（未填写标题）' }}</span>
            <span class="task-expand-icon">{{ t.expanded ? '▲' : '▼' }}</span>
          </div>
          <div class="task-card-body" v-show="t.expanded">
            <div class="form-group">
              <label>工单标题</label>
              <input v-model="t.title" placeholder="措施工单标题" />
            </div>
            <div class="form-group">
              <label>工单类型</label>
              <select v-model="t.type_id">
                <option :value="null">请选择工单类型</option>
                <option v-for="tp in woTypes" :key="tp.id" :value="tp.id">{{ tp.name }}</option>
              </select>
            </div>
            <div class="form-group">
              <label>触发原因</label>
              <textarea v-model="t.reason" :placeholder="'由 ' + wo.code + ' 触发。' + (backfill.reason || '')" rows="2"></textarea>
            </div>
            <div class="form-group">
              <label>行动要求</label>
              <textarea v-model="t.action" :placeholder="backfill.action || '应对措施'" rows="2"></textarea>
            </div>
            <div class="task-card-meta">
              <input v-model="t.person_name" placeholder="责任人" class="task-person" />
              <input type="date" v-model="t.deadline" class="task-deadline" />
            </div>
            <button class="btn btn-out btn-sm" @click="measureTasks.splice(i, 1)" :disabled="measureTasks.length <= 1">✕ 删除</button>
          </div>
        </div>
        <button class="btn btn-out btn-sm" @click="addMeasureTask()" style="margin-top:8px">
          ＋ 添加工单
        </button>
        <div class="form-actions" style="margin-top:12px">
          <button class="btn btn-out btn-sm" @click="saveMeasureTasks" :disabled="savingTasks">
            {{ savingTasks ? '保存中…' : '💾 保存草稿' }}
          </button>
        </div>
      </div>

      <!-- 判断Agent 结果（导入后显示） -->
      <div v-if="backfill.verdict || wo.judgment_status" class="judgment-result" :class="'judgment-' + ((backfill.verdict || wo.judgment_status) || '')">
          <div class="judgment-header">
            <span class="judgment-icon">{{ verdictIcon((backfill.verdict || wo.judgment_status) || '') }}</span>
            <span class="judgment-title">{{ verdictLabel((backfill.verdict || wo.judgment_status) || '') }}</span>
            <span v-if="backfill.judgment_confidence != null" class="judgment-confidence">
              置信度 {{ (backfill.judgment_confidence * 100).toFixed(0) }}%
            </span>
          </div>
          <div v-if="backfill.judgment_reasoning" class="judgment-reasoning">
            {{ backfill.judgment_reasoning }}
          </div>
          <div v-if="backfill.judgment_suggestions" class="judgment-suggestions">
            <div class="suggestion-title">💡 调整建议：</div>
            <ul>
              <li v-if="backfill.judgment_suggestions.title">标题：{{ backfill.judgment_suggestions.title }}</li>
              <li v-if="backfill.judgment_suggestions.priority">优先级：{{ backfill.judgment_suggestions.priority }}</li>
              <li v-if="backfill.judgment_suggestions.person_name">责任人：{{ backfill.judgment_suggestions.person_name }}</li>
              <li v-if="backfill.judgment_suggestions.deadline">截止时间：{{ backfill.judgment_suggestions.deadline }}</li>
              <li v-if="backfill.judgment_suggestions.action_adjustment">措施补充：{{ backfill.judgment_suggestions.action_adjustment }}</li>
            </ul>
          </div>
          <div v-if="backfill.verdict === 'rejected'" class="judgment-actions">
            <button class="btn btn-out btn-sm" @click="bfForm.reason = ''; bfForm.action = ''; backfill = {} as any">
              重新回填
            </button>
          </div>
        </div>
    </div>
  </div>
  <div v-else class="loading">加载中…</div>

  <!-- 派发确认弹窗 -->
  <div v-if="showDispatchConfirm" class="modal-mask" @click.self="showDispatchConfirm = false">
    <div class="modal-card">
      <h3>确认发起 OA 审批</h3>
      <div class="modal-body">
        <div class="confirm-row"><span class="confirm-lbl">工单编号</span><span class="confirm-val">{{ wo?.code }}</span></div>
        <div class="confirm-row"><span class="confirm-lbl">项目名称</span><span class="confirm-val">{{ wo?.project_name }}</span></div>
        <div class="confirm-row"><span class="confirm-lbl">工单类型</span><span class="confirm-val">{{ wo?.type_name }}</span></div>
        <div class="confirm-row"><span class="confirm-lbl">触发原因</span><span class="confirm-val">{{ wo?.reason || '—' }}</span></div>
        <div class="confirm-row"><span class="confirm-lbl">行动要求</span><span class="confirm-val">{{ wo?.action || '—' }}</span></div>
        <div class="confirm-row di-edit">
          <span class="confirm-lbl">责任人</span>
          <SearchableSelect :model-value="dispatchPersonId" :options="allUsers" placeholder="搜索姓名…" @update:model-value="(v: number | undefined) => dispatchPersonId = v" />
        </div>
        <div class="confirm-row di-edit">
          <span class="confirm-lbl">审批人</span>
          <SearchableSelect :model-value="dispatchApproverId" :options="allUsers" placeholder="搜索姓名…" @update:model-value="(v: number | undefined) => dispatchApproverId = v" />
        </div>
        <div class="confirm-row"><span class="confirm-lbl">截止时间</span><span class="confirm-val">{{ wo?.deadline }}</span></div>
      </div>
      <div class="modal-actions">
        <button class="btn btn-out" @click="showDispatchConfirm = false">取消</button>
        <button class="btn btn-pri" @click="confirmDispatch" :disabled="dispatching">
          {{ dispatching ? '发起中…' : '确认发起' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getWorkOrder, getStatusLogs, transitionWorkOrder, updateWorkOrder, type WorkOrder, type StatusLog } from "@/api/workorders";
import { backfillWO, getBackfill, type BackfillResult, exportJudgment, importJudgment } from "@/api/pool";
import { importAgentHtml } from "@/api/imports";
import { getWoTypes, getUsersAll } from "@/api/config";
import SearchableSelect from "@/components/SearchableSelect.vue";
import {
  statusLabel, statusTag, priorityLabel, priorityTag,
  sourceLabel, sourceTagClass, escLabel, escTag, flowProgress,
} from "@/utils/wo-display";

const route = useRoute();
const router = useRouter();
const wo = ref<WorkOrder | null>(null);
const logs = ref<StatusLog[]>([]);
const backfill = ref<Partial<BackfillResult>>({});
const bfSubmitting = ref(false);
const showDispatchConfirm = ref(false);
const dispatching = ref(false);
const dispatchPersonId = ref<number | undefined>(undefined);
const dispatchApproverId = ref<number | undefined>(undefined);
const importFileInput = ref<HTMLInputElement | null>(null);
const importError = ref("");
const importSuccess = ref("");
const importing = ref(false);
const allUsers = ref<any[]>([]);
const woTypes = ref<any[]>([]);
const bfForm = reactive({
  reason: "",
  action: "",
  trigger_new_wo: false,
  new_wo_title: "",
  new_wo_deadline: "",
  new_wo_person_name: "",
});

interface MeasureTask {
  title: string;
  person_name: string;
  deadline: string;
  reason: string;
  action: string;
  type_id: number | null;
  expanded: boolean;
}
const measureTasks = ref<MeasureTask[]>([]);

const flow = computed(() => flowProgress(
  wo.value?.status ?? "pending",
  wo.value?.source_code,
  !!(backfill.value?.reason || backfill.value?.action),
));

function stepIcon(state: string, i: number): string {
  if (state === "done") return "✓";
  if (state === "active") return "●";
  if (state === "warn") return "⚠";
  return "○";
}

function formatTime(iso: string): string {
  return iso.replace("T", " ").slice(0, 16);
}

function verdictIcon(v: string): string {
  const m: Record<string, string> = {
    approved_suggested: "✅",
    approved_as_is: "✅",
    rejected: "❌",
    no_action_needed: "⏭️",
    degraded: "⚠️",
  };
  return m[v] || "🤖";
}

function verdictLabel(v: string): string {
  const m: Record<string, string> = {
    approved_suggested: "判定通过（有建议）",
    approved_as_is: "判定通过",
    rejected: "判定驳回",
    no_action_needed: "无需措施工单",
    degraded: "判断Agent不可用，已降级处理",
  };
  return m[v] || v;
}

async function load() {
  const id = Number(route.params.id);
  const [w, lg, u, wt] = await Promise.all([getWorkOrder(id), getStatusLogs(id), getUsersAll(), getWoTypes()]);
  wo.value = w;
  logs.value = lg;
  allUsers.value = u;
  woTypes.value = wt;
  try { backfill.value = await getBackfill(id); } catch { /* 回填可能为空 */ }
  // 初始化措施工单任务列表
  if (w.source_code === 'alert') {
    const tasks = (w as any).triggered_wo_tasks;
    if (Array.isArray(tasks) && tasks.length > 0) {
      measureTasks.value = tasks.map((t: any) => ({
        title: t.title || '',
        person_name: t.person_name || '',
        deadline: t.deadline || '',
        reason: t.reason || `由 ${w.code} 触发`,
        action: t.action || '',
        type_id: t.type_id ?? null,
        expanded: false,
      }));
    } else {
      measureTasks.value = [{
        title: '', person_name: '', deadline: '',
        reason: `由 ${w.code} 触发`,
        action: '',
        type_id: null,
        expanded: true,
      }];
    }
  }
}

async function submitBackfill() {
  if (!wo.value) return;
  bfSubmitting.value = true;
  try {
    backfill.value = await backfillWO(wo.value.id, {
      reason: bfForm.reason,
      action: bfForm.action,
      trigger_new_wo: bfForm.trigger_new_wo,
      new_wo_title: bfForm.new_wo_title || undefined,
      new_wo_deadline: bfForm.new_wo_deadline || undefined,
      new_wo_person_name: bfForm.new_wo_person_name || undefined,
    });
    await load();
    bfForm.reason = "";
    bfForm.action = "";
    bfForm.trigger_new_wo = false;
    bfForm.new_wo_title = "";
    bfForm.new_wo_deadline = "";
    bfForm.new_wo_person_name = "";
  } catch (e: any) {
    alert("回填失败：" + e.message);
  } finally {
    bfSubmitting.value = false;
  }
}

async function transition(action: string) {
  if (!wo.value) return;
  try {
    wo.value = await transitionWorkOrder(wo.value.id, action);
    logs.value = await getStatusLogs(wo.value.id);
  } catch (e: any) {
    alert(e.message);
  }
}

const savingTasks = ref(false);

function addMeasureTask() {
  measureTasks.value.push({
    title: '',
    person_name: '',
    deadline: '',
    reason: wo.value ? `由 ${wo.value.code} 触发` : '',
    action: backfill.value?.action || '',
    type_id: null,
    expanded: true,
  });
}

async function saveMeasureTasks() {
  if (!wo.value) return;
  savingTasks.value = true;
  try {
    // 过滤空任务
    const tasks = measureTasks.value.filter(t => t.title.trim())
      .map(({ expanded, ...rest }) => ({ ...rest, type_id: rest.type_id ? rest.type_id : null }));
    if (tasks.length === 0) {
      alert("请先填写措施工单标题再保存草稿");
      return;
    }
    await updateWorkOrder(wo.value.id, { triggered_wo_tasks: tasks });
    await load();
  } catch (e: any) {
    alert("保存失败：" + e.message);
  } finally {
    savingTasks.value = false;
  }
}

async function dispatchMeasure() {
  if (!wo.value) return;
  // 先保存任务
  const tasks = measureTasks.value.filter(t => t.title.trim())
    .map(({ expanded, ...rest }) => ({ ...rest, type_id: rest.type_id ? rest.type_id : null }));
  if (tasks.length === 0) {
    alert("请至少添加一个措施工单");
    return;
  }
  savingTasks.value = true;
  try {
    await updateWorkOrder(wo.value.id, { triggered_wo_tasks: tasks });
  } catch { /* ignore */ }
  savingTasks.value = false;
  // 执行派发
  await transition("dispatch_measure");
  await load();
}

async function openDispatchConfirm() {
  dispatchPersonId.value = wo.value?.person_id ?? undefined;
  dispatchApproverId.value = wo.value?.approver_id ?? undefined;
  showDispatchConfirm.value = true;
}

async function confirmDispatch() {
  dispatching.value = true;
  try {
    // 如果责任人/审批人变了，先更新
    if (dispatchPersonId.value !== wo.value?.person_id || dispatchApproverId.value !== wo.value?.approver_id) {
      await updateWorkOrder(wo.value!.id, {
        person_id: dispatchPersonId.value,
        approver_id: dispatchApproverId.value,
      });
    }
    await transition("dispatch");
    showDispatchConfirm.value = false;
  } catch (e: any) {
    alert("派发失败：" + (e.message || "未知错误"));
  } finally {
    dispatching.value = false;
  }
}

async function handleExportJudgment() {
  if (!wo.value) return;
  try {
    const blob = await exportJudgment(wo.value.id) as any;
    const url = window.URL.createObjectURL(new Blob([blob]));
    const a = document.createElement("a");
    a.href = url;
    a.download = `judgment_export_${wo.value.code}.json`;
    a.click();
    window.URL.revokeObjectURL(url);
  } catch (e: any) {
    alert("导出失败：" + (e.message || "未知错误"));
  }
}

function triggerImport() {
  importFileInput.value?.click();
}

async function handleImportJudgment(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || !wo.value) return;

  importError.value = "";
  importSuccess.value = "";
  importing.value = true;
  try {
    const text = await file.text();

    // HTML（荣的「指标异常处置SOP」复盘报告）→ 走批次导入，创建多张工单
    const isHtml = /\.html?$/i.test(file.name) || /^\s*</.test(text);
    if (isHtml) {
      const result = await importAgentHtml(text);
      if (result.already_imported) {
        importSuccess.value = result.message || "该批次已导入过，跳过";
      } else {
        importSuccess.value =
          `已导入 ${result.created} 张工单（${result.project || ""}／${result.trigger?.indicator || ""}）` +
          `${result.skipped_duplicate ? "，跳过 " + result.skipped_duplicate + " 个重复" : ""}。` +
          "已生成一条「异常指标」工单并进入判断流程，请在工单列表点进详情人工选择工单类型后生成措施工单。";
      }
      await load();
      return;
    }

    // JSON（原判断Agent回填流程）
    const data = JSON.parse(text);

    const result = await importJudgment(wo.value.id, data);

    // 自动填入回填表单
    if (result.backfill_reason) bfForm.reason = result.backfill_reason;
    if (result.backfill_action) bfForm.action = result.backfill_action;
    if (result.triggered_wo_title) bfForm.new_wo_title = result.triggered_wo_title;
    if (result.triggered_wo_deadline) bfForm.new_wo_deadline = result.triggered_wo_deadline;
    if (result.triggered_wo_person_name) bfForm.new_wo_person_name = result.triggered_wo_person_name;

    // 刷新回填数据和工单状态
    await load();

    importSuccess.value = 'Agent结果已导入，回填表单已自动填充。请审核后勾选「生成新工单」提交。';
  } catch (e: any) {
    importError.value = "导入失败：" + (e.message || "JSON解析错误");
  } finally {
    importing.value = false;
    input.value = "";
  }
}

async function savePerson(field: "person_id" | "approver_id", userId: number | undefined) {
  if (!wo.value || !userId) return;
  try {
    await updateWorkOrder(wo.value.id, { [field]: userId });
    await load();
  } catch (e: any) {
    alert("保存失败：" + e.message);
  }
}

onMounted(load);
</script>

<style scoped>
.wo-detail .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; gap: 16px; flex-wrap: wrap; }
.header h1 { font-size: 20px; font-weight: 700; }
.meta { font-size: 12px; color: var(--muted); margin-top: 4px; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }

.card { background: var(--card); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow); margin-bottom: 16px; }
.card-hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.card-hd h3 { font-size: 15px; font-weight: 700; }
.badge-alert { font-size: 10px; padding: 2px 6px; background: #fee2e2; color: #991b1b; border-radius: 4px; font-weight: 600; }

.flow { display: flex; align-items: center; padding: 16px 0; flex-wrap: wrap; }
.flow-step { display: flex; flex-direction: column; align-items: center; min-width: 80px; }
.flow-step .circle { width: 28px; height: 28px; border-radius: 50%; border: 2px solid #d1d5db; background: #fff; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; margin-bottom: 4px; }
.flow-step.done .circle { background: var(--green); border-color: var(--green); color: #fff; }
.flow-step.active .circle { background: var(--brand); border-color: var(--brand); color: #fff; }
.flow-step.warn .circle { background: var(--amber); border-color: var(--amber); color: #fff; }
.flow-step .label { font-size: 10px; text-align: center; color: var(--muted); max-width: 70px; }
.flow-arrow { width: 24px; height: 2px; background: #d1d5db; margin: 0 0 20px; }
.flow-arrow.done { background: var(--green); }
.oa-link { text-align: center; font-size: 12px; color: var(--muted); margin-top: 4px; }

.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.info-grid { display: grid; grid-template-columns: 100px 1fr 100px 1fr; gap: 1px; background: var(--border); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.info-grid .lbl { background: #f8fafc; padding: 8px 12px; font-size: 11px; font-weight: 600; color: var(--muted); }
.info-grid .val { background: #fff; padding: 8px 12px; font-size: 13px; }
.text-red { color: var(--red); }

.timeline { position: relative; padding-left: 24px; }
.timeline::before { content: ""; position: absolute; left: 8px; top: 4px; bottom: 4px; width: 2px; background: #e5e7eb; }
.tl-item { position: relative; margin-bottom: 14px; }
.tl-item::before { content: ""; position: absolute; left: -20px; top: 4px; width: 10px; height: 10px; border-radius: 50%; border: 2px solid #d1d5db; background: #fff; }
.tl-item.done::before { background: var(--green); border-color: var(--green); }
.tl-item.active::before { background: var(--brand); border-color: var(--brand); }
.tl-title { font-weight: 600; font-size: 13px; }
.tl-time { font-size: 11px; color: var(--muted); }
.tl-empty { color: var(--muted); font-size: 12px; padding: 12px 0; }

.detail-blocks { display: flex; flex-direction: column; gap: 14px; }
.detail-block label { display: block; font-size: 12px; font-weight: 600; color: #4b5563; margin-bottom: 6px; }
.detail-val { padding: 10px; background: #f8fafc; border-radius: 6px; font-size: 13px; line-height: 1.6; }
.detail-val.conclusion { background: #ecfdf5; }

.tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; white-space: nowrap; }
.src-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; }
.tag-blue { background: #eff6ff; color: var(--brand); }
.tag-green { background: #ecfdf5; color: var(--green); }
.tag-amber { background: #fffbeb; color: var(--amber); }
.tag-red { background: #fef2f2; color: var(--red); }
.tag-gray { background: #f3f4f6; color: #6b7280; }
.src-plan { background: #dbeafe; color: #1e40af; }
.src-alert { background: #fee2e2; color: #991b1b; }
.src-meeting { background: #fef3c7; color: #92400e; }
.src-manual { background: #e0e7ff; color: #3730a3; }
.clickable { cursor: pointer; color: var(--brand); }
.clickable:hover { text-decoration: underline; }

.btn { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-pri { background: var(--brand); color: #fff; }
.btn-pri:hover { background: var(--brand-dark); }
.btn-out { background: #fff; color: #4b5563; border: 1px solid var(--border); }
.btn-out:hover { background: #f9fafb; }
.btn-sm { padding: 4px 10px; font-size: 11px; }
.loading { text-align: center; padding: 60px; color: var(--muted); }

/* 回填 */
.backfill-status { margin-bottom: 14px; }
.empty-backfill { color: var(--muted); font-size: 13px; padding: 10px 0; }
.backfill-form { border-top: 1px solid var(--border); padding-top: 14px; }
.backfill-form .form-group { margin-bottom: 12px; }
.backfill-form label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.backfill-form textarea { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; resize: vertical; min-height: 60px; }
.checkbox-label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px !important; font-weight: 400 !important; }
.trigger-extra { margin-top: 8px; display: flex; gap: 8px; }
.trigger-extra input { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; }
.form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }


@media (max-width: 900px) { .grid2 { grid-template-columns: 1fr; } .info-grid { grid-template-columns: 90px 1fr; } }

/* 确认弹窗 */
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-card { background: #fff; border-radius: 12px; padding: 24px; width: 520px; max-width: 90vw; box-shadow: 0 8px 30px rgba(0,0,0,.15); }
.modal-card h3 { font-size: 16px; font-weight: 700; margin-bottom: 16px; }
.modal-body { margin-bottom: 20px; }
.confirm-row { display: flex; padding: 6px 0; border-bottom: 1px solid #f3f4f6; font-size: 13px; }
.confirm-lbl { width: 80px; color: var(--muted); flex-shrink: 0; }
.confirm-val { flex: 1; }
.confirm-row.di-edit { align-items: center; padding: 8px 0; border-top: 1px solid var(--border); margin-top: 4px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }

/* 判断Agent 导出/导入工具栏 */
.judgment-toolbar { margin-top: 16px; padding: 14px; background: #f8fafc; border-radius: 8px; border: 1px dashed #cbd5e1; }
.judgment-toolbar-title { font-weight: 700; font-size: 14px; margin-bottom: 4px; }
.judgment-toolbar-desc { font-size: 12px; color: var(--muted); margin-bottom: 10px; }
.judgment-toolbar-actions { display: flex; gap: 8px; }
.judgment-import-error { margin-top: 8px; padding: 8px; background: #fef2f2; color: var(--red); border-radius: 6px; font-size: 12px; }
.judgment-import-success { margin-top: 8px; padding: 8px; background: #f0fdf4; color: var(--green); border-radius: 6px; font-size: 12px; }

/* 判定中阶段：措施工单配置 */
.measure-wo-form { margin-top: 14px; padding: 14px; background: #f0fdf4; border-radius: 8px; border: 1px solid #86efac; }
.measure-wo-title { font-weight: 700; font-size: 13px; margin-bottom: 10px; }
.measure-wo-form .form-group { margin-bottom: 10px; }
.measure-wo-form label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.measure-wo-form input { width: 100%; padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }

/* 措施工单可展开卡片 */
.measure-task-card { background: #fff; border-radius: 8px; border: 1px solid #e5e7eb; margin-bottom: 8px; overflow: hidden; }
.task-card-header { display: flex; align-items: center; gap: 8px; padding: 10px 12px; cursor: pointer; background: #f9fafb; }
.task-card-header:hover { background: #f3f4f6; }
.task-card-header .task-idx { width: 22px; height: 22px; border-radius: 50%; background: var(--brand); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.task-title-preview { flex: 1; font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-expand-icon { font-size: 11px; color: var(--muted); flex-shrink: 0; }
.task-card-body { padding: 12px; border-top: 1px solid #e5e7eb; }
.task-card-body .form-group { margin-bottom: 8px; }
.task-card-body label { display: block; font-size: 11px; font-weight: 600; color: var(--muted); margin-bottom: 3px; }
.task-card-body input, .task-card-body textarea, .task-card-body select { width: 100%; padding: 6px 8px; border: 1px solid #e5e7eb; border-radius: 4px; font-size: 12px; }
.task-card-body textarea { resize: vertical; min-height: 40px; }
.task-card-meta { display: flex; gap: 8px; margin-bottom: 8px; }
.task-card-meta input { flex: 1; }

/* 判断Agent 结果 */
.judgment-result { margin-top: 16px; padding: 14px; border-radius: 8px; border: 1px solid; }
.judgment-approved_suggested, .judgment-approved_as_is { background: #f0fdf4; border-color: #86efac; }
.judgment-rejected { background: #fef2f2; border-color: #fca5a5; }
.judgment-no_action_needed { background: #f8fafc; border-color: #d1d5db; }
.judgment-degraded { background: #fffbeb; border-color: #fcd34d; }
.judgment-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.judgment-icon { font-size: 18px; }
.judgment-title { font-weight: 700; font-size: 14px; }
.judgment-confidence { margin-left: auto; font-size: 11px; color: var(--muted); background: #fff; padding: 2px 8px; border-radius: 10px; }
.judgment-reasoning { font-size: 13px; line-height: 1.6; color: #4b5563; margin-bottom: 8px; }
.judgment-suggestions { background: #fff; padding: 10px; border-radius: 6px; }
.judgment-suggestions .suggestion-title { font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.judgment-suggestions ul { margin: 0; padding-left: 16px; font-size: 12px; }
.judgment-suggestions li { margin-bottom: 2px; color: #4b5563; }
.judgment-actions { margin-top: 10px; display: flex; justify-content: flex-end; }
</style>

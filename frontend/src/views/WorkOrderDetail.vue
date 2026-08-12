<template>
  <div class="wo-detail" v-if="wo">
    <div class="header">
      <div>
        <h1>{{ wo.code }} — {{ wo.title }}</h1>
        <div class="meta"><span class="clickable" @click="router.push('/work-orders')">← 返回列表</span></div>
      </div>
      <div class="header-actions">
        <button v-if="wo.status === 'approving'" class="btn btn-pri btn-sm" @click="transition('dispatch')">派发 → 发起OA审批</button>
        <button v-if="wo.status === 'dispatched'" class="btn btn-pri btn-sm" @click="transition('start_exec')">开始执行</button>
        <button v-if="wo.status === 'executing'" class="btn btn-pri btn-sm" @click="transition('submit_evidence')">提交佐证 → 验收</button>
        <button v-if="wo.status === 'verifying'" class="btn btn-pri btn-sm" @click="transition('close')">验收通过 · 闭环</button>
        <button v-if="wo.status === 'approving'" class="btn btn-out btn-sm" @click="transition('reject')">驳回</button>
        <button class="btn btn-out btn-sm" @click="router.push('/work-orders')">返回</button>
      </div>
    </div>

    <!-- 审批流可视化 -->
    <div class="card">
      <div class="card-hd"><h3>审批流转</h3></div>
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
          <div class="lbl">工单类型</div><div class="val">{{ wo.type_name || "—" }}</div>
          <div class="lbl">责任人</div><div class="val"><b>{{ wo.person_name }}</b></div>
          <div class="lbl">审批人</div><div class="val">{{ wo.approver_name || "—" }}</div>
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

    <!-- SOP 知识库 -->
    <div class="card" v-if="sop">
      <div class="card-hd"><h3>📋 SOP · {{ sop.name }}</h3><span class="count" v-if="sop.guidance_ref">{{ sop.guidance_ref }}</span></div>
      <div class="sop-body">
        <div class="sop-section" v-if="sop.sop_purpose">
          <label>目的</label>
          <div class="sop-text">{{ sop.sop_purpose }}</div>
        </div>
        <div class="sop-section" v-if="sop.sop_scope">
          <label>流程</label>
          <div class="sop-text">{{ sop.sop_scope }}</div>
        </div>
        <div class="sop-section" v-if="sop.sop_steps?.length">
          <label>标准步骤</label>
          <div class="sop-steps">
            <div v-for="s in sop.sop_steps" :key="s.step" class="sop-step">
              <span class="step-num">{{ s.step }}</span>
              <div>
                <div class="step-action">{{ s.action }}</div>
                <div class="step-standard">标准：{{ s.standard }}</div>
                <div class="step-role">执行人：{{ s.role }}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="sop-section" v-if="sop.sop_acceptance">
          <label>验收标准</label>
          <div class="sop-text">{{ sop.sop_acceptance }}</div>
        </div>
        <div class="sop-section" v-if="sop.sop_related_guidance?.length">
          <label>关联指引</label>
          <div class="sop-related">
            <span v-for="r in sop.sop_related_guidance" :key="r.ref" class="sop-ref">{{ r.ref }} {{ r.title }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 回填（Phase 3.5） -->
    <div class="card" v-if="wo.status !== 'closed' && wo.status !== 'pending' && wo.status !== 'approving'">
      <div class="card-hd"><h3>回填 · 原因与措施</h3></div>
      <div v-if="backfill.work_order_id">
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
        </div>
        <div v-else class="empty-backfill">尚未回填</div>
      </div>
      <div class="backfill-form">
        <div class="form-group">
          <label>根因分析</label>
          <textarea v-model="bfForm.reason" placeholder="分析异常/事项的根本原因"></textarea>
        </div>
        <div class="form-group">
          <label>应对措施</label>
          <textarea v-model="bfForm.action" placeholder="采取了什么措施、达到什么效果"></textarea>
        </div>
        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="bfForm.trigger_new_wo" />
            措施需要生成新工单跟踪
          </label>
          <div v-if="bfForm.trigger_new_wo" class="trigger-extra">
            <input v-model="bfForm.new_wo_title" placeholder="新工单标题" />
            <input type="date" v-model="bfForm.new_wo_deadline" />
          </div>
        </div>
        <div class="form-actions">
          <button class="btn btn-pri" @click="submitBackfill" :disabled="bfSubmitting">
            {{ bfSubmitting ? '提交中…' : '提交回填' }}
          </button>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="loading">加载中…</div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getWorkOrder, getStatusLogs, transitionWorkOrder, type WorkOrder, type StatusLog } from "@/api/workorders";
import { backfillWO, getBackfill, type BackfillResult } from "@/api/pool";
import { getWoTypesFull } from "@/api/config";
import {
  statusLabel, statusTag, priorityLabel, priorityTag,
  sourceLabel, sourceTagClass, escLabel, escTag, flowProgress,
} from "@/utils/wo-display";

const route = useRoute();
const router = useRouter();
const wo = ref<WorkOrder | null>(null);
const logs = ref<StatusLog[]>([]);
const backfill = ref<Partial<BackfillResult>>({});
const sop = ref<any>(null);
const bfSubmitting = ref(false);
const bfForm = reactive({
  reason: "",
  action: "",
  trigger_new_wo: false,
  new_wo_title: "",
  new_wo_deadline: "",
});

const flow = computed(() => flowProgress(wo.value?.status ?? "pending"));

function stepIcon(state: string, i: number): string {
  if (state === "done") return "✓";
  if (state === "active") return "●";
  if (state === "warn") return "⚠";
  return "○";
}

function formatTime(iso: string): string {
  return iso.replace("T", " ").slice(0, 16);
}

async function load() {
  const id = Number(route.params.id);
  const [w, lg] = await Promise.all([getWorkOrder(id), getStatusLogs(id)]);
  wo.value = w;
  logs.value = lg;
  try { backfill.value = await getBackfill(id); } catch { /* 回填可能为空 */ }
  // 加载 SOP
  try {
    if (w.type_id) {
      const types = await getWoTypesFull();
      sop.value = types.find((t: any) => t.id === w.type_id) || null;
    }
  } catch { /* ignore */ }
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
    });
    await load();
    bfForm.reason = "";
    bfForm.action = "";
    bfForm.trigger_new_wo = false;
    bfForm.new_wo_title = "";
    bfForm.new_wo_deadline = "";
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

/* SOP */
.sop-body { padding: 4px 0; }
.sop-section { margin-bottom: 14px; }
.sop-section label { display: block; font-size: 12px; font-weight: 700; color: var(--brand); margin-bottom: 4px; }
.sop-text { padding: 10px; background: #f8fafc; border-radius: 6px; font-size: 13px; line-height: 1.6; }
.sop-steps { display: flex; flex-direction: column; gap: 8px; }
.sop-step { display: flex; gap: 10px; padding: 8px; background: #f8fafc; border-radius: 6px; }
.step-num { width: 24px; height: 24px; border-radius: 50%; background: var(--brand); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.step-action { font-size: 13px; font-weight: 600; }
.step-standard { font-size: 11px; color: var(--muted); }
.step-role { font-size: 11px; color: var(--amber); }
.sop-related { display: flex; flex-wrap: wrap; gap: 6px; }
.sop-ref { font-size: 11px; padding: 3px 8px; background: #eff6ff; color: var(--brand); border-radius: 4px; }

@media (max-width: 900px) { .grid2 { grid-template-columns: 1fr; } .info-grid { grid-template-columns: 90px 1fr; } }
</style>

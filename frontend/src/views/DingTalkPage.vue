<template>
  <div class="dingtalk-page">
    <div class="page-header">
      <div>
        <h1>钉钉集成</h1>
        <p class="meta">系统工单与钉钉OA审批双向同步 · 多通道通知</p>
      </div>
    </div>

    <!-- 集成状态总览 -->
    <div class="equal-row-4 status-row">
      <t-card class="status-card" :class="status.app_key ? 'ok' : 'warn'">
        <div class="status-head"><span class="s-icon">{{ status.app_key ? '✅' : '⚠️' }}</span> 应用凭证</div>
        <div class="status-val">{{ status.app_key ? '已配置' : '未配置' }}</div>
      </t-card>
      <t-card class="status-card" :class="status.oa_template ? 'ok' : 'warn'">
        <div class="status-head"><span class="s-icon">{{ status.oa_template ? '✅' : '⚠️' }}</span> OA审批模板</div>
        <div class="status-val">{{ status.oa_template ? '已配置' : '未配置' }}</div>
      </t-card>
      <t-card class="status-card" :class="status.agent ? 'ok' : 'warn'">
        <div class="status-head"><span class="s-icon">{{ status.agent ? '✅' : '⚠️' }}</span> 机器人Agent</div>
        <div class="status-val">{{ status.agent ? '已配置' : '未配置' }}</div>
      </t-card>
      <t-card class="status-card ok">
        <div class="status-head"><span class="s-icon">🔄</span> 回调地址</div>
        <div class="status-val mono">{{ callbackUrl }}</div>
      </t-card>
    </div>

    <!-- 流程图 -->
    <t-card title="🔗 工单 → 钉钉 同步流程" class="flow-card">
      <div class="flow-diagram">
        <div class="flow-node sys">
          <div class="fn-icon">📋</div>
          <div class="fn-title">系统创建工单</div>
          <div class="fn-sub">手动/听记/表格</div>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-node action">
          <div class="fn-icon">📤</div>
          <div class="fn-title">点「派发」</div>
          <div class="fn-sub">触发 OA 创建 + 通知</div>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-node ding">
          <div class="fn-icon">钉</div>
          <div class="fn-title">钉钉审批单</div>
          <div class="fn-sub">审批人钉钉收件</div>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-node action">
          <div class="fn-icon">✓/✗</div>
          <div class="fn-title">审批通过/驳回</div>
          <div class="fn-sub">在钉钉里操作</div>
        </div>
        <div class="flow-arrow">↩</div>
        <div class="flow-node sys">
          <div class="fn-icon">🔄</div>
          <div class="fn-title">回调更新状态</div>
          <div class="fn-sub">approving→dispatched</div>
        </div>
      </div>

      <t-divider />

      <div class="channels-grid">
        <div class="channel">
          <div class="ch-num">①</div>
          <div class="ch-name">工作通知消息卡片</div>
          <div class="ch-desc">派发时推给责任人钉钉「工作通知」，带「查看工单」按钮点开回系统</div>
          <t-tag theme="primary" size="small">send_work_notification</t-tag>
        </div>
        <div class="channel">
          <div class="ch-num">②</div>
          <div class="ch-name">群机器人 @</div>
          <div class="ch-desc">在配置的钉钉群发消息卡片 @责任人，群内可 @机器人 反向建单</div>
          <t-tag theme="warning" size="small">send_robot_group</t-tag>
        </div>
        <div class="channel">
          <div class="ch-num">③</div>
          <div class="ch-name">OA审批单 ★</div>
          <div class="ch-desc">工单字段映射到审批模板表单，审批人在钉钉审批，结果回调同步</div>
          <t-tag theme="success" size="small">create_oa_approval</t-tag>
        </div>
        <div class="channel">
          <div class="ch-num">④</div>
          <div class="ch-name">电话 DING</div>
          <div class="ch-desc">P1 紧急工单或 SLA 违约时电话强提醒升级</div>
          <t-tag theme="danger" size="small">send_phone_ding</t-tag>
        </div>
      </div>
    </t-card>

    <!-- 配置 + 测试 -->
    <t-row :gutter="16">
      <t-col :span="6" :lg="6">
        <t-card title="⚙️ 凭证配置" class="config-card">
          <div class="cfg-hint">
            以下凭证在 <code>backend/.env</code> 填写，改完重启后端即生效。<br />
            钉钉后台路径：开放平台 → 应用开发 → 企业内部应用 → 凭证与基础信息
          </div>
          <t-form label-align="top">
            <t-form-item label="DINGTALK_APP_KEY"><t-input :value="status.app_key ? '•••••（已配置）' : ''" placeholder="未配置" readonly /></t-form-item>
            <t-form-item label="DINGTALK_APP_SECRET"><t-input :value="status.app_secret ? '•••••（已配置）' : ''" placeholder="未配置" readonly /></t-form-item>
            <t-form-item label="DINGTALK_AGENT_ID"><t-input :value="status.agent ? '•••••（已配置）' : ''" placeholder="未配置" readonly /></t-form-item>
            <t-form-item label="DINGTALK_OA_TEMPLATE_ID"><t-input :value="status.oa_template ? '•••••（已配置）' : ''" placeholder="未配置" readonly /></t-form-item>
            <t-form-item label="DINGTALK_CORP_ID"><t-input :value="status.corp ? '•••••（已配置）' : ''" placeholder="未配置" readonly /></t-form-item>
          </t-form>
        </t-card>
      </t-col>
      <t-col :span="6" :lg="6">
        <t-card title="🧪 发送测试" class="test-card">
          <div class="cfg-hint">选一条工单，模拟派发，验证通知是否到钉钉（需先配置凭证）。</div>
          <t-form label-align="top">
            <t-form-item label="选择工单">
              <t-select v-model="testWoId" placeholder="选择待派发工单" :options="woOptions" />
            </t-form-item>
            <t-form-item label="通知事件">
              <t-select v-model="testEvent" :options="eventOptions" />
            </t-form-item>
          </t-form>
          <t-space>
            <t-button theme="primary" @click="sendTest" :loading="testing">发送测试通知</t-button>
            <t-button theme="default" variant="outline" @click="refreshStatus">刷新状态</t-button>
          </t-space>
          <t-alert v-if="testResult" :theme="testResult.ok ? 'success' : 'error'" :message="testResult.msg" style="margin-top:12px" />
        </t-card>
      </t-col>
    </t-row>

    <!-- OA 审批模板字段映射 -->
    <t-card title="📋 OA审批模板字段映射" class="mapping-card">
      <div class="cfg-hint">在钉钉后台创建审批模板时，表单字段命名为以下名称，系统会自动映射工单内容：</div>
      <t-table :data="fieldMapping" :columns="mappingCols" row-key="field" size="small" />
    </t-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import http from "@/api/http";

const status = ref({ app_key: false, app_secret: false, agent: false, oa_template: false, corp: false });
const testWoId = ref<number | undefined>(undefined);
const testEvent = ref("dispatch");
const testing = ref(false);
const testResult = ref<{ ok: boolean; msg: string } | null>(null);
const woOptions = ref<any[]>([]);
const eventOptions = [
  { label: "派发通知 (dispatch)", value: "dispatch" },
  { label: "未读24h (unread)", value: "unread" },
  { label: "SLA到期前 (sla_warn)", value: "sla_warn" },
  { label: "SLA违约 (sla_breach)", value: "sla_breach" },
];
const callbackUrl = "/api/dingtalk/oa/callback";

const fieldMapping = [
  { field: "工单编号", source: "work_order.code", example: "RW-2026-0001" },
  { field: "标题", source: "work_order.title", example: "变桨系统异响排查" },
  { field: "触发原因", source: "work_order.reason", example: "巡检发现异响" },
  { field: "行动要求", source: "work_order.action", example: "现场排查齿轮" },
  { field: "责任人", source: "work_order.person_name", example: "王小宁" },
  { field: "审批人", source: "work_order.approver_name", example: "金惠良" },
  { field: "截止日期", source: "work_order.deadline", example: "2026-08-15" },
];
const mappingCols = [
  { colKey: "field", title: "钉钉表单字段名" },
  { colKey: "source", title: "系统数据来源" },
  { colKey: "example", title: "示例值" },
];

const callbackUrlFull = `${location.origin}${callbackUrl}`;

async function refreshStatus() {
  try {
    const s = await http.get<any, any>("/dingtalk/status");
    status.value = s;
  } catch {
    status.value = { app_key: false, app_secret: false, agent: false, oa_template: false, corp: false };
  }
  // 待派发工单
  try {
    const r = await http.get<any, any>("/work-orders", { params: { status: "pending", page_size: 50 } });
    woOptions.value = r.items.map((w: any) => ({ label: `${w.code} · ${w.title}`, value: w.id }));
  } catch { /* ignore */ }
}

async function sendTest() {
  if (!testWoId.value) { testResult.value = { ok: false, msg: "请先选择工单" }; return; }
  testing.value = true;
  testResult.value = null;
  try {
    const r = await http.post<any, any>(`/work-orders/${testWoId.value}/notify`, null, { params: { event: testEvent.value } });
    testResult.value = { ok: true, msg: `已触发：发送 ${r.sent} 条，失败 ${r.failed} 条（未配置凭证时走 mock）` };
  } catch (e: any) {
    testResult.value = { ok: false, msg: e.message };
  } finally {
    testing.value = false;
  }
}

onMounted(refreshStatus);
</script>

<style scoped>
.dingtalk-page { display: flex; flex-direction: column; gap: 16px; }
.page-header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { color: var(--muted); font-size: var(--fs-meta); margin-top: 4px; }

.status-row .status-card { height: 88px; }
.status-card.ok { border-left: 3px solid var(--green); }
.status-card.warn { border-left: 3px solid var(--amber); }
.status-head { display: flex; align-items: center; gap: 6px; font-size: var(--fs-meta); color: var(--muted); }
.s-icon { font-size: 14px; }
.status-val { font-size: var(--fs-num); font-weight: 600; margin-top: 6px; }
.status-val.mono { font-size: var(--fs-tag); font-family: monospace; word-break: break-all; }

.flow-card .flow-diagram { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 12px 0; }
.flow-node { text-align: center; min-width: 110px; padding: 12px; border-radius: 8px; border: 1px solid var(--border); }
.flow-node.sys { background: var(--brand-light); border-color: var(--brand); }
.flow-node.action { background: #fff7e6; border-color: var(--amber); }
.flow-node.ding { background: #e6f7ff; border-color: #1890ff; }
.fn-icon { font-size: var(--fs-h1); }
.fn-title { font-size: var(--fs-body); font-weight: 600; margin-top: 4px; }
.fn-sub { font-size: var(--fs-tag); color: var(--muted); }
.flow-arrow { font-size: 18px; color: var(--muted); }

.channels-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.channel { padding: 14px; border: 1px solid var(--border); border-radius: 8px; }
.ch-num { font-size: 18px; font-weight: 700; color: var(--brand); }
.ch-name { font-size: var(--fs-body); font-weight: 600; margin: 4px 0; }
.ch-desc { font-size: var(--fs-meta); color: var(--muted); margin-bottom: 8px; line-height: 1.5; }

.cfg-hint { font-size: var(--fs-meta); color: var(--muted); background: #fafafa; padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; line-height: 1.6; }
.cfg-hint code { background: #f0f4ff; padding: 1px 5px; border-radius: 3px; }
@media (max-width: 900px) { .channels-grid { grid-template-columns: 1fr 1fr; } .flow-node { min-width: 90px; } }
</style>

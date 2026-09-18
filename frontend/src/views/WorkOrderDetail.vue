<template>
  <div class="wo-detail" v-if="wo">
    <div class="header">
      <div>
        <h1>{{ wo.code }} — {{ wo.title }}</h1>
        <div class="meta"><span class="clickable" @click="router.push('/work-orders')">← 返回列表</span></div>
      </div>
      <div class="header-actions">
        <!-- alert 主单五阶段按钮 -->
        <template v-if="isAnomalyHost">
          <button v-if="wo.alert_phase === 'confirming'" class="btn btn-pri btn-sm" :disabled="savingTasks" @click="confirmAnalysis">
            {{ savingTasks ? '处理中…' : '✅ 确认分析结果 → 生成措施工单' }}
          </button>
          <button v-if="wo.alert_phase === 'confirming'" class="btn btn-out btn-sm" @click="transition('close')">
            无需措施，直接闭环
          </button>
          <button v-if="wo.alert_phase === 'dispatching'" class="btn btn-pri btn-sm" @click="transition('dispatch_measures')">
            📤 派发措施工单
          </button>
          <button v-if="wo.alert_phase === 'reexamining'" class="btn btn-pri btn-sm" @click="transition('confirm_recovered')">
            ✅ 指标恢复 · 闭环
          </button>
          <button v-if="wo.alert_phase === 'reexamining'" class="btn btn-out btn-sm" @click="openRedispatch">
            ＋ 补派发措施工单
          </button>
        </template>
        <!-- 措施工单 / 普通工单标准按钮 -->
        <template v-else>
          <span v-if="oaDriven" class="oa-driving-hint">🔗 已由钉钉OA审批流驱动，请在钉钉OA审批中更改状态</span>
          <template v-else>
            <button v-if="wo.status === 'pending' || wo.status === 'approving'" class="btn btn-pri btn-sm" @click="openDispatchConfirm">派发 → 发起OA审批</button>
            <button v-if="wo.status === 'dispatched'" class="btn btn-pri btn-sm" @click="transition('start_exec')">开始执行</button>
            <button v-if="wo.status === 'executing'" class="btn btn-pri btn-sm" @click="transition('submit_evidence')">提交佐证 → 验收</button>
            <button v-if="wo.status === 'verifying'" class="btn btn-pri btn-sm" @click="transition('close')">验收通过 · 闭环</button>
            <button v-if="wo.status === 'approving'" class="btn btn-out btn-sm" @click="transition('reject')">驳回</button>
          </template>
        </template>
        <button class="btn btn-out btn-sm" :disabled="syncing" @click="syncOa">{{ syncing ? '同步中…' : '🔄 同步 OA' }}</button>
        <template v-if="isAdmin">
          <button class="btn btn-out btn-sm" @click="openBasicEdit">✏️ 编辑基本信息</button>
          <button class="btn btn-out btn-sm btn-danger" @click="removeWorkOrder">🗑 删除工单</button>
        </template>
        <button class="btn btn-out btn-sm" @click="router.push('/work-orders')">返回</button>
      </div>
    </div>

    <!-- 审批流 / 判断流程可视化 -->
    <div class="card">
      <div class="card-hd"><h3>{{ isAnomalyHost ? '五阶段闭环' : '审批流转' }}</h3>
        <span v-if="isAnomalyHost && wo.measure_progress" class="progress-hint">{{ wo.measure_progress.closed }}/{{ wo.measure_progress.total }} 措施已闭环</span></div>
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
      <div v-if="pollActive" class="oa-poll-hint">🔄 轮询同步已开启：每 15 秒自动拉取钉钉最新状态/附件，也可点「同步 OA」手动刷新</div>
    </div>

    <div class="grid2">
      <!-- 基本信息 -->
      <div class="card">
        <div class="card-hd"><h3>基本信息</h3></div>
        <div class="info-grid">
          <div class="lbl">工单类型</div><div class="val"><span class="src-tag" :class="sourceTagClass(wo.source_code)">{{ sourceLabel(wo.source_code) }}</span></div>
          <div class="lbl">优先级</div><div class="val"><span class="tag" :class="priorityTag(wo.priority)">{{ priorityLabel(wo.priority) }}</span></div>
          <div class="lbl">状态</div>
          <div class="val">
            <span class="tag" :class="statusTag(wo.status)">{{ isAnomalyHost && wo.alert_phase ? statusLabel(wo.alert_phase) : statusLabel(wo.status) }}</span>
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
        <div class="detail-block">
          <label>交付物</label>
          <div class="detail-val">{{ wo.task_deliverable || "—" }}</div>
        </div>
        <div class="detail-block" v-if="wo.conclusion">
          <label>执行结论</label>
          <div class="detail-val conclusion">{{ wo.conclusion }}</div>
        </div>
        <div class="detail-block" v-if="attachments.length">
          <label>执行附件</label>
          <div class="detail-val">
            <div v-for="a in attachments" :key="a.id" style="margin-bottom:2px">
              <a class="clickable" target="_blank"
                 :href="`/api/work-orders/${wo.id}/attachments/${a.id}/download`">📎 {{ a.filename }}</a>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 回填 · 仅 alert 来源显示（普通 OA 工单不需要回填，避免噪音） -->
    <div class="card" v-if="isAnomalyHost && wo.status !== 'closed'">
      <div class="card-hd"><h3>回填 · 原因与措施</h3>
        <span v-if="isAnomalyHost" class="badge-alert">监视告警</span>
      </div>
      <div v-if="backfill.work_order_id">
        <!-- 已回填内容展示 -->
        <div class="backfill-status" v-if="backfill.reason || backfill.action">
          <div class="detail-block">
            <label>根因分析</label>
            <div class="detail-val">{{ backfill.reason || "—" }}</div>
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

      <!-- 根因分析 + 措施工单列表（合并一步，避免「应对措施」另填一遍）：
           待回填(pending)填完点「提交回填」进入确认；确认(confirming)复核后用头部「确认分析结果」一键生成工单 -->
      <div v-if="isAnomalyHost && (wo.status === 'pending' || wo.alert_phase === 'confirming')" class="measure-wo-form">
        <div v-if="wo.status === 'pending'" class="form-group">
          <label>根因分析</label>
          <textarea v-model="bfForm.reason" placeholder="分析异常/事项的根本原因"></textarea>
        </div>

        <div class="measure-wo-title">📋 应对措施 — 措施工单（可分多条，点开填写）</div>
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
              <textarea v-model="t.reason" :placeholder="'由 ' + wo.code + ' 触发。' + (bfForm.reason || backfill.reason || '')" rows="2"></textarea>
            </div>
            <div class="form-group">
              <label>行动要求</label>
              <textarea v-model="t.action" placeholder="具体要做什么、达到什么标准" rows="2"></textarea>
            </div>
            <div class="form-group">
              <label>责任人 <span style="color:var(--red)">*</span></label>
              <SearchableSelect :model-value="t.person_id" :options="allUsers" placeholder="搜索姓名…" @update:model-value="(v: number | undefined) => t.person_id = v" />
            </div>
            <div class="form-group">
              <label>审批人 <span style="color:var(--red)">*</span></label>
              <SearchableSelect :model-value="t.approver_id" :options="allUsers" placeholder="搜索姓名…" @update:model-value="(v: number | undefined) => t.approver_id = v" />
            </div>
            <div class="form-group">
              <label>计划开始</label>
              <input type="date" v-model="t.planned_start_date" />
            </div>
            <div class="form-group">
              <label>计划完成</label>
              <input type="date" v-model="t.deadline" />
            </div>
            <button class="btn btn-out btn-sm" @click="measureTasks.splice(i, 1)" :disabled="measureTasks.length <= 1">✕ 删除</button>
          </div>
        </div>
        <button class="btn btn-out btn-sm" @click="addMeasureTask()" style="margin-top:8px">＋ 添加工单</button>

        <div class="form-actions" style="margin-top:12px">
          <button v-if="wo.status === 'pending'" class="btn btn-pri" @click="submitBackfill" :disabled="bfSubmitting">
            {{ bfSubmitting ? '提交中…' : '提交回填 → 进入分析确认' }}
          </button>
          <button v-else class="btn btn-out btn-sm" @click="saveMeasureTasks" :disabled="savingTasks">
            {{ savingTasks ? '保存中…' : '💾 保存草稿' }}
          </button>
        </div>
      </div>

      <!-- 判断Agent 导出/导入（alert 待回填阶段显示） -->
      <div v-if="isAnomalyHost && wo.status === 'pending'" class="judgment-toolbar">
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

      <!-- 已生成的措施工单（派发/跟踪/复核/已恢复阶段） -->
      <div class="card" v-if="isAnomalyHost && wo.alert_phase && ['dispatching', 'tracking', 'reexamining', 'recovered'].includes(wo.alert_phase) && wo.measure_progress && (wo.measure_progress.measures || []).length">
        <div class="card-hd"><h3>📋 措施工单（{{ wo.measure_progress.closed }}/{{ wo.measure_progress.total }} 已闭环）</h3></div>
        <div class="measure-list">
          <div v-for="m in wo.measure_progress.measures" :key="m.id" class="measure-row">
            <span class="measure-code clickable" @click="$router.push('/work-orders/' + m.id)">{{ m.code }}</span>
            <span class="measure-title">{{ m.title }}</span>
            <span class="tag" :class="statusTag(m.status)">{{ statusLabel(m.status) }}</span>
          </div>
        </div>
      </div>

      <!-- 相似异常主单（复用/合并）+ 发生记录 -->
      <div class="card" v-if="isAnomalyHost && wo.status !== 'closed'">
        <div class="card-hd"><h3>🔁 相似异常（同项目同类）</h3></div>
        <div v-if="similarHosts.length === 0" class="empty-backfill">暂无同项目同类的其它开着主单</div>
        <div v-for="h in similarHosts" :key="h.id" class="similar-row">
          <span class="measure-code clickable" @click="$router.push('/work-orders/' + h.id)">{{ h.code }}</span>
          <span class="measure-title">{{ h.title }}（{{ statusLabel(h.alert_phase || '') }} · {{ h.measure_progress.closed }}/{{ h.measure_progress.total }}）</span>
          <button class="btn btn-out btn-sm" @click="doMerge(h)">并入此单</button>
          <button class="btn btn-out btn-sm" @click="doReuse(h)">复用它的措施</button>
        </div>
        <div class="card-hd" style="margin-top:14px"><h4>📅 发生记录</h4></div>
        <div v-if="!(wo.occurrences || []).length" class="empty-backfill">暂无发生记录</div>
        <div v-for="o in (wo.occurrences || [])" :key="o.id" class="occ-row">
          <span class="occ-date">{{ o.occurred_at || '—' }}</span>
          <span class="measure-title">{{ o.indicator_type || '—' }}</span>
          <span class="occ-note">{{ o.note || '' }}</span>
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
  <PageError v-else-if="loadError" title="工单无法打开" :message="loadError" action-label="返回列表" @action="router.push('/work-orders')" />
  <div v-else class="loading">加载中…</div>

  <!-- 派发确认弹窗 -->
  <t-dialog v-model:visible="showDispatchConfirm" header="确认发起 OA 审批" width="560" :footer="false">
      <div class="modal-body">
        <div class="confirm-row"><span class="confirm-lbl">工单编号</span><span class="confirm-val">{{ wo?.code }}</span></div>
        <div class="confirm-row di-edit">
          <span class="confirm-lbl">项目名称</span>
          <t-select v-model="dispatchProjectId" placeholder="输入项目名称 / 编码搜索" filterable clearable :options="projectOptions" />
        </div>
        <div class="confirm-row di-edit">
          <span class="confirm-lbl">工单类型</span>
          <select v-model="dispatchTypeId" class="di-input di-select"><option :value="null">未选</option><option v-for="t in woTypes" :key="t.id" :value="t.id">{{ t.name }}</option></select>
        </div>
        <div class="confirm-row di-edit">
          <span class="confirm-lbl">触发原因</span>
          <textarea v-model="dispatchReason" class="di-input" placeholder="必填" rows="2"></textarea>
        </div>
        <div class="confirm-row di-edit">
          <span class="confirm-lbl">行动要求</span>
          <textarea v-model="dispatchAction" class="di-input" placeholder="必填" rows="2"></textarea>
        </div>
        <div class="confirm-row di-edit">
          <span class="confirm-lbl">责任人</span>
          <SearchableSelect :model-value="dispatchPersonId" :options="allUsers" placeholder="搜索姓名…" @update:model-value="(v: number | undefined) => dispatchPersonId = v" />
        </div>
        <div class="confirm-row di-edit">
          <span class="confirm-lbl">审批人</span>
          <SearchableSelect :model-value="dispatchApproverId" :options="allUsers" placeholder="搜索姓名…" @update:model-value="(v: number | undefined) => dispatchApproverId = v" />
        </div>
        <div class="confirm-row di-edit">
          <span class="confirm-lbl">任务目标交付物</span>
          <textarea v-model="dispatchDeliverable" class="di-input" placeholder="计划类必填：该传什么附件才能闭环" rows="2"></textarea>
        </div>
        <div class="confirm-row di-edit">
          <span class="confirm-lbl">计划开始时间</span>
          <input type="date" v-model="dispatchPlannedStart" class="di-input" />
        </div>
        <div class="confirm-row di-edit">
          <span class="confirm-lbl">截止时间</span>
          <input type="date" v-model="dispatchDeadline" class="di-input" />
        </div>
      </div>
      <div class="modal-actions">
        <t-button variant="outline" @click="showDispatchConfirm = false">取消</t-button>
        <t-button theme="primary" @click="confirmDispatch" :disabled="dispatching">
          {{ dispatching ? '发起中…' : '确认发起' }}
        </t-button>
      </div>
  </t-dialog>

  <!-- 补派发措施工单弹窗（阶段④指标异常） -->
  <t-dialog v-model:visible="showRedispatch" header="补派发措施工单" width="560" :footer="false">
    <div class="form-group"><label>工单标题</label><input v-model="rdForm.title" placeholder="措施工单标题" /></div>
    <div class="form-row">
      <div class="form-group"><label>责任人</label>
        <SearchableSelect :model-value="rdForm.person_id" :options="allUsers" placeholder="搜索姓名…" @update:model-value="(v: number | undefined) => rdForm.person_id = v" /></div>
      <div class="form-group"><label>工单类型</label>
        <select v-model="rdForm.type_id"><option :value="undefined">请选择</option><option v-for="tp in woTypes" :key="tp.id" :value="tp.id">{{ tp.name }}</option></select></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>计划开始</label><input type="date" v-model="rdForm.planned_start_date" /></div>
      <div class="form-group"><label>截止时间</label><input type="date" v-model="rdForm.deadline" /></div>
    </div>
    <div class="form-group"><label>触发原因</label><textarea v-model="rdForm.reason" rows="2"></textarea></div>
    <div class="form-group"><label>行动要求</label><textarea v-model="rdForm.action" rows="2"></textarea></div>
    <div class="modal-actions">
      <t-button variant="outline" @click="showRedispatch = false">取消</t-button>
      <t-button theme="primary" @click="submitRedispatch" :disabled="redispatching">{{ redispatching ? '派发中…' : '派发并回到跟踪' }}</t-button>
    </div>
  </t-dialog>

  <!-- 管理员「编辑基本信息」弹窗 -->
  <t-dialog v-model:visible="showBasicEdit" header="编辑基本信息（管理员）" width="680" :footer="false">
    <div class="basic-form-grid">
      <div class="form-group form-full">
        <label><span class="req">*</span>标题</label>
        <input v-model="basicForm.title" placeholder="一句话概括工单内容" />
      </div>
      <div class="form-group">
        <label>项目</label>
        <t-select v-model="basicForm.project_id" placeholder="输入项目名称 / 编码搜索" filterable clearable :options="projectOptions" />
      </div>
      <div class="form-group">
        <label>工单类型</label>
        <select v-model="basicForm.type_id">
          <option :value="null">未选</option>
          <option v-for="t in woTypes" :key="t.id" :value="t.id">{{ t.name }}</option>
        </select>
      </div>
      <div class="form-group">
        <label>优先级</label>
        <select v-model="basicForm.priority">
          <option value="P1">P1 紧急</option>
          <option value="P2">P2 普通</option>
          <option value="P3">P3 低优先</option>
        </select>
      </div>
      <div class="form-group">
        <label>区域</label>
        <select v-model="basicForm.region">
          <option value="">—</option>
          <option v-for="r in REGIONS" :key="r" :value="r">{{ r }}</option>
        </select>
      </div>
      <div class="form-group">
        <label>责任人</label>
        <SearchableSelect v-model="basicForm.person_id" :options="allUsers" placeholder="搜索姓名…" />
      </div>
      <div class="form-group">
        <label>审批人</label>
        <SearchableSelect v-model="basicForm.approver_id" :options="allUsers" placeholder="搜索姓名…" />
      </div>
      <div class="form-group">
        <label>计划开始</label>
        <input type="date" v-model="basicForm.planned_start_date" />
      </div>
      <div class="form-group">
        <label>截止日期</label>
        <input type="date" v-model="basicForm.deadline" />
      </div>
      <div class="form-group form-full">
        <label>完成时间</label>
        <input type="date" v-model="basicForm.completed_date" />
      </div>
      <div class="form-group form-full">
        <label>触发原因</label>
        <textarea v-model="basicForm.reason" placeholder="偏差描述或触发条件" rows="2"></textarea>
      </div>
      <div class="form-group form-full">
        <label>行动要求</label>
        <textarea v-model="basicForm.action" placeholder="具体要做什么、达到什么标准" rows="2"></textarea>
      </div>
      <div class="form-group form-full">
        <label>任务目标交付物</label>
        <textarea v-model="basicForm.task_deliverable" placeholder="年度计划类必填：该传什么附件才能闭环" rows="2"></textarea>
      </div>
      <div class="form-group form-full">
        <label>执行结论</label>
        <textarea v-model="basicForm.conclusion" placeholder="验收结论（闭环后填写）" rows="2"></textarea>
      </div>
    </div>
    <div class="modal-actions" style="margin-top:16px">
      <t-button variant="outline" @click="showBasicEdit = false">取消</t-button>
      <t-button theme="primary" @click="saveBasicEdit" :disabled="basicSaving">{{ basicSaving ? '保存中…' : '保存' }}</t-button>
    </div>
  </t-dialog>
</template>

<script setup lang="ts">
import { toast, confirmDialog } from "@/utils/feedback";
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getWorkOrder, getStatusLogs, transitionWorkOrder, updateWorkOrder, updateWorkOrderBasic, deleteWorkOrder, syncOaWorkOrder, getWorkOrderAttachments, redispatchMeasures, getSimilarHosts, reuseMeasures, mergeHost, type WorkOrder, type StatusLog } from "@/api/workorders";
import { backfillWO, getBackfill, type BackfillResult, exportJudgment, importJudgment } from "@/api/pool";
import { importAgentHtml } from "@/api/imports";
import { getWoTypes, getProjectsAll, getUsersAll } from "@/api/config";
import SearchableSelect from "@/components/SearchableSelect.vue";
import PageError from "@/components/PageError.vue";
import { useUserStore } from "@/stores/user";
import {
  statusLabel, statusTag, priorityLabel, priorityTag,
  sourceLabel, sourceTagClass, escLabel, escTag, flowProgress, hasLiveOA,
} from "@/utils/wo-display";

const route = useRoute();
const router = useRouter();
const userStore = useUserStore();
const isAdmin = computed(() => userStore.isAdmin);
const REGIONS = ["华北", "华中", "华东", "华南", "西北", "西南", "东北"];
const wo = ref<WorkOrder | null>(null);
const loadError = ref("");
const logs = ref<StatusLog[]>([]);
const attachments = ref<any[]>([]);
const backfill = ref<Partial<BackfillResult>>({});
const bfSubmitting = ref(false);
const showDispatchConfirm = ref(false);
const dispatching = ref(false);
const dispatchPersonId = ref<number | undefined>(undefined);
const dispatchApproverId = ref<number | undefined>(undefined);
const dispatchProjectId = ref<number | null | undefined>(undefined);
const dispatchTypeId = ref<number | null | undefined>(undefined);
const dispatchDeadline = ref<string>("");
const dispatchPlannedStart = ref<string>("");
const dispatchReason = ref<string>("");
const dispatchAction = ref<string>("");
const dispatchDeliverable = ref<string>("");
const importFileInput = ref<HTMLInputElement | null>(null);
const importError = ref("");
const importSuccess = ref("");
const importing = ref(false);
const allUsers = ref<any[]>([]);
const woTypes = ref<any[]>([]);
const projects = ref<any[]>([]);
// 派发弹窗项目下拉：与项目管理页同一口径——按编码数字序，「编码 · 名称」，支持模糊搜索
const projectOptions = computed(() =>
  [...projects.value]
    .sort((a, b) => String(a.code || "").localeCompare(String(b.code || ""), undefined, { numeric: true }))
    .map((p) => ({ value: p.id, label: `${p.code} · ${p.name}` }))
);

// 管理员「编辑基本信息」弹窗状态
const showBasicEdit = ref(false);
const basicSaving = ref(false);
const basicForm = reactive({
  title: "",
  reason: "",
  action: "",
  task_deliverable: "",
  conclusion: "",
  project_id: null as number | null,
  type_id: null as number | null,
  person_id: undefined as number | undefined,
  approver_id: undefined as number | undefined,
  priority: "P2",
  region: "",
  planned_start_date: "",
  deadline: "",
  completed_date: "",
});
const similarHosts = ref<any[]>([]);
const oaDriven = computed(() => hasLiveOA(wo.value?.oa_id));
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
  person_id: number | undefined;
  approver_id: number | undefined;
  planned_start_date: string;
  deadline: string;
  reason: string;
  action: string;
  type_id: number | null;
  expanded: boolean;
}
const measureTasks = ref<MeasureTask[]>([]);

// 异常主单（非措施工单且带 metric_type）→ 五阶段；措施工单走普通三步
const isAnomalyHost = computed(() => !!wo.value?.metric_type && !wo.value?.is_measure);

const flow = computed(() => flowProgress(
  wo.value?.status ?? "pending",
  wo.value?.metric_type,
  wo.value?.alert_phase,
));

/** 轮询同步开关态：有真实 OA 且未终态时，页面每 15s 自动同步钉钉状态/附件 */
const pollActive = computed(() =>
  hasLiveOA(wo.value?.oa_id) && !["closed", "rejected"].includes(wo.value?.status ?? ""));

function stepIcon(state: string, i: number): string {
  if (state === "done") return "✓";
  if (state === "active") return "●";
  if (state === "warn") return "⚠";
  return "○";
}

function formatTime(iso: string | null): string {
  return iso ? iso.replace("T", " ").slice(0, 16) : "—";
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
  loadError.value = "";
  wo.value = null;
  try {
  const w = await getWorkOrder(id);
  const [lg, u, wt, p] = await Promise.allSettled([
    getStatusLogs(id), getUsersAll(), getWoTypes(), getProjectsAll(),
  ]);
  wo.value = w;
  logs.value = lg.status === "fulfilled" ? lg.value : [];
  allUsers.value = u.status === "fulfilled" ? u.value : [];
  woTypes.value = wt.status === "fulfilled" ? wt.value : [];
  projects.value = p.status === "fulfilled" ? p.value : [];
  if ([lg, u, wt, p].some((result) => result.status === "rejected")) {
    toast.warning("部分辅助信息加载失败，工单详情仍可查看");
  }
  try { attachments.value = await getWorkOrderAttachments(id); } catch { /* 附件拉取失败忽略 */ }
  try { backfill.value = await getBackfill(id); } catch { /* 回填可能为空 */ }
  // 初始化措施工单任务列表
  if (w.metric_type && !w.is_measure) {
    const tasks = (w as any).triggered_wo_tasks;
    if (Array.isArray(tasks) && tasks.length > 0) {
      measureTasks.value = tasks.map((t: any) => ({
        title: t.title || '',
        person_id: resolveUserId(t, 'person_id', 'person_name'),
        approver_id: resolveUserId(t, 'approver_id', 'approver_name'),
        planned_start_date: t.planned_start_date || '',
        deadline: t.deadline || '',
        reason: t.reason || `由 ${w.code} 触发`,
        action: t.action || '',
        type_id: t.type_id ?? null,
        expanded: false,
      }));
    } else {
      measureTasks.value = [{
        title: '', person_id: undefined, approver_id: undefined, planned_start_date: '', deadline: '',
        reason: `由 ${w.code} 触发`,
        action: '',
        type_id: null,
        expanded: true,
      }];
    }
  }
  await loadSimilar();
  } catch (e: any) {
    loadError.value = e?.message || "加载工单失败，请稍后重试";
  }
}

function resolveUserId(t: any, idKey: string, nameKey: string): number | undefined {
  if (typeof t[idKey] === 'number') return t[idKey];
  const name = (t[nameKey] || '').trim();
  if (!name) return undefined;
  const u = (allUsers.value || []).find((x: any) => x.name === name);
  return u ? u.id : undefined;
}
function validateMeasureTasks(): string | null {
  const titled = measureTasks.value.filter((t) => (t.title || '').trim());
  for (let i = 0; i < titled.length; i++) {
    const t = titled[i];
    const miss: string[] = [];
    if (t.person_id == null) miss.push("责任人");
    if (t.approver_id == null) miss.push("审批人");
    if (!(t.planned_start_date || '').trim()) miss.push("计划开始");
    if (!(t.deadline || '').trim()) miss.push("计划完成");
    if (miss.length) return `第${i + 1}条「${(t.title || '').trim()}」缺：${miss.join('、')}`;
  }
  return null;
}

async function submitBackfill() {
  if (!wo.value) return;
  if (!bfForm.reason.trim()) {
    toast.warning("请先填写根因分析");
    return;
  }
  const tasks = measureTasks.value
    .filter(t => (t.title || '').trim())
    .map(({ expanded, ...rest }) => ({ ...rest, type_id: rest.type_id ? rest.type_id : null }));
  if (tasks.length === 0) {
    toast.warning("请至少添加一条措施工单（填标题）");
    return;
  }
  const v = validateMeasureTasks();
  if (v) { toast.warning(v); return; }
  bfSubmitting.value = true;
  try {
    // 应对措施=分条措施工单：先存进 triggered_wo_tasks，再回填根因进入「分析确认」，不重复填两遍
    await updateWorkOrder(wo.value.id, { triggered_wo_tasks: tasks });
    backfill.value = await backfillWO(wo.value.id, { reason: bfForm.reason });
    await load();
    bfForm.reason = "";
  } catch (e: any) {
    toast.error("回填失败：" + e.message);
  } finally {
    bfSubmitting.value = false;
  }
}

async function transition(action: string) {
  if (!wo.value) return;
  if (oaDriven.value) {
    toast.warning("该工单已由钉钉OA审批流驱动，请在钉钉OA审批中更改状态");
    return;
  }
  try {
    wo.value = await transitionWorkOrder(wo.value.id, action);
    logs.value = await getStatusLogs(wo.value.id);
  } catch (e: any) {
    toast.error(e.message);
  }
}

const syncing = ref(false);
async function syncOa() {
  if (!wo.value) return;
  syncing.value = true;
  try {
    const res = await syncOaWorkOrder(wo.value.id);
    if (res && res.success === false) {
      toast.warning(res.msg || "该工单未发起 OA 审批");
    } else {
      toast.success("OA 状态/内容/附件已同步");
    }
    await load();
    logs.value = await getStatusLogs(wo.value.id);
  } catch (e: any) {
    toast.error("同步失败：" + (e.message || "未知错误"));
  } finally {
    syncing.value = false;
  }
}

/** 轮询同步：有真实 OA 且未终态时先让后端拉一遍钉钉，再静默刷新页面数据（不打断编辑态）。 */
const POLL_INTERVAL_MS = 15000;
let pollTimer: number | undefined;
let pollBusy = false;
async function pollTick() {
  if (!wo.value || pollBusy || syncing.value || document.hidden) return;
  pollBusy = true;
  try {
    if (pollActive.value) {
      try { await syncOaWorkOrder(wo.value.id); } catch { /* 本轮同步失败静默跳过，等下一轮 */ }
    }
    const id = wo.value.id;
    wo.value = await getWorkOrder(id);
    logs.value = await getStatusLogs(id);
    try { attachments.value = await getWorkOrderAttachments(id); } catch { /* 附件拉取失败忽略 */ }
  } catch { /* 轮询失败不打扰用户，等下一轮 */ } finally {
    pollBusy = false;
  }
}

const savingTasks = ref(false);

function addMeasureTask() {
  measureTasks.value.push({
    title: '',
    person_id: undefined,
    approver_id: undefined,
    planned_start_date: '',
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
      toast.warning("请先填写措施工单标题再保存草稿");
      return;
    }
    await updateWorkOrder(wo.value.id, { triggered_wo_tasks: tasks });
    await load();
  } catch (e: any) {
    toast.error("保存失败：" + e.message);
  } finally {
    savingTasks.value = false;
  }
}

async function confirmAnalysis() {
  if (!wo.value) return;
  // 先保存措施草稿
  const tasks = measureTasks.value.filter(t => t.title.trim())
    .map(({ expanded, ...rest }) => ({ ...rest, type_id: rest.type_id ? rest.type_id : null }));
  if (tasks.length === 0) {
    toast.warning("请至少添加一个措施工单");
    return;
  }
  const v = validateMeasureTasks();
  if (v) { toast.warning(v); return; }
  savingTasks.value = true;
  try {
    await updateWorkOrder(wo.value.id, { triggered_wo_tasks: tasks });
  } catch (e: any) {
    toast.error("保存措施草稿失败：" + (e.message || "未知错误"));
    return;
  } finally {
    savingTasks.value = false;
  }
  // 阶段①→②：确认分析结果，生成措施工单
  await transition("confirm_analysis");
  await load();
}

// 阶段④指标异常 → 手动补派发措施工单
const showRedispatch = ref(false);
const redispatching = ref(false);
const rdForm = reactive({ title: "", person_id: undefined as number | undefined, type_id: undefined as number | undefined, planned_start_date: "", deadline: "", reason: "", action: "" });
function openRedispatch() {
  rdForm.title = ""; rdForm.person_id = undefined; rdForm.type_id = undefined;
  rdForm.planned_start_date = ""; rdForm.deadline = ""; rdForm.reason = ""; rdForm.action = "";
  showRedispatch.value = true;
}
async function submitRedispatch() {
  if (!wo.value) return;
  if (!rdForm.title.trim()) { toast.warning("请填写工单标题"); return; }
  const person = allUsers.value.find((u: any) => u.id === rdForm.person_id);
  redispatching.value = true;
  try {
    wo.value = await redispatchMeasures(wo.value.id, [{
      title: rdForm.title,
      person_name: person?.name ?? null,
      type_id: rdForm.type_id ?? null,
      planned_start_date: rdForm.planned_start_date || null,
      deadline: rdForm.deadline || null,
      reason: rdForm.reason || null,
      action: rdForm.action || null,
    }]);
    showRedispatch.value = false;
    await load();
  } catch (e: any) { toast.error(e.message); } finally { redispatching.value = false; }
}

// 相似异常主单：复用措施 / 合并
async function loadSimilar() {
  if (!wo.value || !(wo.value.metric_type && !wo.value.is_measure) || wo.value.status === "closed") return;
  try {
    const r = await getSimilarHosts(wo.value.id);
    similarHosts.value = (r.items || []);
  } catch { similarHosts.value = []; }
}
async function doReuse(h: any) {
  const ids = (h.measure_progress?.measures || []).filter((m: any) => m.status !== "closed").map((m: any) => m.id);
  if (!ids.length) { toast.warning("该主单没有可复用的开着措施"); return; }
  try {
    await reuseMeasures(wo.value!.id, ids);
    toast.success(`已挂载复用 ${ids.length} 个措施工单`);
    await load(); await loadSimilar();
  } catch (e: any) { toast.error(e.message); }
}
async function doMerge(h: any) {
  if (!(await confirmDialog(`确认把本单并入 ${h.code}？本单将闭环、发生记录并入对方。`))) return;
  try {
    await mergeHost(wo.value!.id, h.id);
    toast.success("已合并");
    await load(); // 主单已闭环，跳回后可能 404 → 由 load 容错
  } catch (e: any) { toast.error(e.message); }
}

async function openDispatchConfirm() {
  if (oaDriven.value) {
    toast.warning("该工单已由钉钉OA审批流驱动，请在钉钉OA审批中更改状态");
    return;
  }
  dispatchPersonId.value = wo.value?.person_id ?? undefined;
  dispatchApproverId.value = wo.value?.approver_id ?? undefined;
  dispatchProjectId.value = wo.value?.project_id ?? null;
  dispatchTypeId.value = wo.value?.type_id ?? null;
  dispatchDeadline.value = wo.value?.deadline ?? "";
  dispatchPlannedStart.value = wo.value?.planned_start_date ?? "";
  dispatchReason.value = wo.value?.reason ?? "";
  dispatchAction.value = wo.value?.action ?? "";
  dispatchDeliverable.value = wo.value?.task_deliverable ?? "";
  showDispatchConfirm.value = true;
}

async function confirmDispatch() {
  if (!wo.value) return;
  // 前端空校验：与 OA 模板必填项一致，缺失则拦截并提示补齐
  const missing: string[] = [];
  if (!dispatchProjectId.value) missing.push("项目");
  if (!dispatchReason.value.trim()) missing.push("触发原因");
  if (!dispatchAction.value.trim()) missing.push("行动要求");
  if (!dispatchPersonId.value) missing.push("责任人");
  if (!dispatchApproverId.value) missing.push("审批人");
  if (!dispatchPlannedStart.value) missing.push("计划开始时间");
  if (!dispatchDeadline.value) missing.push("截止时间");
  if (wo.value?.source_code === "plan" && !dispatchDeliverable.value.trim()) missing.push("任务目标交付物");
  if (missing.length) {
    toast.warning("请先补齐必填字段：" + missing.join("、"));
    return;
  }
  dispatching.value = true;
  try {
    await updateWorkOrder(wo.value.id, {
      project_id: dispatchProjectId.value ?? null,
      person_id: dispatchPersonId.value,
      approver_id: dispatchApproverId.value,
      planned_start_date: dispatchPlannedStart.value || null,
      deadline: dispatchDeadline.value || null,
      reason: dispatchReason.value,
      action: dispatchAction.value,
      task_deliverable: dispatchDeliverable.value.trim() || null,
    });
    await transition("dispatch");
    showDispatchConfirm.value = false;
  } catch (e: any) {
    toast.error("派发失败：" + (e.message || "未知错误"));
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
    toast.error("导出失败：" + (e.message || "未知错误"));
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
    toast.error("保存失败：" + e.message);
  }
}

function openBasicEdit() {
  if (!wo.value) return;
  basicForm.title = wo.value.title || "";
  basicForm.reason = wo.value.reason || "";
  basicForm.action = wo.value.action || "";
  basicForm.task_deliverable = wo.value.task_deliverable || "";
  basicForm.conclusion = wo.value.conclusion || "";
  basicForm.project_id = wo.value.project_id ?? null;
  basicForm.type_id = wo.value.type_id ?? null;
  basicForm.person_id = wo.value.person_id ?? undefined;
  basicForm.approver_id = wo.value.approver_id ?? undefined;
  basicForm.priority = wo.value.priority || "P2";
  basicForm.region = wo.value.region || "";
  basicForm.planned_start_date = wo.value.planned_start_date || "";
  basicForm.deadline = wo.value.deadline || "";
  basicForm.completed_date = wo.value.completed_date || "";
  showBasicEdit.value = true;
}

async function saveBasicEdit() {
  if (!wo.value) return;
  if (!basicForm.title.trim()) {
    toast.warning("标题不能为空");
    return;
  }
  basicSaving.value = true;
  try {
    await updateWorkOrderBasic(wo.value.id, {
      title: basicForm.title.trim(),
      reason: basicForm.reason || null,
      action: basicForm.action || null,
      task_deliverable: basicForm.task_deliverable.trim() || null,
      conclusion: basicForm.conclusion || null,
      project_id: basicForm.project_id ?? null,
      type_id: basicForm.type_id ?? null,
      person_id: basicForm.person_id ?? null,
      approver_id: basicForm.approver_id ?? null,
      priority: basicForm.priority || "P2",
      region: basicForm.region || null,
      planned_start_date: basicForm.planned_start_date || null,
      deadline: basicForm.deadline || null,
      completed_date: basicForm.completed_date || null,
    });
    toast.success("基本信息已更新");
    showBasicEdit.value = false;
    await load();
  } catch (e: any) {
    toast.error("保存失败：" + e.message);
  } finally {
    basicSaving.value = false;
  }
}

async function removeWorkOrder() {
  if (!wo.value) return;
  if (oaDriven.value) {
    toast.warning("该工单已发起钉钉OA审批，不能删除");
    return;
  }
  const ok = await confirmDialog(`确认删除工单 ${wo.value.code}（${wo.value.title}）？此操作不可恢复。`);
  if (!ok) return;
  try {
    await deleteWorkOrder(wo.value.id);
    toast.success("工单已删除");
    router.push("/work-orders");
  } catch (e: any) {
    toast.error("删除失败：" + (e.message || "未知错误"));
  }
}

onMounted(() => {
  load();
  pollTimer = window.setInterval(pollTick, POLL_INTERVAL_MS);
});
watch(() => route.params.id, () => load());
onUnmounted(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer);
});
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
.oa-poll-hint { text-align: center; font-size: 11px; color: #b45309; background: #fffbeb; border: 1px dashed #fde68a; padding: 4px 10px; border-radius: 6px; margin-top: 8px; }

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

.oa-driving-hint { font-size: 11px; color: #b45309; background: #fffbeb; border: 1px solid #fde68a; padding: 3px 10px; border-radius: 6px; align-self: center; }
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
/* 派发确认弹窗 */
.modal-body { margin-bottom: 20px; }
.confirm-row { display: flex; padding: 6px 0; border-bottom: 1px solid #f3f4f6; font-size: 13px; }
.confirm-lbl { width: 80px; color: var(--muted); flex-shrink: 0; }
.confirm-val { flex: 1; }
.confirm-row.di-edit { align-items: center; padding: 8px 0; border-top: 1px solid var(--border); margin-top: 4px; }
.di-input { flex: 1; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; background: #fff; resize: vertical; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }

/* 管理员编辑基本信息弹窗 + 删除按钮 */
.btn-danger { background: #fff; color: var(--red); border: 1px solid #fca5a5; }
.btn-danger:hover { background: #fef2f2; }
.basic-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.basic-form-grid .form-group { display: flex; flex-direction: column; gap: 4px; }
.basic-form-grid .form-full { grid-column: 1 / -1; }
.basic-form-grid label { font-size: 12px; font-weight: 600; color: var(--muted); }
.basic-form-grid .req { color: var(--red); }
.basic-form-grid input, .basic-form-grid textarea, .basic-form-grid select { padding: 7px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; background: #fff; }
.basic-form-grid textarea { resize: vertical; min-height: 44px; }
@media (max-width: 900px) { .basic-form-grid { grid-template-columns: 1fr; } }

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
.progress-hint { font-size: 12px; color: var(--muted); font-weight: 600; }
.measure-list { display: flex; flex-direction: column; gap: 6px; }
.measure-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: #f8fafc; border-radius: 6px; border: 1px solid var(--border); }
.measure-code { font-weight: 600; font-size: 12px; color: var(--brand); flex-shrink: 0; }
.measure-title { flex: 1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #374151; }
.similar-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: #f8fafc; border-radius: 6px; border: 1px solid var(--border); margin-bottom: 6px; }
.occ-row { display: flex; align-items: center; gap: 10px; padding: 5px 10px; font-size: 12px; color: #6b7280; border-bottom: 1px dashed var(--border); }
.occ-date { flex-shrink: 0; color: var(--muted); }
.occ-note { color: #9ca3af; }
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

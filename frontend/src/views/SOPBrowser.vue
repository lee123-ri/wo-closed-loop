<template>
  <div class="page">
    <div class="header"><h1>SOP 知识库</h1><div class="meta">基于 YWSYB-GLZY 系列官方管理指引 · 双击卡片可编辑</div></div>
    <div class="card" v-for="sop in sops" :key="sop.id" style="margin-bottom:12px">
      <div class="card-hd" @click="sop._open = !sop._open" style="cursor:pointer">
        <h3>{{ sop.name }}</h3>
        <div class="hd-right">
          <span class="count" v-if="sop.guidance_ref">{{ sop.guidance_ref }} · {{ sop.sop_steps?.length || 0 }} 步</span>
          <button class="btn btn-sm btn-out" @click.stop="startEdit(sop)">✏️ 编辑</button>
        </div>
      </div>
      <div v-if="sop._open" class="sop-body">
        <div class="sop-section" v-if="sop.sop_purpose"><label>目的</label><div class="sop-text">{{ sop.sop_purpose }}</div></div>
        <div class="sop-section" v-if="sop.sop_scope"><label>流程</label><div class="sop-text">{{ sop.sop_scope }}</div></div>
        <div class="sop-section" v-if="sop.sop_steps?.length"><label>标准步骤</label>
          <div class="sop-steps"><div v-for="s in sop.sop_steps" :key="s.step" class="sop-step">
            <span class="step-num">{{ s.step }}</span>
            <div><div class="step-action">{{ s.action }}</div><div class="step-standard">标准：{{ s.standard }}</div><div class="step-role">执行人：{{ s.role }}</div></div>
          </div></div>
        </div>
        <div class="sop-section" v-if="sop.sop_acceptance"><label>验收标准</label><div class="sop-text">{{ sop.sop_acceptance }}</div></div>
        <div class="sop-section" v-if="sop.sop_related_guidance?.length"><label>关联指引</label>
          <div class="sop-related"><span v-for="r in sop.sop_related_guidance" :key="r.ref" class="sop-ref">{{ r.ref }} {{ r.title }}</span></div>
        </div>
      </div>
    </div>

    <!-- SOP 编辑弹窗 -->
    <div v-if="editModal.open" class="modal-mask" @click.self="editModal.open = false">
      <div class="modal modal-wide">
        <h3>编辑 SOP · {{ editModal.name }}</h3>
        <div class="modal-body-scroll">
          <div class="form-group"><label>指引编号</label><input v-model="editModal.guidance_ref" /></div>
          <div class="form-group"><label>目的</label><textarea v-model="editModal.sop_purpose" rows="2"></textarea></div>
          <div class="form-group"><label>流程</label><textarea v-model="editModal.sop_scope" rows="2"></textarea></div>
          <div class="form-group">
            <label>标准步骤（JSON）</label>
            <textarea v-model="editModal.sop_steps" rows="6" class="mono"></textarea>
            <span class="form-hint">[{"step":1,"action":"...","standard":"...","role":"..."}]</span>
          </div>
          <div class="form-group"><label>验收标准</label><textarea v-model="editModal.sop_acceptance" rows="2"></textarea></div>
          <div class="form-group">
            <label>升级规则（JSON）</label>
            <textarea v-model="editModal.sop_escalation" rows="3" class="mono"></textarea>
          </div>
          <div class="form-group">
            <label>关联指引（JSON）</label>
            <textarea v-model="editModal.sop_related_guidance" rows="3" class="mono"></textarea>
          </div>
          <div class="form-group">
            <label class="checkbox-label"><input type="checkbox" v-model="editModal.sop_backfill_required" /> 要求回填</label>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn btn-out" @click="editModal.open = false">取消</button>
          <button class="btn btn-pri" @click="saveEdit" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { getWoTypesFull } from "@/api/config";
import { updateWoType } from "@/api/config-crud";

const sops = ref<any[]>([]);
const saving = ref(false);

const editModal = reactive({
  open: false, id: 0, name: "",
  guidance_ref: "", sop_purpose: "", sop_scope: "", sop_steps: "",
  sop_acceptance: "", sop_escalation: "", sop_related_guidance: "", sop_backfill_required: true,
});

function startEdit(sop: any) {
  editModal.id = sop.id;
  editModal.name = sop.name;
  editModal.guidance_ref = sop.guidance_ref || "";
  editModal.sop_purpose = sop.sop_purpose || "";
  editModal.sop_scope = sop.sop_scope || "";
  editModal.sop_steps = sop.sop_steps ? JSON.stringify(sop.sop_steps, null, 2) : "";
  editModal.sop_acceptance = sop.sop_acceptance || "";
  editModal.sop_escalation = sop.sop_escalation ? JSON.stringify(sop.sop_escalation, null, 2) : "";
  editModal.sop_related_guidance = sop.sop_related_guidance ? JSON.stringify(sop.sop_related_guidance, null, 2) : "";
  editModal.sop_backfill_required = sop.sop_backfill_required !== false;
  editModal.open = true;
}

async function saveEdit() {
  saving.value = true;
  try {
    const data: any = {
      type_code: sops.value.find(s => s.id === editModal.id)?.type_code || "",
      name: editModal.name,
      guidance_ref: editModal.guidance_ref || null,
      sop_purpose: editModal.sop_purpose || null,
      sop_scope: editModal.sop_scope || null,
      sop_acceptance: editModal.sop_acceptance || null,
      sop_backfill_required: editModal.sop_backfill_required,
    };
    try { data.sop_steps = editModal.sop_steps ? JSON.parse(editModal.sop_steps) : null; } catch { alert("标准步骤 JSON 格式错误"); return; }
    try { data.sop_escalation = editModal.sop_escalation ? JSON.parse(editModal.sop_escalation) : null; } catch { alert("升级规则 JSON 格式错误"); return; }
    try { data.sop_related_guidance = editModal.sop_related_guidance ? JSON.parse(editModal.sop_related_guidance) : null; } catch { alert("关联指引 JSON 格式错误"); return; }
    await updateWoType(editModal.id, data);
    editModal.open = false;
    sops.value = (await getWoTypesFull()).map((s: any) => ({ ...s, _open: s._open ?? false }));
  } catch (e: any) { alert("保存失败：" + e.message); }
  finally { saving.value = false; }
}

onMounted(async () => { sops.value = (await getWoTypesFull()).map((s: any) => ({ ...s, _open: false })); });
</script>
<style scoped>
.page .header { margin-bottom: 20px; } .header h1 { font-size: var(--fs-h1); font-weight: 700; } .meta { font-size: 12px; color: var(--muted); }
.card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.card-hd { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; }
.card-hd h3 { font-size: 15px; font-weight: 700; } .count { font-size: 12px; color: var(--muted); }
.hd-right { display: flex; align-items: center; gap: 10px; }
.sop-body { padding: 0 20px 16px; } .sop-section { margin-bottom: 12px; }
.sop-section label { display: block; font-size: 12px; font-weight: 700; color: var(--brand); margin-bottom: 4px; }
.sop-text { padding: 10px; background: #f8fafc; border-radius: 6px; font-size: 13px; line-height: 1.6; }
.sop-steps { display: flex; flex-direction: column; gap: 6px; } .sop-step { display: flex; gap: 10px; padding: 8px; background: #f8fafc; border-radius: 6px; }
.step-num { width: 24px; height: 24px; border-radius: 50%; background: var(--brand); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.step-action { font-size: 13px; font-weight: 600; } .step-standard { font-size: 11px; color: var(--muted); } .step-role { font-size: 11px; color: var(--amber); }
.sop-related { display: flex; flex-wrap: wrap; gap: 6px; } .sop-ref { font-size: 11px; padding: 3px 8px; background: #eff6ff; color: var(--brand); border-radius: 4px; }

/* 编辑弹窗 */
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; border-radius: 12px; padding: 24px; width: 420px; max-width: 90vw; max-height: 85vh; overflow-y: auto; }
.modal-wide { width: 640px; }
.modal h3 { font-size: 16px; margin-bottom: 16px; }
.modal-body-scroll { max-height: 60vh; overflow-y: auto; padding-right: 4px; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; font-size: 12px; font-weight: 600; color: #4b5563; margin-bottom: 4px; }
.form-group input, .form-group textarea { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
.form-group textarea { resize: vertical; }
.form-group textarea.mono { font-family: monospace; font-size: 12px; }
.form-hint { font-size: 10px; color: var(--muted); display: block; margin-top: 2px; }
.checkbox-label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px; font-weight: 400; }
.checkbox-label input { width: auto; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.btn { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-pri { background: var(--brand); color: #fff; } .btn-pri:disabled { opacity: 0.6; }
.btn-out { background: #fff; color: #4b5563; border: 1px solid var(--border); } .btn-sm { padding: 4px 10px; font-size: 11px; }
</style>
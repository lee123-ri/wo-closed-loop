<template>
  <div class="page">
    <div class="header"><h1>SOP 知识库</h1><div class="meta">基于 YWSYB-GLZY 系列官方管理指引</div></div>
    <div class="card" v-for="sop in sops" :key="sop.id" style="margin-bottom:12px">
      <div class="card-hd" @click="sop._open = !sop._open" style="cursor:pointer">
        <h3>{{ sop.name }}</h3>
        <span class="count" v-if="sop.guidance_ref">{{ sop.guidance_ref }} · {{ sop.sop_steps?.length || 0 }} 步</span>
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
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getWoTypesFull } from "@/api/config";
const sops = ref<any[]>([]);
onMounted(async () => { sops.value = (await getWoTypesFull()).map((s: any) => ({ ...s, _open: false })); });
</script>
<style scoped>
.page .header { margin-bottom: 20px; } .header h1 { font-size: var(--fs-h1); font-weight: 700; } .meta { font-size: 12px; color: var(--muted); }
.card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.card-hd { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; }
.card-hd h3 { font-size: 15px; font-weight: 700; } .count { font-size: 12px; color: var(--muted); }
.sop-body { padding: 0 20px 16px; } .sop-section { margin-bottom: 12px; }
.sop-section label { display: block; font-size: 12px; font-weight: 700; color: var(--brand); margin-bottom: 4px; }
.sop-text { padding: 10px; background: #f8fafc; border-radius: 6px; font-size: 13px; line-height: 1.6; }
.sop-steps { display: flex; flex-direction: column; gap: 6px; } .sop-step { display: flex; gap: 10px; padding: 8px; background: #f8fafc; border-radius: 6px; }
.step-num { width: 24px; height: 24px; border-radius: 50%; background: var(--brand); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.step-action { font-size: 13px; font-weight: 600; } .step-standard { font-size: 11px; color: var(--muted); } .step-role { font-size: 11px; color: var(--amber); }
.sop-related { display: flex; flex-wrap: wrap; gap: 6px; } .sop-ref { font-size: 11px; padding: 3px 8px; background: #eff6ff; color: var(--brand); border-radius: 4px; }
</style>
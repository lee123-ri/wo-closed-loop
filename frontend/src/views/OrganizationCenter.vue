<template>
  <div class="page">
    <div class="header"><h1>用户与组织</h1><p>钉钉提供人员事实；岗位映射先预览、确认后才生效。</p></div>
    <PageError v-if="error" title="组织配置加载失败" :message="error" @action="load" />
    <template v-else>
      <t-card title="权限角色"><template #actions><t-button size="small" @click="addPermissionRole">新增权限角色</t-button></template>
        <div class="hint">权限角色控制菜单、操作和数据范围；业务岗位只描述职责，两者不重复。</div>
        <t-table :data="permissionRoles" :columns="permissionRoleColumns" row-key="id" size="small" />
      </t-card>
      <t-card title="人员权限授权"><template #actions><t-button size="small" @click="addPermissionAssignment">分配权限</t-button></template>
        <div class="hint">输入平台用户 ID 后授予权限角色。旧管理员身份在迁移期仍兼容，后端以权限角色再次校验。</div>
      </t-card>
      <t-card title="业务岗位"><template #actions><t-button size="small" @click="addRole">新增岗位</t-button></template>
        <t-table :data="roles" :columns="roleColumns" row-key="id" size="small" />
      </t-card>
      <t-card title="钉钉组织映射规则"><template #actions><t-button size="small" @click="addMapping">新增映射</t-button></template>
        <t-table :data="mappings" :columns="mappingColumns" row-key="id" size="small" />
      </t-card>
      <t-card title="待确认岗位"><div class="hint">项目群/部门/职位同步只会产生这里的候选项；确认后才参与责任人、审批人与升级解析。</div>
        <t-table :data="candidates" :columns="candidateColumns" row-key="id" size="small">
          <template #action="{ row }"><t-button v-if="row.status==='pending'" size="small" theme="primary" @click="confirmCandidate(row)">确认生效</t-button></template>
        </t-table>
      </t-card>
      <t-card title="项目群同步"><div class="hint">先绑定项目钉钉群；同步仅生成“场站人员”待确认候选，不按姓名猜测，也不直接赋权。</div>
        <t-table :data="projects" :columns="projectColumns" row-key="id" size="small"><template #sync="{ row }"><t-button size="small" :disabled="!row.dingtalk_group_id" @click="syncProject(row)">生成候选</t-button></template></t-table>
      </t-card>
      <t-card title="机器人通知规则"><template #actions><t-button size="small" @click="addNotification">新增规则</t-button></template>
        <div class="hint">仅支持机器人私聊、机器人群聊。新规则默认草稿；试算只展示接收对象和内容，不发送消息。</div>
        <t-table :data="notifications" :columns="notificationColumns" row-key="id" size="small" />
      </t-card>
      <t-card title="运行事件"><div class="hint">用于运维快速定位同步、试算和投递问题；完整技术异常通过追踪号关联文件日志。</div>
        <t-table :data="events" :columns="eventColumns" row-key="id" size="small" />
      </t-card>
    </template>
    <t-dialog v-model:visible="dialog.open" :header="dialog.title" :footer="false" width="460">
      <div v-if="dialog.kind==='permission'" class="form"><t-input v-model="dialog.code" label="编码" placeholder="如 regional_operator" /><t-input v-model="dialog.name" label="名称" /><t-input v-model="dialog.dataScopes" label="数据范围" placeholder="all / self / region，以逗号分隔" /><t-input v-model="dialog.menus" label="菜单权限" placeholder="菜单名称，以逗号分隔；* 表示全部" /><t-input v-model="dialog.actions" label="操作权限" placeholder="操作编码，以逗号分隔；* 表示全部" /></div>
      <div v-else-if="dialog.kind==='permissionAssignment'" class="form"><t-input v-model="dialog.userId" label="平台用户 ID" /><t-select v-model="dialog.permissionRoleId" :options="permissionRoleOptions" label="权限角色" /></div>
      <div v-else-if="dialog.kind==='role'" class="form"><t-input v-model="dialog.code" label="编码" placeholder="如 project_manager" /><t-input v-model="dialog.name" label="名称" /><t-select v-model="dialog.scope" :options="scopeOptions" label="适用层级" /></div>
      <div v-else-if="dialog.kind==='mapping'" class="form"><t-input v-model="dialog.name" label="规则名称" /><t-select v-model="dialog.sourceKind" :options="sourceOptions" label="钉钉来源" /><t-input v-model="dialog.pattern" label="匹配文本或正则" /><t-select v-model="dialog.roleCode" :options="roleOptions" label="业务岗位" /><t-select v-model="dialog.scope" :options="scopeOptions" label="作用层级" /></div>
      <div v-else class="form"><t-input v-model="dialog.name" label="规则名称" /><t-select v-model="dialog.event" :options="eventOptions" label="触发事件" /><t-checkbox-group v-model="dialog.channels" :options="channelOptions" /><t-textarea v-model="dialog.template" label="消息模板" placeholder="支持 {code}、{title}、{status}" /></div>
      <div class="actions"><t-button variant="outline" @click="dialog.open=false">取消</t-button><t-button theme="primary" @click="save">保存</t-button></div>
    </t-dialog>
  </div>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref, computed } from "vue";
import http from "@/api/http";
import { toast } from "@/utils/feedback";
import PageError from "@/components/PageError.vue";
const permissionRoles=ref<any[]>([]), roles=ref<any[]>([]), mappings=ref<any[]>([]), candidates=ref<any[]>([]), notifications=ref<any[]>([]), events=ref<any[]>([]), projects=ref<any[]>([]), error=ref("");
const scopeOptions=[{label:"全局",value:"global"},{label:"区域",value:"region"},{label:"项目",value:"project"}], sourceOptions=[{label:"部门",value:"department"},{label:"职位",value:"title"},{label:"项目群",value:"group"}], eventOptions=[{label:"派发",value:"dispatch"},{label:"即将逾期",value:"sla_warn"},{label:"逾期升级",value:"sla_breach"}], channelOptions=[{label:"机器人私聊",value:"robot_private"},{label:"机器人群聊",value:"robot_group"}];
const dialog=reactive<any>({open:false,kind:"",title:"",code:"",name:"",scope:"global",sourceKind:"title",pattern:"",roleCode:"",event:"dispatch",channels:[],template:"",dataScopes:"self",menus:"",actions:"",userId:"",permissionRoleId:""});
const roleOptions=computed(()=>roles.value.map(x=>({label:x.name,value:x.code})));
const permissionRoleOptions=computed(()=>permissionRoles.value.map(x=>({label:x.name,value:x.id})));
const permissionRoleColumns=[{colKey:"name",title:"权限角色"},{colKey:"code",title:"编码"},{colKey:"data_scopes",title:"数据范围"},{colKey:"menu_permissions",title:"菜单"},{colKey:"action_permissions",title:"操作"},{colKey:"is_active",title:"启用"}];
const roleColumns=[{colKey:"name",title:"岗位"},{colKey:"code",title:"编码"},{colKey:"scope_type",title:"层级"},{colKey:"is_active",title:"启用"}];
const mappingColumns=[{colKey:"name",title:"规则"},{colKey:"source_kind",title:"来源"},{colKey:"pattern",title:"匹配"},{colKey:"business_role_code",title:"岗位"},{colKey:"scope_type",title:"层级"}];
const candidateColumns=[{colKey:"user_id",title:"人员ID"},{colKey:"business_role_code",title:"建议岗位"},{colKey:"source_kind",title:"来源"},{colKey:"source_value",title:"依据"},{colKey:"confidence",title:"置信度"},{colKey:"status",title:"状态"},{colKey:"action",title:"操作"}];
const notificationColumns=[{colKey:"name",title:"规则"},{colKey:"event",title:"事件"},{colKey:"channels",title:"渠道"},{colKey:"enabled",title:"启用"}];
const eventColumns=[{colKey:"created_at",title:"时间"},{colKey:"category",title:"类别"},{colKey:"status",title:"结果"},{colKey:"summary",title:"摘要"},{colKey:"work_order_id",title:"工单"}];
const projectColumns=[{colKey:"name",title:"项目"},{colKey:"region",title:"区域"},{colKey:"dingtalk_group_id",title:"钉钉群 ID"},{colKey:"sync",title:"同步"}];
async function load(){error.value="";try{const result=await Promise.all([http.get<any,any[]>("/organization/permission-roles"),http.get<any,any[]>("/organization/business-roles"),http.get<any,any[]>("/organization/mapping-rules"),http.get<any,any[]>("/organization/sync-candidates"),http.get<any,any[]>("/organization/notification-rules"),http.get<any,any>("/organization/operation-events"),http.get<any,any[]>("/config/projects/all")]);[permissionRoles.value,roles.value,mappings.value,candidates.value,notifications.value,events.value,projects.value]=[result[0],result[1],result[2],result[3],result[4],result[5].items,result[6]]}catch(e:any){error.value=e.message||"请稍后重试"}}
function reset(kind:string,title:string){Object.assign(dialog,{open:true,kind,title,code:"",name:"",scope:"global",sourceKind:"title",pattern:"",roleCode:"",event:"dispatch",channels:[],template:"",dataScopes:"self",menus:"",actions:"",userId:"",permissionRoleId:""})} function addRole(){reset("role","新增业务岗位")} function addPermissionRole(){reset("permission","新增权限角色")} function addPermissionAssignment(){reset("permissionAssignment","分配权限角色")} function addMapping(){reset("mapping","新增映射规则")} function addNotification(){reset("notification","新增机器人通知规则")}
const csv=(value:string)=>value.split(",").map(x=>x.trim()).filter(Boolean);
async function save(){try{if(dialog.kind==="permission")await http.post("/organization/permission-roles",{code:dialog.code,name:dialog.name,data_scopes:csv(dialog.dataScopes),menu_permissions:csv(dialog.menus),action_permissions:csv(dialog.actions)});else if(dialog.kind==="permissionAssignment")await http.post("/organization/permission-assignments",{user_id:Number(dialog.userId),permission_role_id:Number(dialog.permissionRoleId)});else if(dialog.kind==="role")await http.post("/organization/business-roles",{code:dialog.code,name:dialog.name,scope_type:dialog.scope});else if(dialog.kind==="mapping")await http.post("/organization/mapping-rules",{name:dialog.name,source_kind:dialog.sourceKind,pattern:dialog.pattern,business_role_code:dialog.roleCode,scope_type:dialog.scope});else await http.post("/organization/notification-rules",{name:dialog.name,event:dialog.event,channels:dialog.channels,template:dialog.template,enabled:false});dialog.open=false;toast.success("已保存为可配置草稿");await load()}catch(e:any){toast.error(e.message||"保存失败")}}
async function confirmCandidate(row:any){try{await http.post(`/organization/sync-candidates/${row.id}/confirm`);toast.success("岗位已确认生效");await load()}catch(e:any){toast.error(e.message||"确认失败")}}
async function syncProject(row:any){try{const result=await http.post<any,any>(`/organization/projects/${row.id}/sync-candidates`);toast.success(`已生成 ${result.created} 个待确认候选`);await load()}catch(e:any){toast.error(e.message||"同步失败")}}
onMounted(load);
</script>
<style scoped>.page{display:flex;flex-direction:column;gap:16px}.header h1{font-size:var(--fs-h1)}.header p,.hint{font-size:12px;color:var(--muted)}.form{display:flex;flex-direction:column;gap:12px}.actions{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}</style>

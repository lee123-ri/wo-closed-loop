#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉钉OA审批模板创建工具

钉钉已经没有开放API用来创建审批模板，
模板需要在钉钉管理后台（OA管理 → 表单管理）手动创建。

本脚本提供：
  1. 打开管理后台的指引
  2. 模板配置的JSON导出（可根据需要在管理后台批量导入）
  3. 模板创建后的验证

用法：
  python3 create_oa_template.py          # 打印配置指南
  python3 create_oa_template.py --export # 导出模板配置JSON
"""

import argparse
import json
import sys
from pathlib import Path


# 保存 processCode 的文件
PROCESS_CODE_FILE = Path(__file__).resolve().parent / ".oa_template_process_code.json"


MANUAL_GUIDE = """
╔══════════════════════════════════════════════════════════════════╗
║              软工单闭环审批 · 钉钉OA模板创建指南                ║
╚══════════════════════════════════════════════════════════════════╝

【前置条件】
  1. 有钉钉管理后台权限（OA审批管理权限）
  2. 已开通OA审批功能
  3. 能访问：https://oa.dingtalk.com/ 或 钉钉管理后台 → 工作台 → OA审批

【第一步：进入OA管理后台】
  方式一：网页版
    打开 https://oa.dingtalk.com/ → 扫码登录 → 表单管理

  方式二：钉钉客户端
    钉钉 → 工作台 → OA审批 → 右上角「管理」→ 表单管理

【第二步：创建新表单】
  点击「创建新表单」→ 选择「普通表单」

  表单名称：软工单闭环审批
  表单说明：软工单闭环管理 - 责任指派 → 执行佐证 → 审批闭环
  分组：建议放在「项目管理」或自建分组

【第三步：配置表单字段】
  按以下顺序添加字段（字段名必须与下表一致，后续API调用时匹配）：

  ┌────────────────┬────────────┬──────────┬──────────────────────────┐
  │ 字段名         │ 控件类型    │ 必填     │ 说明                     │
  ├────────────────┼────────────┼──────────┼──────────────────────────┤
  │ 工单编号       │ 单行输入框 │ 是       │ 系统自动生成或手动填写    │
  │ 项目名称       │ 单行输入框 │ 是       │ 如：中节能通辽永兴        │
  │ 工单类型       │ 单选       │ 是       │ 选项见下方               │
  │ 触发原因       │ 多行输入框 │ 是       │ 偏差描述或触发条件        │
  │ 行动要求       │ 多行输入框 │ 是       │ 具体要做什么              │
  │ 责任人         │ 人员选择   │ 是       │ 执行人                   │
  │ 截止时间       │ 日期       │ 是       │ 完成时限                 │
  │ 执行佐证       │ 附件       │ 否       │ 照片/截图/文件            │
  │ 执行结论       │ 多行输入框 │ 否       │ 责任人填写               │
  │ 审批人         │ 人员选择   │ 是       │ 确认闭环审批人            │
  └────────────────┴────────────┴──────────┴──────────────────────────┘

  「工单类型」选项：
    ┌──────────────┬──────────────┐
    │ 选项值       │ 选项名       │
    ├──────────────┼──────────────┤
    │ corrective   │ 纠偏         │
    │ customer_comm│ 客户沟通     │
    │ relationship │ 关系维护     │
    │ non_standard │ 非标任务     │
    │ other        │ 其他         │
    └──────────────┴──────────────┘

  提示：字段名最终会作为 API 调用的 name 参数，
  建议在管理后台创建时和上面表格完全一致，避免后续API调用时字段匹配不上。

【第四步：配置审批流程】

  流程类型：审批流程
  流程节点：

  节点1（责任人执行）：
    ├── 审批人类型：从表单获取
    ├── 审批人字段：责任人
    └── 审批方式：单人审批

  节点2（审批人确认）：
    ├── 审批人类型：从表单获取
    ├── 审批人字段：审批人
    └── 审批方式：单人审批

  超时设置（可选）：
    └── 截止时间前24小时 → 自动催办

【第五步：发布表单】
  点击「保存并发布」
  发布成功后，记下表单的 processCode（在表单详情页URL中可找到）

【第六步：验证并记录】
  1. 刷新页面，在表单列表中找到"软工单闭环审批"
  2. 记住模板唯一标识（processCode）
  3. 运行验证脚本：
     python3 verify_template.py

【第七步：配置到项目】
  将 processCode 填入 .env 文件：
    DINGTALK_OA_TEMPLATE_ID=<获取到的processCode>

【常见问题】
  Q: 找不到表单管理入口？
  A: 需要企业管理员授权。联系IT管理员开通「OA审批管理」权限。

  Q: 字段名可以改吗？
  A: 可以，但必须同步修改 API 调用中的字段名。

  Q: 表单已发布，如何修改？
  A: 在「表单管理」中找到表单，点击「编辑」→ 修改 → 重新发布。

  Q: 流程如何设置超时？
  A: 在审批流程配置中，每个节点可以设置「超时处理」。
"""


TEMPLATE_EXPORT = {
    "template_name": "软工单闭环审批",
    "template_description": "软工单闭环管理 - 责任指派 → 执行佐证 → 审批闭环",
    "fields": [
        {
            "field_name": "工单编号",
            "component_type": "TextField",
            "required": True,
            "placeholder": "系统自动生成或手动填写"
        },
        {
            "field_name": "项目名称",
            "component_type": "TextField",
            "required": True,
            "placeholder": "如：中节能通辽永兴"
        },
        {
            "field_name": "工单类型",
            "component_type": "DDSelectField",
            "required": True,
            "options": [
                {"value": "corrective", "label": "纠偏"},
                {"value": "customer_communication", "label": "客户沟通"},
                {"value": "relationship_maintenance", "label": "关系维护"},
                {"value": "non_standard_task", "label": "非标任务"},
                {"value": "other", "label": "其他"}
            ]
        },
        {
            "field_name": "触发原因",
            "component_type": "TextareaField",
            "required": True,
            "placeholder": "偏差描述或触发条件，如：指标偏离阈值、客户投诉等"
        },
        {
            "field_name": "行动要求",
            "component_type": "TextareaField",
            "required": True,
            "placeholder": "具体要做什么，如：联系客户沟通变更方案，形成会议纪要"
        },
        {
            "field_name": "责任人",
            "component_type": "DDStaffField",
            "required": True,
            "placeholder": "请选择责任人（执行人）"
        },
        {
            "field_name": "截止时间",
            "component_type": "DDDateField",
            "required": True,
            "placeholder": "请选择完成时限",
            "format": "yyyy-MM-dd"
        },
        {
            "field_name": "执行佐证",
            "component_type": "AttachmentField",
            "required": False,
            "placeholder": "上传执行结果佐证，支持照片/截图/文件",
            "multiple": True
        },
        {
            "field_name": "执行结论",
            "component_type": "TextareaField",
            "required": False,
            "placeholder": "责任人填写执行结果、完成情况说明"
        },
        {
            "field_name": "审批人",
            "component_type": "DDStaffField",
            "required": True,
            "placeholder": "请选择确认闭环的审批人"
        }
    ],
    "approval_flow": [
        {
            "node_name": "责任人执行",
            "approver_type": "from_form_field",
            "field_name": "责任人",
            "sign_type": "single"
        },
        {
            "node_name": "审批人确认闭环",
            "approver_type": "from_form_field",
            "field_name": "审批人",
            "sign_type": "single"
        }
    ]
}


def main():
    parser = argparse.ArgumentParser(description="软工单钉钉OA审批模板创建工具")
    parser.add_argument("--export", action="store_true", help="导出模板配置JSON")
    parser.add_argument("--guide", action="store_true", help="显示创建指南")
    args = parser.parse_args()

    if args.export:
        print(json.dumps(TEMPLATE_EXPORT, ensure_ascii=False, indent=2))
        print(f"\n💡 已保存到上述文件")
        return

    # 默认显示指南
    print(MANUAL_GUIDE)

    print("\n" + "=" * 60)
    print("💡 提示：完成后运行以下命令验证模板可用性")
    print("  python3 verify_template.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
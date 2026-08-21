#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试发起软工单OA审批实例

在模板创建完成后，运行此脚本测试发起一个测试工单。

用法：
  # 交互式输入（推荐）
  python3 test_oa_initiate.py

  # 直接指定参数
  python3 test_oa_initiate.py \\
    --process-code PROC-XXXX \\
    --project "中节能通辽永兴" \\
    --type "纠偏" \\
    --reason "测试：模板可用性验证" \\
    --action "确认审批模板是否正常可用" \\
    --person "李沛东" \\
    --deadline "2026-08-20" \\
    --approver "贾兴威"
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


# 默认凭证（cockpit平台）
APP_KEY = "ding1ikpdp8hvarwxoi2"
APP_SECRET = "OqWQbDHrpCtMb-3im7Q1nqqU05tGvIGeZdshAbz7cDHgHzlCjojbjBM3KPl0EXkM"

# 保存的 processCode 文件
PROCESS_CODE_FILE = Path(__file__).resolve().parent / ".oa_template_process_code.json"


def load_process_code() -> str:
    """从文件读取 processCode"""
    if PROCESS_CODE_FILE.exists():
        data = json.loads(PROCESS_CODE_FILE.read_text(encoding="utf-8"))
        return data.get("processCode")
    return None


def search_forms(keyword: str) -> list:
    """搜索审批表单"""
    result = subprocess.run([
        "dws", "oa", "+search-forms",
        "--query", keyword,
        "--format", "json",
    ], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
        return data.get("forms", data.get("items", data.get("result", {}).get("forms", [])))
    except json.JSONDecodeError:
        return []


def initiate_approval(process_code: str, form_data: list) -> str:
    """发起审批实例"""
    payload = {
        "process_code": process_code,
        "originator_user_id": "",
        "dept_id": 1,
        "app_v2": True,
        "form_component_values": form_data,
    }

    result = subprocess.run([
        "dws", "api", "POST", "/topapi/processinstance/create",
        "--base-url", "https://oapi.dingtalk.com",
        "--data", json.dumps(payload, ensure_ascii=False),
        "--client-id", APP_KEY,
        "--client-secret", APP_SECRET,
        "--format", "json",
    ], capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        print(f"\n❌ 发起审批失败: {result.stderr}")
        if result.stdout:
            print(f"响应: {result.stdout}")
        return None

    try:
        data = json.loads(result.stdout)
        errcode = data.get("errcode", 0)
        errmsg = data.get("errmsg", "")

        if errcode != 0:
            print(f"\n❌ 发起审批失败 (errcode={errcode}): {errmsg}")
            if "表单组件" in errmsg or "form" in errmsg.lower():
                print("\n💡 提示：字段名与模板不匹配，请检查模板中的字段名是否正确")
                print("   可在钉钉管理后台 → OA审批 → 表单管理 → 编辑表单查看字段名")
            return None

        instance_id = data.get("instanceId") or data.get("processInstanceId")
        if instance_id:
            print(f"\n✅ 审批发起成功!")
            print(f"   审批实例ID: {instance_id}")
            return instance_id
        else:
            print(f"\n⚠️ 响应中未找到实例ID: {json.dumps(data, ensure_ascii=False, indent=2)}")
            return None
    except json.JSONDecodeError as e:
        print(f"\n❌ 解析响应失败: {e}")
        print(f"原始响应: {result.stdout}")
        return None


def main():
    parser = argparse.ArgumentParser(description="测试发起软工单OA审批")
    parser.add_argument("--process-code", type=str, help="审批模板ID")
    parser.add_argument("--project", type=str, help="项目名称")
    parser.add_argument("--type", type=str, help="工单类型")
    parser.add_argument("--reason", type=str, help="触发原因")
    parser.add_argument("--action", type=str, help="行动要求")
    parser.add_argument("--person", type=str, help="责任人")
    parser.add_argument("--deadline", type=str, help="截止时间 (YYYY-MM-DD)")
    parser.add_argument("--approver", type=str, help="审批人")
    parser.add_argument("--interactive", action="store_true", default=True, help="交互式输入（默认）")
    args = parser.parse_args()

    print("=" * 60)
    print("🧪 软工单OA审批发起测试")
    print("=" * 60)

    # 获取 processCode
    process_code = args.process_code
    if not process_code:
        process_code = load_process_code()
    if not process_code:
        forms = search_forms("软工单")
        if forms:
            process_code = forms[0].get("processCode", forms[0].get("formCode", ""))

    if not process_code:
        print("\n❌ 未找到模板ID")
        print("  请先创建模板或在钉钉管理后台确认模板已发布")
        print("  然后通过 --process-code 指定模板ID")
        sys.exit(1)

    print(f"📋 模板ID: {process_code}")

    # 交互式输入
    if args.interactive:
        print("\n📝 请输入测试工单信息（直接回车使用默认值）:")
        project = input("  项目名称 [测试项目]: ").strip() or "测试项目"
        wo_type = input("  工单类型 (纠偏/客户沟通/关系维护/非标任务/其他) [其他]: ").strip() or "其他"
        reason = input("  触发原因 [模板可用性验证]: ").strip() or "模板可用性验证"
        action = input("  行动要求 [确认OA审批模板是否正常可用]: ").strip() or "确认OA审批模板是否正常可用"
        person = input("  责任人 (钉钉用户名) [留空]: ").strip()
        deadline = input(f"  截止时间 (YYYY-MM-DD) [{(datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')}]: ").strip()
        if not deadline:
            deadline = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        approver = input("  审批人 (钉钉用户名) [留空]: ").strip()
    else:
        project = args.project or "测试项目"
        wo_type = args.type or "其他"
        reason = args.reason or "模板可用性验证"
        action = args.action or "确认OA审批模板是否正常可用"
        person = args.person or ""
        deadline = args.deadline or (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        approver = args.approver or ""

    # 构建表单数据
    # 注意：字段名必须与模板中的字段名完全一致
    form_data = [
        {"name": "工单编号", "value": f"TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}"},
        {"name": "项目名称", "value": project},
        {"name": "工单类型", "value": wo_type},
        {"name": "触发原因", "value": reason},
        {"name": "行动要求", "value": action},
        {"name": "责任人", "value": person},
        {"name": "截止时间", "value": deadline},
        {"name": "审批人", "value": approver},
    ]

    print(f"\n📋 工单信息:")
    print(f"  ├─ 工单编号: TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    print(f"  ├─ 项目名称: {project}")
    print(f"  ├─ 工单类型: {wo_type}")
    print(f"  ├─ 触发原因: {reason}")
    print(f"  ├─ 行动要求: {action}")
    print(f"  ├─ 责任人: {person or '(未指定)'}")
    print(f"  ├─ 截止时间: {deadline}")
    print(f"  └─ 审批人: {approver or '(未指定)'}")

    if not person and not approver:
        print("\n⚠️ 责任人和审批人均未指定，审批可能无法正常流转")
        confirm = input("  是否继续? (y/N): ").strip().lower()
        if confirm != 'y':
            print("已取消")
            sys.exit(0)

    print(f"\n🚀 正在发起审批...")
    instance_id = initiate_approval(process_code, form_data)

    if instance_id:
        print(f"\n✅ 测试完成！可在钉钉 OA审批中查看测试工单")
        print(f"   或使用以下命令查看详情:")
        print(f"   dws oa approval detail --process-instance-id {instance_id}")

        # 保存测试记录
        test_log = {
            "timestamp": datetime.now().isoformat(),
            "process_code": process_code,
            "instance_id": instance_id,
            "form_data": form_data,
        }
        log_file = Path(__file__).resolve().parent / ".oa_test_log.json"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(test_log, f, ensure_ascii=False, indent=2)
        print(f"\n📝 测试记录已保存至: {log_file}")
    else:
        print(f"\n❌ 测试失败")
        print("\n可能原因：")
        print("  1. 模板ID不正确")
        print("  2. 字段名与模板中的字段名不匹配")
        print("  3. 应用没有该模板的发起权限")
        print("\n👉 请在钉钉管理后台确认模板已发布，并检查字段名")


if __name__ == "__main__":
    main()
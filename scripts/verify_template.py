#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证软工单OA审批模板是否可用

用法：
  python3 verify_template.py
  python3 verify_template.py --process-code <PROCESS_CODE>
"""

import argparse
import json
import subprocess
import sys

# 用 cockpit 平台凭证
APP_KEY = "ding1ikpdp8hvarwxoi2"
APP_SECRET = "OqWQbDHrpCtMb-3im7Q1nqqU05tGvIGeZdshAbz7cDHgHzlCjojbjBM3KPl0EXkM"


def search_forms(keyword: str) -> list:
    """搜索可见的审批表单"""
    result = subprocess.run([
        "dws", "oa", "+search-forms",
        "--query", keyword,
        "--format", "json",
    ], capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        print(f"❌ 搜索失败: {result.stderr}")
        return []

    try:
        data = json.loads(result.stdout)
        return data.get("forms", data.get("items", data.get("result", {}).get("forms", [])))
    except json.JSONDecodeError:
        return []


def list_forms() -> list:
    """列出所有可见表单"""
    result = subprocess.run([
        "dws", "oa", "+list-forms",
        "--cursor", "0",
        "--limit", "100",
        "--format", "json",
    ], capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        print(f"❌ 列表失败: {result.stderr}")
        return []

    try:
        data = json.loads(result.stdout)
        return data.get("forms", data.get("items", data.get("result", {}).get("forms", [])))
    except json.JSONDecodeError:
        return []


def test_initiate(process_code: str) -> bool:
    """测试发起一个审批实例"""
    result = subprocess.run([
        "dws", "api", "POST", "/topapi/processinstance/create",
        "--base-url", "https://oapi.dingtalk.com",
        "--data", json.dumps({
            "process_code": process_code,
            "originator_user_id": "",
            "dept_id": 1,
            "app_v2": True,
            "form_component_values": [
                {"name": "工单编号", "value": "TEST-2026-0001"},
                {"name": "项目名称", "value": "测试项目"},
                {"name": "工单类型", "value": "其他"},
                {"name": "触发原因", "value": "模板创建验证测试"},
                {"name": "行动要求", "value": "验证OA审批模板是否可用"},
                {"name": "责任人", "value": ""},
                {"name": "截止时间", "value": "2026-08-20"},
                {"name": "审批人", "value": ""},
            ],
        }, ensure_ascii=False),
        "--client-id", APP_KEY,
        "--client-secret", APP_SECRET,
        "--format", "json",
    ], capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        print(f"❌ 发起审批失败: {result.stderr}")
        if result.stdout:
            print(f"响应: {result.stdout}")
        return False

    try:
        data = json.loads(result.stdout)
        instance_id = data.get("instanceId") or data.get("processInstanceId")
        if instance_id:
            print(f"✅ 测试发起成功! 审批实例ID: {instance_id}")
            return True
        else:
            print(f"⚠️ 响应中未找到实例ID: {json.dumps(data, ensure_ascii=False, indent=2)}")
            return False
    except json.JSONDecodeError as e:
        print(f"❌ 解析响应失败: {e}")
        print(f"原始响应: {result.stdout}")
        return False


def main():
    parser = argparse.ArgumentParser(description="验证软工单OA审批模板")
    parser.add_argument("--process-code", type=str, help="指定模板ID进行验证")
    parser.add_argument("--test", action="store_true", help="测试发起审批实例")
    args = parser.parse_args()

    print("=" * 60)
    print("🔍 软工单OA审批模板验证")
    print("=" * 60)

    if args.process_code:
        process_code = args.process_code
        print(f"\n📋 使用指定模板ID: {process_code}")
    else:
        # 搜索模板
        print("\n📋 搜索「软工单」相关模板...")
        forms = search_forms("软工单")
        if not forms:
            print("⚠️ 未找到「软工单」相关模板，尝试搜索「工单」...")
            forms = search_forms("工单")

        if not forms:
            print("\n❌ 未找到软工单审批模板")
            print("\n可能原因：")
            print("  1. 模板尚未创建")
            print("  2. 当前用户没有该模板的发起权限")
            print("  3. 模板名称不匹配")
            print("\n👉 请先在钉钉管理后台创建模板：")
            print("   python3 create_oa_template.py")
            print("\n当前可见的审批表单：")
            all_forms = list_forms()
            if all_forms:
                for f in all_forms:
                    print(f"  - {f.get('name', f.get('processCode', '?'))} (processCode: {f.get('processCode', '?')})")
            else:
                print("  (无)")
            return

        print(f"\n✅ 找到 {len(forms)} 个相关模板:")
        for f in forms:
            name = f.get("name", f.get("formName", f.get("processCode", "?")))
            code = f.get("processCode", f.get("formCode", "?"))
            print(f"  📋 {name}")
            print(f"     processCode: {code}")
            print(f"     URL: {f.get('url', 'N/A')}")

        if len(forms) == 1:
            process_code = forms[0].get("processCode", forms[0].get("formCode", ""))
        else:
            process_code = forms[0].get("processCode", forms[0].get("formCode", ""))
            print(f"\n⚠️ 多个模板，使用第一个: {process_code}")

    if not process_code:
        print("❌ 无法获取 processCode")
        return

    print(f"\n📋 模板ID: {process_code}")

    if args.test:
        print(f"\n🧪 测试发起审批实例...")
        test_initiate(process_code)

    print(f"\n✅ 验证完成！")
    print(f"\n下一步：将 processCode 填入 .env 文件")
    print(f"  DINGTALK_OA_TEMPLATE_ID={process_code}")


if __name__ == "__main__":
    main()
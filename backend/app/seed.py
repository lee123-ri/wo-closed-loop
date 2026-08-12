"""种子数据：灌入默认项目、人员、工单类型、优先级规则、解析规则、SLA、审批流、通知策略、示例工单。

运行：python -m app.seed
"""
from datetime import date, timedelta

from app.core.database import Base, SessionLocal, engine
from app.core.config import load_system_yaml
from app.models import (
    ApprovalFlow, ConfigDefinition, NotificationPolicy, ParsingRule,
    PriorityRule, Project, SLADefinition, User, WorkOrder, WorkOrderTypeKB,
    PersonProjectMap,
)


def _today(offset: int = 0) -> date:
    return date.today() + timedelta(days=offset)


def seed_users(db) -> dict:
    people = [
        ("王小宁", "executor"), ("于鸿飞", "executor"), ("高志强", "executor"),
        ("明南辉", "executor"), ("张雷雷", "executor"), ("塔拉", "executor"),
        ("明丹辉", "executor"), ("郭宝记", "executor"), ("陈立超", "executor"), ("周涛", "executor"),
        ("金惠良", "approver"), ("陈亮", "approver"), ("贾兴威", "approver"),
        ("admin", "admin"),
    ]
    ids = {}
    for name, role in people:
        u = db.query(User).filter(User.name == name).first()
        if not u:
            u = User(name=name, role=role, is_active=True)
            db.add(u)
            db.flush()
        ids[name] = u.id
    db.commit()
    return ids


def seed_projects(db, user_ids) -> dict:
    projs = [
        ("TL-YX", "通辽永兴风电场", "wind", "内蒙古"),
        ("WA-JZ", "瓮安建中HS300风电场", "wind", "贵州"),
        ("GZ-EQ", "瓜州二期风电场", "wind", "甘肃"),
        ("CT-TQ", "城投太旗光伏电站", "pv", "内蒙古"),
    ]
    # 责任人映射
    mapping = {
        "通辽永兴风电场": ["王小宁", "于鸿飞", "高志强", "明南辉", "明丹辉", "张雷雷", "陈立超", "周涛", "塔拉"],
        "瓮安建中HS300风电场": ["于鸿飞", "塔拉", "明南辉"],
        "瓜州二期风电场": ["高志强", "张雷雷", "王小宁"],
        "城投太旗光伏电站": ["张雷雷", "明南辉", "塔拉"],
    }
    ids = {}
    for code, name, ptype, region in projs:
        p = db.query(Project).filter(Project.code == code).first()
        if not p:
            p = Project(code=code, name=name, type=ptype, region=region)
            db.add(p)
            db.flush()
        ids[name] = p.id
    db.commit()

    for pname, persons in mapping.items():
        pid = ids[pname]
        for i, pname_ in enumerate(persons):
            uid = user_ids.get(pname_)
            if not uid:
                continue
            exists = db.query(PersonProjectMap).filter_by(project_id=pid, user_id=uid).first()
            if not exists:
                db.add(PersonProjectMap(project_id=pid, user_id=uid, is_default=(i == 0)))
    db.commit()
    return ids


def seed_config(db) -> None:
    """来源 + 状态 + 工单类型"""
    cfg = load_system_yaml().get("seed", {})

    # 来源
    for i, s in enumerate(cfg.get("sources", [])):
        if not db.query(ConfigDefinition).filter_by(category="source", code=s["code"]).first():
            db.add(ConfigDefinition(category="source", code=s["code"], name=s["name"], color=s.get("color"), sort_order=i))

    # 状态
    for i, (code, info) in enumerate(cfg.get("statuses", {}).items()):
        if not db.query(ConfigDefinition).filter_by(category="status", code=code).first():
            db.add(ConfigDefinition(
                category="status", code=code, name=info["name"], color=info.get("color"),
                sort_order=i, extra={"next": info.get("next", [])},
            ))

    # 工单类型（含 SOP — 基于 YWSYB-GLZY 官方指引）
    types = [
        # ── 原有 6 种 ──
        ("correction", "纠偏", "运行指标偏差、效率异常、PR值偏低等运营指标类问题",
         "金惠良", "P2",
         "YWSYB-GLZY-012",
         "规范七类核心异常指标的识别、监控、分发与闭环管理",
         "经营管理部监控→异常识别判定→定向分发PMO→整改执行→结果验证",
         [
             {"step": 1, "action": "确认偏差指标及超标幅度", "standard": "对比合同阈值或公司内控值", "role": "经营管理部"},
             {"step": 2, "action": "排查根因（设备/人员/环境/管理/合同）", "standard": "区分责任归属，明确是否我方原因", "role": "PMO+区域"},
             {"step": 3, "action": "制定纠偏措施并执行", "standard": "24h内响应，P1事项4h内启动", "role": "PMO+项目现场"},
             {"step": 4, "action": "验证纠偏效果", "standard": "指标恢复至正常范围，连续3天无异常", "role": "经营管理部"},
             {"step": 5, "action": "输出纠偏报告，纳入月度复盘", "standard": "含根因分析+措施+效果+预防建议", "role": "PMO"},
         ],
         "指标恢复至合同/内控阈值范围内，连续监测周期无复发",
         True,
         {"timeout_hours": 24, "action": "升级至事业部PMO专项支撑", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-007", "title": "三级风险管理机制"}, {"ref": "YWSYB-GLZY-012", "title": "异常指标监控工作指引"}, {"ref": "YWSYB-GLZY-010", "title": "风机产品运营管理指引"}],
        ),
        ("customer", "客户沟通", "客户满意度调查、月度汇报、客户关系维护",
         "贾兴威", "P2",
         "YWSYB-GLZY-008",
         "规范传统运维项目客户满意度管理，涵盖满意度调查与客户投诉（抱怨性/追责性）全流程管控",
         "月度线上满意度调查→结果分析→整改跟踪；客诉分类→处理→回访闭环",
         [
             {"step": 1, "action": "月度满意度调查发放与回收", "standard": "每月通过线上渠道完成，回收率≥80%", "role": "区域PMO"},
             {"step": 2, "action": "分析满意度结果，识别不满项目", "standard": "满意度<80分需重点关注", "role": "经营管理部"},
             {"step": 3, "action": "客诉分类：抱怨性/追责性", "standard": "抱怨性=无经济损失；追责性=有损失需补偿", "role": "PMO"},
             {"step": 4, "action": "制定整改方案并执行", "standard": "追责性客诉24h内响应，3天内出方案", "role": "项目现场+PMO"},
             {"step": 5, "action": "客户回访确认满意度恢复", "standard": "月度跟踪，连续2月≥80分可关闭", "role": "区域PMO"},
         ],
         "客户满意度连续2月≥80分，客诉关闭且客户确认满意",
         True,
         {"timeout_hours": 72, "action": "升级至事业部负责人", "target": "事业部分管领导"},
         [{"ref": "YWSYB-GLZY-008", "title": "客户满意度管理指引"}, {"ref": "YWSYB-GLZY-012", "title": "异常指标监控工作指引"}],
        ),
        ("relation", "关系维护", "与业主、调度、供应商、政府等外部关系维护",
         "陈亮", "P2",
         "YWSYB-GLZY-029",
         "维护项目相关外部关系，确保信息畅通、协同高效，支撑项目稳定运营",
         "识别关键关系→定期沟通→问题预警→协同解决→关系评估",
         [
             {"step": 1, "action": "梳理项目关键外部关系人清单", "standard": "含业主/调度/供应商/政府等，每月更新", "role": "区域PMO"},
             {"step": 2, "action": "制定沟通计划并执行", "standard": "重要关系每月至少1次正式沟通", "role": "项目负责人"},
             {"step": 3, "action": "记录沟通要点和待办事项", "standard": "每次沟通后24h内录入", "role": "项目负责人"},
             {"step": 4, "action": "跟踪待办事项闭环", "standard": "纳入月度PMO复盘", "role": "区域PMO"},
         ],
         "关键关系人满意度良好，无因关系问题导致的项目风险",
         True,
         None,
         [{"ref": "YWSYB-GLZY-029", "title": "PMO工作机制落实指引"}],
        ),
        ("hazard", "隐患整改", "安全检查发现的隐患、设备缺陷整改、安全设施维护",
         "金惠良", "P1",
         "YWSYB-GLZY-009",
         "建立基于数字化系统联动的预警管理机制，通过数据分析识别异常，依托EAM系统实现工单规范流转",
         "PowerInsight数据分析→预警识别→EAM工单生成→审核派发→排查处理→结果反馈→闭环归档",
         [
             {"step": 1, "action": "系统识别或人工发现隐患/缺陷", "standard": "PowerInsight自动推送或现场巡检发现", "role": "数智化小组/项目现场"},
             {"step": 2, "action": "生成预警工单，标定闭环时限", "standard": "高频故障/亚健康等异常自动标定时限", "role": "EAM系统"},
             {"step": 3, "action": "PMO审核工单信息并派发", "standard": "1个工作日内完成审核，确认机组归属/质保期", "role": "风机PMO"},
             {"step": 4, "action": "现场排查处理", "standard": "按闭环时限执行，复杂异常24h内申请技术支持", "role": "项目现场"},
             {"step": 5, "action": "处理结果反馈与闭环", "standard": "含处理过程/结果/佐证材料，PMO确认后归档", "role": "PMO+项目现场"},
         ],
         "隐患已消除，处理结果经PMO审核确认，佐证材料完整归档",
         True,
         {"timeout_hours": 4, "action": "升级至三级管理第一责任人", "target": "事业部技术管理部"},
         [{"ref": "YWSYB-GLZY-009", "title": "风机设备预警工单管理指引"}, {"ref": "YWSYB-GLZY-005", "title": "风机技术支持工作指引"}, {"ref": "YWSYB-GLZY-007", "title": "三级风险管理机制"}],
        ),
        ("nonstandard", "非标任务", "年度计划内的非标准化任务、重点工作督办",
         "陈亮", "P2",
         "YWSYB-GLZY-001",
         "规范事业部重点工作事项推进，强化过程监督与成果交付，确保重点事项按期高质量完成",
         "事项接收→执行监控→节点跟踪→验收关闭",
         [
             {"step": 1, "action": "明确任务目标、范围及交付要求", "standard": "录入《事业部重点工作督办表》，含里程碑节点", "role": "事项发布人"},
             {"step": 2, "action": "主责人每日更新进度", "standard": "含当前进展/存在问题/下一步计划", "role": "主责人"},
             {"step": 3, "action": "周跟踪+月通报", "standard": "每周五汇总进度偏差，月度例会通报", "role": "督办人"},
             {"step": 4, "action": "完成验收关闭", "standard": "完成后8h内发起验收→辅导人组织验收→督办人标记关闭", "role": "主责人+辅导人"},
         ],
         "交付物达标，辅导人验收通过，督办人确认关闭",
         True,
         {"timeout_hours": 24, "action": "超期通报+书面说明", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-001", "title": "重点工作督办管理指引"}, {"ref": "YWSYB-GLZY-029", "title": "PMO工作机制落实指引"}],
        ),
        # ── 新增 6 种 ──
        ("alert", "预警工单", "风机设备预警、PowerInsight系统自动推送的异常告警",
         "金惠良", "P1",
         "YWSYB-GLZY-009",
         "基于PowerInsight系统数据分析识别高频故障、亚健康等异常机组，自动生成预警工单并规范流转",
         "PowerInsight数据采集→预警模型识别→自动推送EAM→PMO审核→派发→排查→闭环",
         [
             {"step": 1, "action": "PowerInsight系统自动识别异常", "standard": "高频故障/亚健康/振动异常等自动触发", "role": "数智化小组"},
             {"step": 2, "action": "预警工单自动推送至EAM", "standard": "含机组编号/异常性质/运行数据特征", "role": "系统自动"},
             {"step": 3, "action": "PMO审核工单并标定闭环时限", "standard": "1个工作日内完成审核派发", "role": "风机PMO"},
             {"step": 4, "action": "现场排查处理", "standard": "按时限执行，复杂异常24h内申请技术支持", "role": "项目现场"},
             {"step": 5, "action": "处理结果反馈与闭环归档", "standard": "PMO确认后归档，纳入月度复盘", "role": "PMO+项目现场"},
         ],
         "预警已消除，处理结果经PMO确认，数据回传PowerInsight",
         True,
         {"timeout_hours": 4, "action": "升级至事业部技术管理部", "target": "技术管理部负责人"},
         [{"ref": "YWSYB-GLZY-009", "title": "风机设备预警工单管理指引"}, {"ref": "YWSYB-GLZY-005", "title": "风机技术支持工作指引"}],
        ),
        ("contract", "合同履约", "保电量/保收益/合同指标考核、扣款风险、双细则超标",
         "贾兴威", "P1",
         "YWSYB-GLZY-007",
         "规范合同履约类风险管控，覆盖保电量/保收益/设备可靠性/双细则等合同指标考核",
         "合约指标监控→偏差识别→风险分级→整改方案→PMO跟踪→闭环验证",
         [
             {"step": 1, "action": "监控合同指标达成情况", "standard": "按月对比合同阈值，识别偏差", "role": "经营管理部"},
             {"step": 2, "action": "风险分级评估", "standard": "按影响金额和频次定级（一级>10万/二级5-10万/三级1-5万）", "role": "PMO"},
             {"step": 3, "action": "制定整改方案并执行", "standard": "P1事项需事业部审批，P2/P3由PMO直接推动", "role": "PMO+区域"},
             {"step": 4, "action": "跟踪整改效果", "standard": "按风险等级定期跟踪（一级双周/二级双周/三级月）", "role": "PMO"},
             {"step": 5, "action": "闭环归档", "standard": "指标恢复+整改报告+预防措施", "role": "PMO+经营管理部"},
         ],
         "合同指标恢复至阈值范围内，考核风险已消除或已制定有效防控措施",
         True,
         {"timeout_hours": 24, "action": "升级至事业部负责人及董办会", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-007", "title": "三级风险管理机制"}, {"ref": "YWSYB-GLZY-012", "title": "异常指标监控工作指引"}, {"ref": "YWSYB-GLZY-021", "title": "集中式运维产品指标体系"}],
        ),
        ("payment", "回款结算", "应签未签确认单、尾款结算、据实结算、对账争议",
         "陈亮", "P2",
         "YWSYB-GLZY-007",
         "规范回款结算类事项管理，确保款项按期回收，降低财务风险",
         "账期监控→应签未签识别→催收/协商→争议解决→回款确认",
         [
             {"step": 1, "action": "监控回款账期", "standard": "按合同约定回款节点跟踪", "role": "经营管理部"},
             {"step": 2, "action": "识别应签未签/逾期未回", "standard": "账期>30天启动预警，>90天升级", "role": "经营管理部"},
             {"step": 3, "action": "发起催收或协商", "standard": "先区域沟通，无效则升级至事业部", "role": "区域PMO→事业部"},
             {"step": 4, "action": "争议解决与确认", "standard": "涉及争议需营销/法务协同", "role": "PMO+营销+法务"},
             {"step": 5, "action": "回款确认闭环", "standard": "款项到账+确认单签回", "role": "经营管理部"},
         ],
         "款项到账，确认单已签回，账期恢复正常",
         True,
         {"timeout_hours": 72, "action": "升级至事业部负责人+营销中心", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-007", "title": "三级风险管理机制"}, {"ref": "YWSYB-GLZY-012", "title": "异常指标监控工作指引"}],
        ),
        ("insurance", "保险理赔", "电站财产险/机损险事故报险、定损、理赔全流程",
         "金惠良", "P2",
         "YWSYB-GLZY-007",
         "规范电站保险事故处理流程，确保理赔及时、证据完整、损失最小化",
         "事故发生→报险→现场勘查→定损→资料提交→理赔跟进→结案",
         [
             {"step": 1, "action": "事故发生后立即报险", "standard": "24h内报险，重大事故2h内", "role": "项目现场"},
             {"step": 2, "action": "现场证据收集与保全", "standard": "照片/视频/运行记录/维修记录/损失清单", "role": "项目现场+区域PMO"},
             {"step": 3, "action": "配合保险公司定损", "standard": "提供完整证据链，必要时引入第三方评估", "role": "区域PMO+法务"},
             {"step": 4, "action": "理赔资料提交与跟进", "standard": "按保险公司要求完整提交，定期跟进进度", "role": "经营管理部"},
             {"step": 5, "action": "结案与复盘", "standard": "理赔款到账，输出事故分析+预防措施", "role": "经营管理部+PMO"},
         ],
         "理赔款到账，事故分析报告完成，预防措施已落实",
         True,
         {"timeout_hours": 48, "action": "升级至事业部负责人+法务", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-007", "title": "三级风险管理机制"}, {"ref": "YWSYB-GLZY-008", "title": "客户满意度管理指引"}],
        ),
        ("compliance", "合规管理", "消防验收、安全合规检查、资质审核、监管要求整改",
         "金惠良", "P1",
         "YWSYB-GLZY-007",
         "规范合规类事项管理，确保项目满足消防/安全/资质等监管要求，避免处罚风险",
         "合规要求识别→自查/检查→不符合项整改→验收确认→闭环归档",
         [
             {"step": 1, "action": "识别合规要求", "standard": "消防/安全/环保/资质/许可等法规要求", "role": "区域PMO"},
             {"step": 2, "action": "自查或配合外部检查", "standard": "按检查清单逐项核实", "role": "项目现场"},
             {"step": 3, "action": "不符合项整改", "standard": "P1事项立即整改，P2/P3限时整改", "role": "项目现场+PMO"},
             {"step": 4, "action": "整改验收", "standard": "内部验收+外部验收（如需）", "role": "PMO+监管部门"},
             {"step": 5, "action": "归档与持续监控", "standard": "整改报告+验收文件归档，纳入定期复查", "role": "经营管理部"},
         ],
         "整改完成，验收通过，相关文件归档，无遗留合规风险",
         True,
         {"timeout_hours": 24, "action": "升级至事业部负责人", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-007", "title": "三级风险管理机制"}, {"ref": "YWSYB-GLZY-001", "title": "重点工作督办管理指引"}],
        ),
        ("special", "专项服务", "专项服务项目立项、执行、交付、日报、结算全流程",
         "陈亮", "P2",
         "YWSYB-GLZY-022",
         "规范专项服务项目全生命周期管理，涵盖立项/预算/交付/日报/结算/满意度",
         "立项→预算审批→执行交付→日报跟踪→结算→客户满意度回访",
         [
             {"step": 1, "action": "专项服务项目立项", "standard": "含项目范围/预算/周期/交付标准", "role": "PMO"},
             {"step": 2, "action": "预算审批与资源配置", "standard": "按预算管理制度审批，配置人员/物料", "role": "PMO+经营管理部"},
             {"step": 3, "action": "执行交付与日报跟踪", "standard": "每日提交执行日报，PMO跟踪进度", "role": "项目现场+PMO"},
             {"step": 4, "action": "交付验收", "standard": "按合同约定交付标准验收", "role": "PMO+客户"},
             {"step": 5, "action": "结算与满意度回访", "standard": "完成结算，客户满意度调查", "role": "经营管理部+区域PMO"},
         ],
         "交付验收通过，结算完成，客户满意度达标",
         True,
         {"timeout_hours": 48, "action": "升级至事业部负责人", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-022", "title": "专项服务项目预算管理指引"}, {"ref": "YWSYB-GLZY-023", "title": "专项服务项目交付重点跟踪"}, {"ref": "YWSYB-GLZY-024", "title": "专项服务项目客户满意度"}],
        ),
        ("other", "其他", "其他无法归入上述类型的工单",
         "金惠良", "P3",
         None,
         "处理无法归入上述类型的其他工作事项",
         "按实际情况灵活处理",
         [
             {"step": 1, "action": "明确事项内容和交付要求", "standard": "与事项发布人确认", "role": "主责人"},
             {"step": 2, "action": "执行并记录过程", "standard": "按约定标准完成", "role": "主责人"},
             {"step": 3, "action": "交付验收", "standard": "事项发布人确认完成", "role": "事项发布人"},
         ],
         "事项发布人确认完成",
         False,
         None,
         [],
        ),
    ]
    # approver by name
    name_to_id = {u.name: u.id for u in db.query(User).all()}
    for i, item in enumerate(types):
        code, name, desc, approver_name, pri = item[:5]
        guidance_ref = item[5] if len(item) > 5 else None
        sop_purpose = item[6] if len(item) > 6 else None
        sop_scope = item[7] if len(item) > 7 else None
        sop_steps = item[8] if len(item) > 8 else None
        sop_acceptance = item[9] if len(item) > 9 else None
        sop_backfill = item[10] if len(item) > 10 else True
        sop_escalation = item[11] if len(item) > 11 else None
        sop_related = item[12] if len(item) > 12 else None
        existing = db.query(WorkOrderTypeKB).filter_by(type_code=code).first()
        if not existing:
            db.add(WorkOrderTypeKB(
                type_code=code, name=name, desc=desc,
                default_approver_id=name_to_id.get(approver_name),
                default_priority=pri, sort_order=i,
                guidance_ref=guidance_ref,
                sop_purpose=sop_purpose,
                sop_scope=sop_scope,
                sop_steps=sop_steps,
                sop_acceptance=sop_acceptance,
                sop_backfill_required=sop_backfill,
                sop_escalation=sop_escalation,
                sop_related_guidance=sop_related,
            ))
        else:
            # 更新已有记录的 SOP 字段
            existing.guidance_ref = guidance_ref
            existing.sop_purpose = sop_purpose
            existing.sop_scope = sop_scope
            existing.sop_steps = sop_steps
            existing.sop_acceptance = sop_acceptance
            existing.sop_backfill_required = sop_backfill
            existing.sop_escalation = sop_escalation
            existing.sop_related_guidance = sop_related
    db.commit()


def seed_rules(db) -> None:
    if db.query(PriorityRule).count() == 0:
        for i, (pat, label, pri) in enumerate([
            ("(安全|伤亡|事故|火灾|爆炸|触电|坠落|人身|生命)", "涉及安全/人身风险", "P1"),
            ("(扣款|罚款|考核超标|违约|赔偿|合同风险|双细则超标|电价损失)", "涉及合同扣款/考核罚款", "P1"),
            ("(停运|停机|跳闸|脱网|断网|全站停电|大面积故障)", "涉及设备停运/全站故障", "P1"),
            ("(客户投诉|业主不满|满意度.*低|投诉|纠纷)", "客户投诉/业主不满", "P2"),
            ("(监视告警|偏差.*超|指标.*异常|效率.*低|PR.*降|功率.*低)", "监视告警触发", "P2"),
            ("(判定会|会议决议|领导交办|贾总|陈亮)", "判定会决议/领导交办", "P2"),
            ("(隐患|缺陷|整改|检查.*未|排查)", "安全隐患/缺陷整改", "P2"),
            ("(年度计划|月度|季度|例行|定期|日常)", "年度计划/例行任务", "P3"),
            ("(培训|汇报|报告|统计|盘点|归档)", "培训/汇报/文档类", "P3"),
        ]):
            db.add(PriorityRule(pattern=pat, label=label, priority=pri, sort_order=i, enabled=True))

    if db.query(ParsingRule).count() == 0:
        for i, (name, pat, w) in enumerate([
            ("含责任人", "(王小宁|于鸿飞|高志强|明南辉|张雷雷|塔拉|明丹辉|郭宝记|陈立超|周涛|负责|责任人)", 3),
            ("含截止时间", "(\\d+月\\d+[日号]|\\d+[\\/\\-]\\d+|截止|期限|ddl|deadline|完成|前)", 2),
            ("含行动动词", "(完成|跟踪|跟进|排查|协调|整改|检查|提交|上报|处理|修复|采购|组织|开展|编制|汇报|确认)", 2),
            ("含项目名", "(通辽永兴|瓮安建中|瓜州二期|城投太旗|金水口|黑茨河|盐锅峡|风电场|光伏)", 1),
            ("含偏差/问题", "(偏差|超标|异常|滞后|不达标|未完成|故障|缺陷|隐患|问题|风险|投诉)", 2),
            ("含会议决议", "(判定会|会议|决议|决定|要求|安排)", 1),
            ("含审批/流程", "(审批|流程|工单|闭环|验收|确认)", 1),
        ]):
            db.add(ParsingRule(name=name, pattern=pat, weight=w, enabled=True, sort_order=i))
    db.commit()


def seed_sla(db) -> None:
    if db.query(SLADefinition).count() == 0:
        for pri, dd, wb, eh in [("P1", 1, 4, 24), ("P2", 3, 24, 72), ("P3", 7, 48, 168)]:
            db.add(SLADefinition(priority=pri, deadline_days=dd, warn_before_hours=wb, escalate_hours=eh))
    db.commit()


def seed_approval_flows(db) -> None:
    if db.query(ApprovalFlow).count() == 0:
        p1 = ApprovalFlow(priority="P1", name="P1 紧急审批流", enabled=True,
            nodes=[
                {"type": "start", "title": "提交人", "sub": "创建工单", "role": "creator"},
                {"type": "approval", "title": "项目主管", "sub": "金惠良", "role": "金惠良", "timeout_days": 0.5},
                {"type": "approval", "title": "分管领导", "sub": "贾兴威", "role": "贾兴威", "timeout_days": 1},
                {"type": "exec", "title": "执行", "sub": "责任人", "role": "executor"},
                {"type": "approval", "title": "验收", "sub": "审批人", "role": "approver", "timeout_days": 0.5},
                {"type": "end", "title": "闭环", "sub": "完成", "role": ""},
            ],
            escalation={"timeout_hours": 4, "action": "电话DING上级", "target": "贾兴威"})
        p2 = ApprovalFlow(priority="P2", name="P2 普通审批流", enabled=True,
            nodes=[
                {"type": "start", "title": "提交人", "sub": "创建工单", "role": "creator"},
                {"type": "approval", "title": "审批人", "sub": "金惠良/陈亮", "role": "approver", "timeout_days": 1},
                {"type": "exec", "title": "执行", "sub": "责任人", "role": "executor"},
                {"type": "approval", "title": "验收", "sub": "审批人", "role": "approver", "timeout_days": 1},
                {"type": "end", "title": "闭环", "sub": "完成", "role": ""},
            ],
            escalation={"timeout_hours": 24, "action": "电话DING", "target": "上级"})
        p3 = ApprovalFlow(priority="P3", name="P3 低优先审批流", enabled=True,
            nodes=[
                {"type": "start", "title": "提交人", "sub": "创建工单", "role": "creator"},
                {"type": "approval", "title": "审批人", "sub": "审批", "role": "approver", "timeout_days": 2},
                {"type": "exec", "title": "执行", "sub": "责任人", "role": "executor"},
                {"type": "end", "title": "闭环", "sub": "完成", "role": ""},
            ],
            escalation={"timeout_hours": 48, "action": "应用DING", "target": "上级"})
        db.add_all([p1, p2, p3])
    db.commit()


def seed_notification_policies(db) -> None:
    if db.query(NotificationPolicy).count() == 0:
        matrix = [
            ("P1", "phone_ding", "work_notify", "robot_mention"),
            ("P2", "app_ding", "work_notify", "robot_mention"),
            ("P3", "work_notify", "robot_mention"),
        ]
        events = ["dispatch", "unread", "sla_warn", "sla_breach", "sla_breach_72h"]
        for pri, *ch in matrix:
            for ev in events:
                db.add(NotificationPolicy(priority=pri, event=ev, channels=list(ch), enabled=True))
    db.commit()


def seed_workorders(db, user_ids, proj_ids) -> None:
    if db.query(WorkOrder).count() > 0:
        return
    name_to_id = user_ids
    # 类型 id
    type_codes = {
        "纠偏": "correction", "客户沟通": "customer", "关系维护": "relation",
        "隐患整改": "hazard", "非标任务": "nonstandard", "其他": "other",
    }
    src_map = {"年度计划": "plan", "监视告警": "alert", "判定会": "meeting", "手动": "manual"}
    rows = [
        ("RW-2026-0001", "P2", "年度计划", "通辽永兴风电场", "变桨系统技改跟踪", "纠偏", "业主技改方案流标，进度滞后", "跟进招投标进度，每周汇报", "王小宁", "金惠良", -2, "overdue", 3, 2),
        ("RW-2026-0002", "P1", "监视告警", "通辽永兴风电场", "AGC双细则考核超标纠偏", "纠偏", "7月双细则考核扣分超标15%", "排查AGC响应延迟原因，协调厂家修模", "明南辉", "金惠良", 5, "executing", 0, 0),
        ("RW-2026-0003", "P3", "判定会", "通辽永兴风电场", "沉降观测检测补充", "非标任务", "08-03判定会发现漏项", "联系检测单位，11月前完成", "于鸿飞", "陈亮", 90, "pending", 0, 0),
        ("RW-2026-0004", "P2", "年度计划", "瓮安建中HS300风电场", "客户月度汇报满意度偏低整改", "客户沟通", "上月客户满意度评分仅72分", "本月增加一次现场拜访，解决客户反馈的3个问题", "于鸿飞", "贾兴威", -1, "overdue", 2, 1),
        ("RW-2026-0005", "P1", "手动", "瓜州二期风电场", "新员工安全培训交底", "隐患整改", "新入场人员未完成三级安全教育", "组织安全培训，完成考试并归档", "高志强", "金惠良", -4, "overdue", 3, 4),
        ("RW-2026-0006", "P2", "监视告警", "城投太旗光伏电站", "组件清洗质量不达标", "纠偏", "上月清洗后PR值未提升", "要求清洗单位返工，重新验收", "张雷雷", "陈亮", 3, "verifying", 0, 0),
        ("RW-2026-0007", "P3", "年度计划", "通辽永兴风电场", "预防性试验准备-停电协调", "非标任务", "年度计划8月停电窗口", "协调调度确认8/19-20停电时间", "于鸿飞", "金惠良", 0, "executing", 0, 0),
        ("RW-2026-0008", "P3", "判定会", "通辽永兴风电场", "安全培训交底确认", "客户沟通", "判定会确认已完成但无记录", "补录安全培训交底记录并上传", "王小宁", "金惠良", -7, "closed", 0, 0),
        ("RW-2026-0009", "P2", "年度计划", "通辽永兴风电场", "风机定检第一批旁站监督", "非标任务", "定检队伍进场不稳定", "协调定检单位稳定出勤，做好旁站记录", "高志强", "陈亮", -10, "closed", 0, 0),
        ("RW-2026-0010", "P3", "手动", "瓜州二期风电场", "备品备件库房盘点", "其他", "季度例行盘点", "完成盘点并更新台账", "高志强", "金惠良", -15, "closed", 0, 0),
        ("RW-2026-0011", "P3", "年度计划", "瓮安建中HS300风电场", "月度运营分析报告", "其他", "7月月度报告提交", "按模板完成7月运营分析报告", "塔拉", "贾兴威", -3, "closed", 0, 0),
        ("RW-2026-0012", "P1", "监视告警", "城投太旗光伏电站", "逆变器效率异常排查", "纠偏", "3号逆变器效率连续3天低于95%", "现场排查逆变器，必要时更换", "张雷雷", "陈亮", 1, "approving", 0, 0),
        ("RW-2026-0013", "P2", "判定会", "通辽永兴风电场", "涉网试验-1号SVG未完成", "非标任务", "判定会发现1号SVG未完成涉网试验", "8月内完成1号SVG涉网试验", "明南辉", "金惠良", 25, "dispatched", 0, 0),
        ("RW-2026-0014", "P3", "年度计划", "瓮安建中HS300风电场", "消防设施月度检查", "隐患整改", "8月消防检查", "完成灭火器、消防栓检查并记录", "塔拉", "金惠良", -5, "closed", 0, 0),
        ("RW-2026-0015", "P2", "手动", "城投太旗光伏电站", "双细则日报数据核对", "纠偏", "本周功率预测准确率偏低", "联系功率预测厂家修模", "明南辉", "陈亮", 2, "verifying", 0, 0),
    ]
    for code, pri, src, proj, title, wtype, reason, action, person, approver, dl_off, status, esc, od in rows:
        type_kb = db.query(WorkOrderTypeKB).filter_by(type_code=type_codes[wtype]).first()
        wo = WorkOrder(
            code=code, title=title, reason=reason, action=action,
            project_id=proj_ids[proj], person_id=name_to_id[person], approver_id=name_to_id[approver],
            type_id=type_kb.id if type_kb else None,
            source_code=src_map[src], status=status, priority=pri,
            created_date=_today(dl_off - 7 if "closed" in status or status == "overdue" else dl_off - 3),
            deadline=_today(dl_off),
            completed_date=_today(dl_off) if status == "closed" else None,
            oa_id=f"OA-2026080{abs(dl_off)%9+1}-00{abs(dl_off)%9+1}" if status not in ("pending",) else None,
            escalation_level=esc, overdue_days=od,
            conclusion="已完成" if status == "closed" else None,
        )
        db.add(wo)
    db.commit()


def run() -> None:
    print("→ 创建表（如不存在）...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print("→ 灌入用户...")
        u = seed_users(db)
        print("→ 灌入项目...")
        p = seed_projects(db, u)
        print("→ 灌入配置（来源/状态/类型）...")
        seed_config(db)
        print("→ 灌入规则...")
        seed_rules(db)
        print("→ 灌入 SLA...")
        seed_sla(db)
        print("→ 灌入审批流...")
        seed_approval_flows(db)
        print("→ 灌入通知策略...")
        seed_notification_policies(db)
        print("→ 灌入示例工单...")
        seed_workorders(db, u, p)
        print("✓ 种子数据完成")
    finally:
        db.close()


if __name__ == "__main__":
    run()

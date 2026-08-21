"""种子数据：灌入默认项目、人员、工单类型、优先级规则、解析规则、SLA、审批流、通知策略、示例工单。

运行：python -m app.seed
"""
from datetime import date, timedelta

from app.core.database import Base, SessionLocal, engine
from app.core.config import load_system_yaml
from app.models import (
    ApprovalFlow, ConfigDefinition, NotificationPolicy, ParsingRule,
    PriorityRule, Project, SLADefinition, User, WorkOrder, WorkOrderTypeKB,
    PersonProjectMap, RoleAssignment,
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


def seed_roles(db) -> None:
    """灌入组织角色 → 人员映射（审批流用角色编码，具体人名可在后台配置）。

    角色编码对应指引里的角色层级：
      division_head=事业部负责人, pmo=事业部PMO/经营分析, delivery_pmo=交付/专项PMO
    """
    people = {u.name: u.id for u in db.query(User).all()}
    roles = [
        ("division_head", "事业部负责人", "贾兴威"),
        ("pmo", "事业部PMO/经营分析", "金惠良"),
        ("delivery_pmo", "交付/专项PMO", "陈亮"),
    ]
    for i, (code, name, person) in enumerate(roles):
        ra = db.query(RoleAssignment).filter_by(role_code=code).first()
        if not ra:
            ra = RoleAssignment(role_code=code, sort_order=i)
            db.add(ra)
        ra.role_name = name
        ra.user_id = people.get(person)
    db.commit()


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

# ── 工单类型：按 YWSYB-GLZY 真实指引重映射（2026-08-19） ──
    # 依据：012《经营管理部异常指标监控工作指引》七类核心异常指标
    #       + 007 项目风险 + 001 重点工作督办 + 009 设备预警工单 + 022/023/024 专项服务
    # 调整：insurance(保险理赔) 无对应指引已删除；payment(回款结算) 归入 unsigned(应签未签)；
    #       relation(关系维护)/compliance(合规)/nonstandard(非标) 无独立指引，分别并入对应类/删除。
    # 阈值：全部取自指引原文，逐条核对见 docs/规则台账-待业务确认.md D2 表。
    # 注意：default_approver / default_priority 仍待业务确认（台账 C 节），此处为便于建单的占位默认值。
    types = [
        # ── 012 七类核心异常指标 ──
        ("customer", "客户满意度/客户投诉", "月度满意度调查 + 抱怨性/追责性客诉全流程管控",
         "division_head", "P2",
         "YWSYB-GLZY-008",
         "规范传统运维项目客户满意度调查与客户投诉全流程管控",
         "月度线上满意度调查→结果整理筛选→问题项目回访→整改跟踪→验收闭环；客诉分类→处理→回函→闭环",
         [
             {"step": 1, "action": "问卷分发(每月25日前)+区域3日内组织完成提交", "standard": "线上渠道确保接收,规定日未提交按0分", "role": "综合管理经理/区域负责人"},
             {"step": 2, "action": "结果统计并筛选不满意(分数<80分 或 客户明确表达具体诉求)", "standard": "问卷提交截止日后1个工作日内完成统计", "role": "综合管理经理/经营分析"},
             {"step": 3, "action": "问题项目逐一回访,填写《客户满意度调查回访记录表》", "standard": "整理完成后3-5个工作日内完成回访", "role": "PMO/经营分析经理"},
             {"step": 4, "action": "制定整改措施(明确目标/责任人/时限);整改周期超1个月的分阶段计划,每5个工作日同步进展,次月20日前完成跟踪", "standard": "措施要可操作、可评价", "role": "PMO牵头+责任部门"},
             {"step": 5, "action": "整改验收:客户签字确认《满意度整改验收单》", "standard": "业主明确表示满意或不再追责后方可闭环", "role": "PMO"},
         ],
         "整改以客户签字《满意度整改验收单》为据;业主明确满意或不再追责后闭环",
         True,
         {"timeout_hours": 48, "action": "连续两次满意度调查无改进→按《项目风险管理办法》申请风险升级", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-007", "title": "项目风险管理办法(暂行版)"}, {"ref": "YWSYB-GLZY-012", "title": "经营管理部异常指标监控工作指引"}],
        ),
        ("contract", "履约指标异常", "电量、设备可靠性(TBA/MTBF/MTTR/FLG)、等效可利用小时数等合同/内控指标未达要求",
         "pmo", "P1",
         "YWSYB-GLZY-010",
         "规范风机产品履约指标监控与偏差纠偏,指标阈值首选合同值、次选内控值",
         "按月核算指标→与合同值/内控值比对→识别偏差→风险分级→PMO牵头整改→验证闭环",
         [
             {"step": 1, "action": "按月核算TBA/MTBF/MTTR/FLG等指标,与合同值/内控值比对", "standard": "参照GB/T25385、NB/T31047,HS300 TBA≥95%、HS400≥97%等", "role": "PMO+经营管理部"},
             {"step": 2, "action": "识别偏差:未达合同阈值或内控值即判定异常", "standard": "根据合同约定或公司内控值判定", "role": "PMO"},
             {"step": 3, "action": "风险分级:按007(影响金额>10万/5-10万/1-5万 或 半年累计3次不达标)定级", "standard": "结合合同指标类风险分级表", "role": "PMO+经营管理部"},
             {"step": 4, "action": "整改:PMO牵头\"从问题到解决\",接收异常后启动整改", "standard": "接收异常后1个工作日内启动整改", "role": "PMO"},
             {"step": 5, "action": "验证闭环:整改后验证达标/未达标", "standard": "未达标由经营管理部要求PMO 7个工作日内补充整改", "role": "经营管理部"},
         ],
         "指标恢复至合同/内控阈值,经营管理部审核确认闭环",
         True,
         {"timeout_hours": 24, "action": "按007风险分级:一级报董办会/二级辅导员决策/三级事业部月度跟踪", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-021", "title": "集中式运维产品指标体系"}, {"ref": "YWSYB-GLZY-012", "title": "经营管理部异常指标监控工作指引"}, {"ref": "YWSYB-GLZY-007", "title": "项目风险管理办法(暂行版)"}],
        ),
        ("unsigned", "应签未签确认单", "已完成服务/节点需签回确认单未签回,或客户异议/资料缺失影响签回",
         "delivery_pmo", "P2",
         "YWSYB-GLZY-012",
         "规范应签未签确认单跟踪,降低资金占用",
         "账期监控→识别应签未签→风险分级→催收/协商→签回闭环",
         [
             {"step": 1, "action": "监控应签未签确认单(资金占用天数)与据实结算回款", "standard": "以计划部统计数据为准", "role": "经营管理部"},
             {"step": 2, "action": "识别异常:确认单未签回/客户异议/资料缺失,或据实结算未按期结回", "standard": "按012应签未签异常判定", "role": "经营管理部"},
             {"step": 3, "action": "风险分级:按007资金占用天数分档", "standard": "资金占用天数>15000 / 5000-15000 / 3000-5000 万元*天 对应一/二/三级", "role": "PMO+计划部"},
             {"step": 4, "action": "催收/协商:先区域沟通,无效则升级事业部", "standard": "营销部门应签未签协同", "role": "区域PMO→事业部"},
             {"step": 5, "action": "签回闭环:确认单签回/款项结回", "standard": "经营管理部审核确认", "role": "经营管理部"},
         ],
         "确认单签回或款项结回,账期恢复正常",
         True,
         {"timeout_hours": 72, "action": "按007资金占用天数分档升级至事业部负责人", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-007", "title": "项目风险管理办法(暂行版)"}],
        ),
        ("penalty", "考核扣款", "按合同约定或内部规则产生的扣款,或重复发生扣款",
         "pmo", "P1",
         "YWSYB-GLZY-012",
         "规范考核扣款异常管理与整改",
         "识别扣款→风险分级→PMO整改→验证闭环",
         [
             {"step": 1, "action": "识别考核扣款异常(含双细则考核、内部规则扣款、重复扣款)", "standard": "按012考核扣款异常定义", "role": "经营管理部"},
             {"step": 2, "action": "风险分级:按007考核单金额分档", "standard": "考核单金额>10万/5-10万/1-5万元 对应一/二/三级", "role": "PMO+经营管理部"},
             {"step": 3, "action": "整改:PMO牵头,接收异常后启动整改", "standard": "1个工作日内启动", "role": "PMO"},
             {"step": 4, "action": "验证闭环:整改后验证达标/未达标", "standard": "未达标7个工作日内补充整改", "role": "经营管理部"},
         ],
         "扣款风险消除或已制定有效防控措施",
         True,
         {"timeout_hours": 24, "action": "按007考核单金额分档升级", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-007", "title": "项目风险管理办法(暂行版)"}],
        ),
        ("risk", "项目风险", "已识别未闭环的项目风险(合同/预算/履约交付/客户满意度/回款/安全合规等)",
         "division_head", "P1",
         "YWSYB-GLZY-007",
         "规范项目全周期风险分级管控,早发现早介入",
         "风险识别(投标前/合同签订后/交付运维/收尾结算)→分级→动态监控→应对执行→升降级管理",
         [
             {"step": 1, "action": "风险识别:覆盖投标前→合同签订后→交付运维→收尾结算四阶段", "standard": "营销中心/产品管理部/区域/项目各自识别,无例外项目", "role": "营销/产品管理部/区域/项目"},
             {"step": 2, "action": "风险分级:按\"发生概率×影响程度\"定三级(低)/二级(中)/一级(危机)", "standard": "影响金额>10万/5-10万/1-5万 或 客诉连续2/3/6个月低于80分等", "role": "事业部"},
             {"step": 3, "action": "动态监控:一级/二级每双周、三级每月跟进,纳入风险台账", "standard": "跟进损失变化/拦截效果/升级迹象", "role": "事业部+辅导员"},
             {"step": 4, "action": "应对执行:三级事业部月度跟踪、二级辅导员决策、一级董办会决策", "standard": "权责闭环、责任到人", "role": "辅导员/董办会"},
             {"step": 5, "action": "升降级:风险有效控制则降级,升级触发则按流程提报", "standard": "三级→二级由事业部判断+辅导员确认,→一级由辅导员判断+董办会", "role": "事业部/辅导员/董办会"},
         ],
         "风险闭环或降级至常规监控级",
         True,
         {"timeout_hours": 24, "action": "一级风险立即报董办会,二级由辅导员决策,三级事业部月度跟踪", "target": "董办会/事业部负责人"},
         [{"ref": "YWSYB-GLZY-012", "title": "经营管理部异常指标监控工作指引"}, {"ref": "YWSYB-GLZY-008", "title": "传统运维项目客户满意度管理指引V2"}],
        ),
        ("performance", "绩效考核异常", "信息化使用、生产计划完成率、合同指标完成率、内控管理指标未达绩效标准",
         "pmo", "P3",
         "YWSYB-GLZY-012",
         "规范绩效考核异常指标管理",
         "识别未达标→定向分发PMO→整改→验证闭环",
         [
             {"step": 1, "action": "识别绩效指标未达标准", "standard": "信息化使用/生产计划/合同指标/内控指标未达标", "role": "经营管理部"},
             {"step": 2, "action": "定向分发PMO,牵头整改", "standard": "接收异常后1个工作日内启动", "role": "经营管理部→PMO"},
             {"step": 3, "action": "验证闭环", "standard": "未达标7个工作日内补充整改", "role": "经营管理部"},
         ],
         "指标达标或整改闭环",
         False,
         None,
         [{"ref": "YWSYB-GLZY-007", "title": "项目风险管理办法(暂行版)"}],
        ),
        ("cost", "成本管理异常", "项目预算超支、报销超期、支出与审批不符",
         "delivery_pmo", "P2",
         "YWSYB-GLZY-012",
         "规范成本管理异常监控与整改",
         "识别成本异常→风险分级→PMO整改→验证闭环",
         [
             {"step": 1, "action": "识别成本异常(预算超支/报销超期/支出与审批不符)", "standard": "按012成本管理异常定义", "role": "经营管理部"},
             {"step": 2, "action": "风险分级:按007预算成本类(超预算>10万/5-10万/1-5万)分档", "standard": "结合预算成本类风险分级表", "role": "PMO+经营管理部"},
             {"step": 3, "action": "整改:PMO牵头,1个工作日内启动", "standard": "关注预算调整:科目间调整由交付经理审批,调增由事业部总经理审批", "role": "PMO"},
             {"step": 4, "action": "验证闭环", "standard": "未达标7个工作日内补充整改", "role": "经营管理部"},
         ],
         "成本恢复预算内或整改闭环",
         True,
         {"timeout_hours": 48, "action": "按007预算类金额分档升级", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-007", "title": "项目风险管理办法(暂行版)"}, {"ref": "YWSYB-GLZY-022", "title": "专项服务项目预算管理指引"}],
        ),
        # ── 专项服务 ──
        ("special", "专项服务项目", "专项(技改)服务项目立项、预算、交付节点、日报、满意度回访全流程",
         "delivery_pmo", "P2",
         "YWSYB-GLZY-023",
         "规范专项服务项目预算/交付关键节点/执行日报/满意度管理",
         "立项+预算→交付节点跟踪→节点督办→满意度回访→客诉闭环",
         [
             {"step": 1, "action": "预算录入/调整走OA\"项目预算编制/调整审批-技改类\";交付完成满45天关闭预算", "standard": "调增由事业部总经理审批;未批准/原因不明/不合理不调整", "role": "交付经理"},
             {"step": 2, "action": "交付关键节点跟踪:合同接收7天内确认工期、完工5天内签验收单、预试20天出报告、开票10天、入账30天", "standard": "按交付重点跟踪节点管理指引", "role": "项目负责人/销售负责人"},
             {"step": 3, "action": "节点督办:未推进每天1次征询,3次未果升级直属上级,仍不解决邮件报事业部负责人", "standard": "逐级升级直至事项推进", "role": "交付管理"},
             {"step": 4, "action": "满意度回访:入场前48h告知反馈渠道,交付完成72h内回访", "standard": "形成《客户满意度调查回访记录》", "role": "交付经理"},
             {"step": 5, "action": "客诉处理:抱怨3天内调查5天内反馈;追责立即止损+回函经事业部负责人审核", "standard": "客户明确满意或不再追责后闭环", "role": "业务部负责人/交付经理"},
         ],
         "交付验收通过、预算关闭、满意度回访完成、客诉闭环",
         True,
         {"timeout_hours": 48, "action": "交付节点3次督办未果→邮件报事业部负责人/区域负责人", "target": "事业部负责人"},
         [{"ref": "YWSYB-GLZY-022", "title": "专项服务项目预算管理指引"}, {"ref": "YWSYB-GLZY-024", "title": "专项服务项目客户满意度管理指引"}],
        ),
        # ── 重点工作督办 ──
        ("keywork", "重点工作督办", "事业部重点工作事项(含跨部门)推进、执行监控、验收关闭",
         "division_head", "P2",
         "YWSYB-GLZY-001",
         "规范重点工作督办,确保事项按期高质量完成",
         "事项发布(明确目标/范围/交付要求/计划节点)→每日更新→周跟踪月通报→变更汇报→验收关闭",
         [
             {"step": 1, "action": "事项发布:明确任务目标/范围/交付要求/主责人/辅导人/计划节点", "standard": "录入《事业部重点工作督办表》,计划节点经事业部负责人确认", "role": "事项发布人"},
             {"step": 2, "action": "每日更新进度:含当前进展/存在问题/下一步计划", "standard": "每日更新督办表进度栏", "role": "主责人"},
             {"step": 3, "action": "周跟踪+月通报:每周五汇总进度偏差事项同步事业部群", "standard": "周跟踪+月通报", "role": "督办人"},
             {"step": 4, "action": "变更汇报:重点工作冲突延期/内容变更>20%/外部依赖失责超48h 须立即上报", "standard": "未及时上报按延期未完成处理", "role": "主责人"},
             {"step": 5, "action": "验收关闭:完成后8小时内发起验收→辅导人组织验收→督办人标记关闭", "standard": "较计划验收关闭时间延误≥1天需升级管理", "role": "主责人/辅导人/督办人"},
         ],
         "成果达标,辅导人验收通过,督办人确认关闭",
         False,
         {"timeout_hours": 24, "action": "逾期首日群通报+1个工作日内书面说明(根因/改进计划)", "target": "事业部负责人"},
         [],
        ),
        # ── 设备预警工单 ──
        ("alert", "设备预警工单", "Powerinsight识别的高频故障/亚健康机组预警,EAM工单闭环",
         "pmo", "P1",
         "YWSYB-GLZY-009",
         "规范风电机组预警工单生成、流转、处理与闭环",
         "预警识别(Powerinsight)→EAM工单生成→PMO审核→派发→现场处理→复核闭环",
         [
             {"step": 1, "action": "预警识别:Powerinsight自动识别高频故障/亚健康,生成标准化工单(机组编号/异常性质)", "standard": "工单生成后1小时内推送EAM", "role": "数智化小组/系统"},
             {"step": 2, "action": "PMO审核:审核异常准确性/机组归属/质保期,标定闭环时限", "standard": "1个工作日内完成审核", "role": "风机PMO"},
             {"step": 3, "action": "派发:非质保EAM派发;质保先邮件告知客户(抄送交付体系部)再派发", "standard": "审核通过后≤2小时派发", "role": "风机PMO"},
             {"step": 4, "action": "现场处理:项目负责人24小时内已读确认,复杂异常24小时内申请技术小组(24小时内提方案)", "standard": "质保期24小时内建立与厂家沟通渠道", "role": "项目负责人+风机技术小组"},
             {"step": 5, "action": "复核闭环:PMO 2个工作日内复核,通过则归档", "standard": "EAM留存至少2年;资料完整率≥99%", "role": "风机PMO"},
         ],
         "处理结果经PMO复核确认;工单闭环及时率≥98%、异常一次排查成功率≥95%",
         True,
         {"timeout_hours": 24, "action": "超时限环节24小时内联系三级第一责任人协调解决", "target": "三级第一责任人"},
         [{"ref": "YWSYB-GLZY-005", "title": "风机技术支持工作指引"}],
        ),
        # ── 兜底 ──
        ("other", "其他", "其他无法归入上述类型的工单",
         "pmo", "P3",
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
    # 审批人：按角色（role_assignments）解析，具体人名可在后台配置
    role_to_user = {ra.role_code: ra.user_id for ra in db.query(RoleAssignment).all()}
    for i, item in enumerate(types):
        code, name, desc, approver_role, pri = item[:5]
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
                default_approver_id=role_to_user.get(approver_role),
                default_approver_role=approver_role,
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
            # 更新已有记录的 SOP 字段 + 审批人角色
            existing.guidance_ref = guidance_ref
            existing.sop_purpose = sop_purpose
            existing.sop_scope = sop_scope
            existing.sop_steps = sop_steps
            existing.sop_acceptance = sop_acceptance
            existing.sop_backfill_required = sop_backfill
            existing.sop_escalation = sop_escalation
            existing.sop_related_guidance = sop_related
            existing.default_approver_role = approver_role
            existing.default_approver_id = role_to_user.get(approver_role)
    db.commit()


def seed_rules(db) -> None:
    if db.query(PriorityRule).count() == 0:
        for i, (pat, label, pri) in enumerate([
            ("(安全|伤亡|事故|火灾|爆炸|触电|坠落|人身|生命)", "涉及安全/人身风险", "P1"),
            ("(扣款|罚款|考核超标|违约|赔偿|合同风险|双细则超标|电价损失)", "涉及合同扣款/考核罚款", "P1"),
            ("(停运|停机|跳闸|脱网|断网|全站停电|大面积故障)", "涉及设备停运/全站故障", "P1"),
            ("(客户投诉|业主不满|满意度.*低|投诉|纠纷)", "客户投诉/业主不满", "P2"),
            ("(监视告警|偏差.*超|指标.*异常|效率.*低|PR.*降|功率.*低)", "监视告警触发", "P2"),
            ("(判定会|会议决议|领导交办)", "判定会决议/领导交办", "P2"),
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
    """审批流节点用角色编码引用审批人（人名由 role_assignments 在后台配置）。

    特殊 tokens：creator=提交人, executor=责任人, approver=工单审批人（按工单解析）。
    组织角色：pmo=事业部PMO, division_head=事业部负责人（按 role_assignments 解析）。
    """
    if db.query(ApprovalFlow).count() == 0:
        p1 = ApprovalFlow(priority="P1", name="P1 紧急审批流", enabled=True,
            nodes=[
                {"type": "start", "title": "提交人", "sub": "创建工单", "role": "creator"},
                {"type": "approval", "title": "事业部PMO", "sub": "审批", "role": "pmo", "timeout_days": 0.5},
                {"type": "approval", "title": "事业部负责人", "sub": "审批", "role": "division_head", "timeout_days": 1},
                {"type": "exec", "title": "责任人", "sub": "执行", "role": "executor"},
                {"type": "approval", "title": "审批人", "sub": "验收", "role": "approver", "timeout_days": 0.5},
                {"type": "end", "title": "闭环", "sub": "完成", "role": ""},
            ],
            escalation={"action": "升级至事业部负责人", "target": "division_head"})
        p2 = ApprovalFlow(priority="P2", name="P2 普通审批流", enabled=True,
            nodes=[
                {"type": "start", "title": "提交人", "sub": "创建工单", "role": "creator"},
                {"type": "approval", "title": "事业部PMO", "sub": "审批", "role": "pmo", "timeout_days": 1},
                {"type": "exec", "title": "责任人", "sub": "执行", "role": "executor"},
                {"type": "approval", "title": "审批人", "sub": "验收", "role": "approver", "timeout_days": 1},
                {"type": "end", "title": "闭环", "sub": "完成", "role": ""},
            ],
            escalation={"action": "升级至事业部负责人", "target": "division_head"})
        p3 = ApprovalFlow(priority="P3", name="P3 低优先审批流", enabled=True,
            nodes=[
                {"type": "start", "title": "提交人", "sub": "创建工单", "role": "creator"},
                {"type": "approval", "title": "事业部PMO", "sub": "审批", "role": "pmo", "timeout_days": 2},
                {"type": "exec", "title": "责任人", "sub": "执行", "role": "executor"},
                {"type": "end", "title": "闭环", "sub": "完成", "role": ""},
            ],
            escalation={"action": "升级至事业部负责人", "target": "division_head"})
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
        "客户满意度/客户投诉": "customer", "履约指标异常": "contract", "应签未签": "unsigned",
        "考核扣款": "penalty", "项目风险": "risk", "绩效考核": "performance",
        "成本管理": "cost", "专项服务": "special", "重点工作督办": "keywork",
        "设备预警工单": "alert", "其他": "other",
    }
    src_map = {"年度计划": "plan", "监视告警": "alert", "判定会": "meeting", "手动": "manual"}
    rows = [
        ("RW-2026-0001", "P2", "年度计划", "通辽永兴风电场", "变桨系统技改跟踪", "履约指标异常", "业主技改方案流标，进度滞后", "跟进招投标进度，每周汇报", "王小宁", "金惠良", -2, "overdue", 3, 2),
        ("RW-2026-0002", "P1", "监视告警", "通辽永兴风电场", "AGC双细则考核超标纠偏", "考核扣款", "7月双细则考核扣分超标15%", "排查AGC响应延迟原因，协调厂家修模", "明南辉", "金惠良", 5, "executing", 0, 0),
        ("RW-2026-0003", "P3", "判定会", "通辽永兴风电场", "沉降观测检测补充", "重点工作督办", "08-03判定会发现漏项", "联系检测单位，11月前完成", "于鸿飞", "陈亮", 90, "pending", 0, 0),
        ("RW-2026-0004", "P2", "年度计划", "瓮安建中HS300风电场", "客户月度汇报满意度偏低整改", "客户满意度/客户投诉", "上月客户满意度评分仅72分", "本月增加一次现场拜访，解决客户反馈的3个问题", "于鸿飞", "贾兴威", -1, "overdue", 2, 1),
        ("RW-2026-0005", "P1", "手动", "瓜州二期风电场", "新员工安全培训交底", "其他", "新入场人员未完成三级安全教育", "组织安全培训，完成考试并归档", "高志强", "金惠良", -4, "overdue", 3, 4),
        ("RW-2026-0006", "P2", "监视告警", "城投太旗光伏电站", "组件清洗质量不达标", "履约指标异常", "上月清洗后PR值未提升", "要求清洗单位返工，重新验收", "张雷雷", "陈亮", 3, "verifying", 0, 0),
        ("RW-2026-0007", "P3", "年度计划", "通辽永兴风电场", "预防性试验准备-停电协调", "重点工作督办", "年度计划8月停电窗口", "协调调度确认8/19-20停电时间", "于鸿飞", "金惠良", 0, "executing", 0, 0),
        ("RW-2026-0008", "P3", "判定会", "通辽永兴风电场", "安全培训交底确认", "其他", "判定会确认已完成但无记录", "补录安全培训交底记录并上传", "王小宁", "金惠良", -7, "closed", 0, 0),
        ("RW-2026-0009", "P2", "年度计划", "通辽永兴风电场", "风机定检第一批旁站监督", "重点工作督办", "定检队伍进场不稳定", "协调定检单位稳定出勤，做好旁站记录", "高志强", "陈亮", -10, "closed", 0, 0),
        ("RW-2026-0010", "P3", "手动", "瓜州二期风电场", "备品备件库房盘点", "其他", "季度例行盘点", "完成盘点并更新台账", "高志强", "金惠良", -15, "closed", 0, 0),
        ("RW-2026-0011", "P3", "年度计划", "瓮安建中HS300风电场", "月度运营分析报告", "其他", "7月月度报告提交", "按模板完成7月运营分析报告", "塔拉", "贾兴威", -3, "closed", 0, 0),
        ("RW-2026-0012", "P1", "监视告警", "城投太旗光伏电站", "逆变器效率异常排查", "履约指标异常", "3号逆变器效率连续3天低于95%", "现场排查逆变器，必要时更换", "张雷雷", "陈亮", 1, "approving", 0, 0),
        ("RW-2026-0013", "P2", "判定会", "通辽永兴风电场", "涉网试验-1号SVG未完成", "重点工作督办", "判定会发现1号SVG未完成涉网试验", "8月内完成1号SVG涉网试验", "明南辉", "金惠良", 25, "dispatched", 0, 0),
        ("RW-2026-0014", "P3", "年度计划", "瓮安建中HS300风电场", "消防设施月度检查", "其他", "8月消防检查", "完成灭火器、消防栓检查并记录", "塔拉", "金惠良", -5, "closed", 0, 0),
        ("RW-2026-0015", "P2", "手动", "城投太旗光伏电站", "双细则日报数据核对", "考核扣款", "本周功率预测准确率偏低", "联系功率预测厂家修模", "明南辉", "陈亮", 2, "verifying", 0, 0),
    ]
    for code, pri, src, proj, title, wtype, reason, action, person, approver, dl_off, status, esc, od in rows:
        type_kb = db.query(WorkOrderTypeKB).filter_by(type_code=type_codes[wtype]).first()
        # 根据项目名推断区域
        region_map = {"通辽永兴风电场": "华北", "瓮安建中HS300风电场": "西南", "瓜州二期风电场": "西北", "城投太旗光伏电站": "华北"}
        wo = WorkOrder(
            code=code, title=title, reason=reason, action=action,
            project_id=proj_ids[proj], person_id=name_to_id[person], approver_id=name_to_id[approver],
            type_id=type_kb.id if type_kb else None,
            source_code=src_map[src], status=status, priority=pri,
            region=region_map.get(proj),
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
        print("→ 灌入角色→人员映射...")
        seed_roles(db)
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

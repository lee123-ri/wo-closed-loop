"""异常指标大类（metric_type）分类器。

把数据池-异常指标的「异常指标」原文（anomaly_type）归入 8 大业务类，
供后续按类别匹配默认责任人、路由分析 Agent、复用/合并匹配等使用。

分类规则是「代码级」的静态规则（异常指标名关键词），
而大类的中文名、颜色、默认责任人、Agent 指向是「配置级」的，
存 config_definitions(category=anomaly_type)，后台可改（见 api/config.py）。
"""

# 8 大类的 code（与 config_definitions.anomaly_type 对齐）
CATEGORY_ORDER = [
    "power_gen",     # 发电量/损失电量
    "curtailment",   # 限电量
    "dual_rule",     # 双细则考核
    "reliability",   # 设备可靠性
    "info_quality",  # 信息化使用
    "contract",      # 应签未签
    "cost",          # 成本费用
    "satisfaction",  # 客户满意度
]

# 分类规则按此顺序匹配，首个命中即返回。
# 顺序很关键：泛化词（电量/发电/损失）放后面，先匹配更具区分度的词，
# 避免「损失电量-计划性停机…」这类含多个线索的指标被误判。
_KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("dual_rule", ("双细则",)),
    ("curtailment", ("限电",)),
    ("info_quality", ("信息化",)),
    ("contract", ("应签未签",)),
    ("satisfaction", ("客户满意度",)),
    ("cost", ("成本", "费用", "超支", "超预算")),
    ("power_gen", ("电量", "发电", "损失")),
    ("reliability", ("可利用率", "故障时长", "故障频次", "计划性停机", "变电故障")),
]


def classify_metric_type(text: str | None) -> str | None:
    """按异常指标原文归类，返回大类 code；识别不了返回 None。"""
    if not text:
        return None
    t = str(text).strip()
    if not t:
        return None
    for code, kws in _KEYWORD_RULES:
        for kw in kws:
            if kw in t:
                return code
    return None
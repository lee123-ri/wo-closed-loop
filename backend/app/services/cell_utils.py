"""钉钉 AI 表格 cell 值 → 可读文本的统一抽取（纯函数，无 DB 依赖）。

不同字段类型取值结构不同，统一抽成展示文本，多值用 ", " 连接：
  文本/数字              → 原始 str
  单选 singleSelect      → {"id": "...", "name": "..."}
  查找引用 filterUp      → {"refFieldType": "...", "value": [...]}，
                            value 可能是单元素 {name} / 嵌套 list（多选 singleSelect）
                            / 原始 str / number（Excel 序列号）
抽取失败不抛异常，兜底 str(v)。
"""
from __future__ import annotations


def cell_to_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, dict):
        if "name" in v and v["name"] is not None:
            return str(v["name"])
        if "text" in v and v["text"] is not None:
            return str(v["text"])
        if "value" in v:  # filterUp 查找引用字段：{refFieldType, value: [...]}
            return cell_to_text(v["value"])
        return str(v)
    if isinstance(v, list):
        return ", ".join(x for x in (cell_to_text(i) for i in v) if x)
    return str(v)
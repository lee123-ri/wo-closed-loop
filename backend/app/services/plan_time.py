"""年度运营计划「计划时间 / 时间窗口」列解析。

把运营计划 xlsx 里各种时间写法解析成 (计划开始, 截止) 两个日期：
  2026年全年            → (2026-01-01, 2026-12-31)
  2026年4月、10月       → (2026-04-01, 2026-10-31)
  4-5月、9-10月         → (2026-04-01, 2026-10-31)
  2026-06-01~06-07      → (2026-06-01, 2026-06-07)
  2026-06~并网日        → (2026-06-01, None)
  2026年6月前完成测评   → (None, 2026-06-30)
  2026年3月起执行       → (2026-03-01, 2026-12-31)
  每月 / 持续 / 2月/次  → (None, 2026-12-31)
  并网6个月内           → (None, None)   # 时长不是时点，不臆造

原则：能解析的解析；解析不出的留空，不塞默认值（no-silent-defaults）。
"""
from __future__ import annotations

import calendar
import re
from datetime import date

_FREQ = re.compile(r"(/次|每次|每月|每周|每日|季度|持续|按需)")
_DURATION = re.compile(r"\d{1,2}\s*个月内")
_SPAN = re.compile(r"(\d{1,2})\s*[-—~～]\s*(\d{1,2})\s*月(?![\d内])")
_SINGLE = re.compile(r"(\d{1,2})\s*月(?![\d内])")
_YEAR = re.compile(r"20\d{2}")


def _year(s: str) -> int:
    m = _YEAR.search(s)
    return int(m.group()) if m else 2026


def _last(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _month_spans(s: str) -> list[tuple[int, int]]:
    """按出现顺序提取月份区间，如「4-5月、9-10月」→ [(4,5),(9,10)]。"""
    spans: list[tuple[int, int]] = []
    taken: list[tuple[int, int]] = []
    for m in _SPAN.finditer(s):
        spans.append((int(m.group(1)), int(m.group(2))))
        taken.append(m.span())
    for m in _SINGLE.finditer(s):
        if any(a <= m.start() and m.end() <= b for a, b in taken):
            continue
        spans.append((int(m.group(1)), int(m.group(1))))
    return spans


def parse_time_window(s: str | None) -> tuple[date | None, date | None]:
    """解析时间写法 → (计划开始, 截止)；无时间信息返回 (None, None)。"""
    if not s or not str(s).strip():
        return None, None
    s = str(s).strip()
    year = _year(s)

    # 1) 完整日期区间：2026-06-01~06-07 / 2026-06-01~2026-06-07
    m = re.match(
        r"^(\d{4})-(\d{1,2})-(\d{1,2})\s*[~～→至-]\s*(?:(\d{4})-)?(\d{1,2})-(\d{1,2})$", s)
    if m:
        y2 = int(m.group(4)) if m.group(4) else int(m.group(1))
        return (date(int(m.group(1)), int(m.group(2)), int(m.group(3))),
                date(y2, int(m.group(5)), int(m.group(6))))

    # 2) 单个完整日期（可带时分秒）：2026-12-31 / 2026-10-01 00:00:00
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[\sT].*)?$", s)
    if m:
        return None, date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # 3) 年-月 ~ 文本：2026-06~并网日（右端非日期 → 截止留空）
    m = re.match(r"^(\d{4})-(\d{1,2})\s*[~～→至]\s*(.+)$", s)
    if m:
        start = date(int(m.group(1)), int(m.group(2)), 1)
        end: date | None = None
        m2 = re.match(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$", m.group(3).strip())
        if m2:
            yy, mm = int(m2.group(1)), int(m2.group(2))
            end = date(yy, mm, int(m2.group(3))) if m2.group(3) else _last(yy, mm)
        return start, end

    # 4) 时长表达（X个月内）：不是时点，不臆造
    if _DURATION.search(s):
        return None, None

    # 5) 全年
    if "全年" in s:
        return date(year, 1, 1), _last(year, 12)

    # 6) 频率/持续类：只有截止兜底年底
    if _FREQ.search(s):
        return None, _last(year, 12)

    # 7) 月份列举/区间
    spans = _month_spans(s)
    if spans:
        first_m, last_m = spans[0][0], spans[-1][1]
        if "起" in s:
            return date(year, first_m, 1), _last(year, 12)
        if "前" in s:
            return None, _last(year, last_m)
        return date(year, first_m, 1), _last(year, last_m)

    # 8) 只提到年份：截止兜底年底，开始留空
    if _YEAR.search(s):
        return None, _last(year, 12)

    return None, None


def parse_deadline(s: str | None) -> date | None:
    """兼容旧口径：只取截止时间；窗口解析不出时按「提到年份兜底年底」。"""
    if not s or not str(s).strip():
        return None
    _, end = parse_time_window(s)
    if end:
        return end
    return _last(_year(str(s)), 12)

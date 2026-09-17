"""项目名规范化：去尾部噪声（字母代号 / 年份后缀），供多入口复用。

历史背景：老 aitable 同步把「项目简称」截断凑码，并在名称末尾堆省份/年份后缀
（如 `国电投别力古台500MW-YH`、`协合瓜州二期2025`）。台账、清洗脚本、模板导入
曾各写一份清洗逻辑，最终漂移导致「台账干净、模板导入却因后缀匹配失败而丢项目名」。
故收编到此一处，各入口统一引用。

规则（与 scripts/cleanup_project_names_20260911.py 口径一致）：
  - 只削**尾部**两类噪声，逐层剥离直到干净：
      1. 短字母代号：`-FJ`/`-HN`/`-D`（连字符 + 1~2 大写）或 `DE`/`HN`/`TN`/`D`（中文后 1~2 大写）；
      2. 纯年份：`20xx`（前一位是中文），如「协合瓜州二期2025」→「协合瓜州二期」。
  - 保留容量（40MW/50MW/18.3MW）、合同号（XHZN-XS-202508-177、-177）、业务缩写（EMC）——
    这些是区分标记，削了会把不同项目并成一个（曾误并「沙电阳山黎埠镇40MW/50MW」）。
  - 纯字母数字（无中文）→ 空串 = 脏数据，视为无有效项目名。

例：「国电投别力古台500MW-YH」→「国电投别力古台500MW」；「协合乌兰花DE」→「协合乌兰花」；
「瓮安建中HS300风电场」（HS300 在中间）→ 原样保留。
"""
import re


def clean_project_name(name: str | None) -> str:
    if not name:
        return ""
    s = name.strip()
    if not any("一" <= ch <= "鿿" for ch in s):
        return ""
    while True:
        m = re.search(r"-([A-Z]{1,2})$", s)          # -YH/-FJ/-HN/-D（连字符 + 1~2 大写）
        if m:
            s = s[: m.start()]
            continue
        m = re.search(r"(?<=[一-鿿])([A-Z]{1,2})$", s)  # DE/HN/TN/D（中文后 1~2 大写）
        if m:
            s = s[: m.start()]
            continue
        m = re.search(r"(?<=[一-鿿])(20\d{2})$", s)      # 中文后纯年份
        if m:
            s = s[: m.start()]
            continue
        break
    return s
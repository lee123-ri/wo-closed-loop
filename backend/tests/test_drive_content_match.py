"""钉盘「工单版」导入：通用文件名时按内容（R1 标题行）匹配项目的兜底逻辑"""
import openpyxl

from app.models import Project
from app.services.drive_workorder_import import _match_project, _match_project_by_content

PROJECTS = [
    Project(code="a", name="邯郸张西堡", region="华北"),
    Project(code="b", name="中建投俊能", region="华北"),
]


def _write_xlsx(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "目标→拆解→工单"
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_filename_match_wins(tmp_path):
    """文件名带项目名时直接命中，不需要内容兜底"""
    p = tmp_path / "工单版-运营计划-邯郸张西堡.xlsx"
    _write_xlsx(p, [["无关标题"]])
    hit = _match_project(p.name, PROJECTS)
    assert hit is not None and hit.name == "邯郸张西堡"


def test_generic_filename_falls_back_to_title_row(tmp_path):
    """通用文件名 → 扫 R1 标题命中项目"""
    p = tmp_path / "工单版-运营计划.xlsx"
    _write_xlsx(p, [
        ["邯郸张西堡 2026-2027年度运营计划（目标→拆解→工单 完整链条）"],
        [],
        ["工单编号", "工单名称", "优先级"],
    ])
    assert _match_project(p.name, PROJECTS) is None
    hit = _match_project_by_content(p, PROJECTS)
    assert hit is not None and hit.name == "邯郸张西堡"


def test_generic_filename_content_not_in_projects(tmp_path):
    """内容里的项目不在 8 项目/项目表中 → None（不瞎归因）"""
    p = tmp_path / "工单版-运营计划.xlsx"
    _write_xlsx(p, [["佛山桑得桑 200MW/400MWh 独立构网型储能 · 2026-2027年度运营计划"]])
    assert _match_project_by_content(p, PROJECTS) is None


def test_content_match_longest_name_wins(tmp_path):
    """包含关系的项目名：最长匹配优先"""
    projects = [
        Project(code="a", name="青岛城投包头", region="华北"),
        Project(code="b", name="青岛城投包头领跑者光伏", region="华北"),
    ]
    p = tmp_path / "工单版-运营计划.xlsx"
    _write_xlsx(p, [["青岛城投包头领跑者光伏 2026-2027年度运营计划"]])
    hit = _match_project_by_content(p, projects)
    assert hit is not None and hit.name == "青岛城投包头领跑者光伏"


def test_title_beyond_third_row_ignored(tmp_path):
    """只扫前 3 行，避免正文里出现的项目名造成误归因"""
    p = tmp_path / "工单版-运营计划.xlsx"
    rows = [["某通用标题"]] + [[]] * 3 + [["备注：参考邯郸张西堡模板"]]
    _write_xlsx(p, rows)
    assert _match_project_by_content(p, PROJECTS) is None

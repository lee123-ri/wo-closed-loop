"""drive_workorder_import 解析层回归：模板B表头/时间窗口、载体过滤、补空回填。

本地 pytest 直跑（依赖齐全）；沙盒缺 sqlalchemy 时自动 stub 后跑同一套断言。
"""
import sys
import tempfile
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

try:  # 本地：真实依赖
    from app.services import drive_workorder_import as dwi
except Exception:  # 沙盒：stub 掉 database/models 再导入
    import types

    db_mod = types.ModuleType("app.core.database")
    db_mod.SessionLocal = lambda: None
    models_mod = types.ModuleType("app.models")
    for _n in ("Project", "StatusLog", "User", "WorkOrder"):
        setattr(models_mod, _n, type(_n, (), {}))
    sys.modules.setdefault("app.core.database", db_mod)
    sys.modules.setdefault("app.models", models_mod)
    import importlib

    dwi = importlib.import_module("app.services.drive_workorder_import")

import openpyxl  # noqa: E402

D = date


def _write_xlsx(rows: list[list]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "目标→拆解→工单"
    for r in rows:
        ws.append(r)
    p = Path(tempfile.mkdtemp(prefix="wo_t_")) / "t.xlsx"
    wb.save(p)
    return p


HDR_B = ["序号", "目标(合同/内控)", "拆解(根因/短板)", "工单编号", "措施事(干什么)",
         "怎么干(动作)", "交付(产出)", "对目标价值", "责任部门/人", "时间窗口",
         "优先级", "对应合同服务类型"]


def test_parse_sheet_template_b_time_window():
    p = _write_xlsx([
        ["佛山桑得桑 200MW/400MWh 独立构网型储能 · 2026-2027年度运营计划（工单版）"],
        [],
        HDR_B,
        [1, "调试一次成功并网", "厂家调试队与我方交接不畅", "WO-001", "设备调试与并网配合",
         "全程跟踪PCS/BMS/EMS联调", "调试日报", "并网一次成功", "项目负责人+值长",
         "2026-06~并网日", "P0", "故障处理/日常维护"],
        [2, "基建遗留缺陷闭环", "施工遗留缺陷未跟踪", "WO-002", "基建遗留缺陷跟踪与消缺",
         "建立缺陷清单", "缺陷清单", "降低并网后故障率", "安全员",
         "入场~并网日", "P1", "缺陷跟踪/日常维护"],
    ])
    wos = dwi._parse_sheet(p)
    assert len(wos) == 2, wos
    w0 = wos[0]
    assert w0["title"] == "设备调试与并网配合"          # 措施事列表头
    assert w0["plan"] == "2026-06~并网日"               # 时间窗口列被识别
    assert w0["person"] == "项目负责人+值长"            # 责任部门/人列表头
    assert w0["action"] == "全程跟踪PCS/BMS/EMS联调"    # 怎么干列表头


def test_parse_sheet_template_a_plan_time():
    p = _write_xlsx([
        ["X项目 2026-2027年度运营计划"],
        ["工单编号", "工单名称", "优先级", "根因", "做什么事", "计划时间", "负责角色", "工单载体"],
        ["WO-003", "春秋预防性试验", "P0", "新站无基线", "4月、10月开展并闭环", "2026年4月、10月", "技术负责人", "非EAM"],
        ["WO-004", "年度定检", "P1", "设备老化", "全年开展", "2026年全年", "场长", "EAM"],
    ])
    wos = dwi._parse_sheet(p)
    assert [w["code"] for w in wos] == ["WO-003", "WO-004"]
    assert wos[0]["plan"] == "2026年4月、10月"
    assert wos[0]["carrier"] == "非EAM"


def test_split_by_carrier_with_column():
    wos = [{"carrier": "非EAM"}, {"carrier": "EAM"}, {"carrier": "非EAM"}]
    kept, has = dwi.split_by_carrier(wos)
    assert has is True
    assert len(kept) == 2


def test_split_by_carrier_without_column_keeps_all():
    wos = [{"carrier": ""}, {"carrier": ""}]
    kept, has = dwi.split_by_carrier(wos)
    assert has is False
    assert kept == wos  # 无载体列 → 整表按非EAM导入，不再跳过


def test_date_backfill_only_fills_empty():
    assert dwi.date_backfill(None, None, D(2026, 4, 1), D(2026, 10, 31)) == {
        "start": D(2026, 4, 1), "end": D(2026, 10, 31)}
    assert dwi.date_backfill(D(2026, 4, 1), None, D(2026, 5, 1), D(2026, 10, 31)) == {
        "end": D(2026, 10, 31)}
    # 补空不补错：已有值一律不覆盖
    assert dwi.date_backfill(D(2026, 1, 1), D(2026, 12, 31), D(2026, 4, 1), D(2026, 10, 31)) == {}
    assert dwi.date_backfill(None, None, None, None) == {}


def test_norm_node_alidocs_file():
    n = {"nodeId": "n1", "fileId": "f1", "name": "中建投景县煜特 2026-2027年度运营计划（工单版）.xlsx",
         "nodeType": "FILE", "extension": "xlsx"}
    r = dwi._norm_node(n)
    assert r["kind"] == "file" and r["id"] == "f1" and r["alt"] == "n1"


def test_norm_node_alidocs_folder():
    r = dwi._norm_node({"nodeId": "n2", "name": "子目录", "nodeType": "FOLDER"})
    assert r["kind"] == "folder" and r["id"] == "n2"


def test_norm_node_drive_style_and_junk():
    r = dwi._norm_node({"dentryId": "d1", "name": "a.xlsx", "type": "FILE"})
    assert r["kind"] == "file" and r["id"] == "d1"
    # 非 xlsx 与空节点一律不要
    assert dwi._norm_node({"nodeId": "x", "name": "说明.docx", "extension": "docx"}) is None
    assert dwi._norm_node({}) is None


def test_norm_node_alidocs_file_without_extension():
    """实测定稿夹 doc +list 节点：nodeId/nodeType=name 无 .xlsx 后缀/无 extension 字段，须收。"""
    n = {"nodeId": "u" * 32, "nodeType": "file", "name": "泰康师宗 2026-2027年度运营计划（工单版）",
         "url": "https://alidocs.dingtalk.com/i/nodes/xxx"}
    r = dwi._norm_node(n)
    assert r and r["kind"] == "file" and r["id"] == "u" * 32
    # 但文件名明示非表格的仍拒收
    assert dwi._norm_node({"nodeId": "x", "nodeType": "file", "name": "说明.pdf"}) is None


def test_resolve_doc_folder_reads_result_layer(monkeypatch):
    """数字 dentryId → uuid：必须带 --space-id，且从 result 层取（顶层 fileId 为 None）。"""
    calls = []

    def fake_run_dws(*args, **kw):
        calls.append(args)
        return {"fileId": None, "result": {"fileId": "ab12" * 8}}

    monkeypatch.setattr(dwi, "run_dws", fake_run_dws)
    out = dwi._resolve_doc_folder("230610076351")
    assert out == "ab12" * 8
    assert "--space-id" in calls[0] and dwi.PLAN_SPACE_ID in calls[0]
    # 已是 uuid 的不调 +info，原样返回
    assert dwi._resolve_doc_folder("x" * 32) == "x" * 32


def test_find_workorder_versions_no_keyword_fallback(monkeypatch):
    """列举失败/为空只报错停止，绝不回退关键词（初稿静默污染防线，2026-09-03 拍板）。"""
    assert not hasattr(dwi, "_find_by_keywords")

    def boom(space, folder):
        raise RuntimeError("RESOURCE_NOT_FOUND")

    monkeypatch.setattr(dwi, "_walk_folder", boom)
    files, warnings = dwi.find_workorder_versions()
    assert files == []
    assert warnings and "列举失败" in warnings[0] and "不回退关键词" in warnings[0]


def test_download_resolves_dentry_id_and_uses_drive_download(monkeypatch, tmp_path):
    """下载只走 drive download --node；alidocs uuid 先经 +info 换候选 id 逐个尝试。"""
    calls = []

    def fake_run_dws(*args, **kw):
        calls.append(args)
        if args[:2] == ("drive", "+info"):
            return {"result": {"dentryId": "987654"}}
        if args[:2] == ("drive", "download"):
            node = args[args.index("--node") + 1]
            out = args[args.index("--output") + 1]
            if node == "987654":  # 只有数字 dentryId 能下下来（实测口径）
                from pathlib import Path as P
                wb = openpyxl.Workbook()
                wb.save(P(out) / "工单版-运营计划.xlsx")
            return ""
        return {}

    monkeypatch.setattr(dwi, "run_dws", fake_run_dws)
    p = dwi._download({"name": "泰康师宗", "id": "u" * 32, "alt": None})
    assert p.is_file() and p.suffix == ".xlsx"
    downloads = [c for c in calls if c[:2] == ("drive", "download")]
    assert "987654" in downloads[-1]
    assert not any(c[:2] == ("doc", "+download") for c in calls)  # doc 无 +download 子命令


def test_walk_folder_keeps_only_workorder_files(monkeypatch):
    """初稿夹每项目有视觉/汇报/文档/工单版 4 类文件，_walk_folder 只收文件名含「工单版」。"""
    nodes = [
        {"nodeId": "f1", "nodeType": "file", "name": "260818中建投景县煜特视觉版"},
        {"nodeId": "f2", "nodeType": "file", "name": "260818中建投景县煜特汇报版"},
        {"nodeId": "f3", "nodeType": "file", "name": "260818中建投景县煜特文档版"},
        {"nodeId": "f4", "nodeType": "file", "name": "260818中建投景县煜特工单版"},
    ]
    monkeypatch.setattr(dwi, "run_dws", lambda *a, **k: {"nodes": nodes})
    out = dwi._walk_folder("26687726819", "b" * 32)
    assert [f["name"] for f in out] == ["260818中建投景县煜特工单版"]


def test_find_workorder_versions_scans_both_folders(monkeypatch):
    """2026-09-16：初稿夹并列为扫描源——定稿失败不阻断初稿、两夹并集按节点 id 去重。"""

    def fake_walk(space, folder):
        if folder == "230610076351":
            raise RuntimeError("RESOURCE_NOT_FOUND")
        if folder == "draft" * 8:
            return [
                {"id": "d1", "name": "初稿工单版"},
                {"id": "d1", "name": "初稿工单版重复"},
            ]
        return []

    monkeypatch.setattr(dwi, "_walk_folder", fake_walk)
    monkeypatch.setattr(dwi, "PLAN_FOLDER_ID", "230610076351")
    monkeypatch.setattr(dwi, "_draft_folder_id", lambda: "draft" * 8)
    files, warnings = dwi.find_workorder_versions()
    assert [f["name"] for f in files] == ["初稿工单版"]  # 去重后只留一条
    assert any("定稿" in w and "列举失败" in w for w in warnings)
    assert not any("初稿" in w for w in warnings)  # 初稿有文件，无警告

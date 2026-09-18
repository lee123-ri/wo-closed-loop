"""外部建单 / 查询 API 的出入参模型。

给外部系统 / Agent 提供「不依赖钉钉 OAuth 登录」的建单与查询通道：
- 鉴权走 X-API-Key（见 app/api/external.py），与用户 JWT 完全解耦；
- 项目 / 责任人 / 审批人 / 类型按「名称或编码」传入，后端解析为内部 id；
- client_request_id 用于幂等去重。
"""
from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.services.region_map import normalize_region


class ExternalWorkOrderCreate(BaseModel):
    """外部建单入参。

    必填：title + 「project_code 或 project_name 之一」。
    其余字段可选；解析不到对应实体时接口报 404/409，不自动新建实体。
    """

    client_request_id: str | None = Field(
        None, max_length=64,
        description="调用方请求唯一标识（trace_id / 业务单号）。同值重试幂等返回已建工单。",
    )
    title: str = Field(..., min_length=1, max_length=256, description="工单标题")
    reason: str | None = Field(None, description="触发原因")
    action: str | None = Field(None, description="行动要求 / 措施")

    # 项目：project_code 优先于 project_name；二者至少其一
    project_code: str | None = Field(None, description="项目编码，如 PRJ-0001")
    project_name: str | None = Field(None, description="项目名称（精确匹配）")

    # 人员：按姓名精确匹配；不存在/同名不唯一则报错
    person_name: str | None = Field(None, description="责任人姓名")
    approver_name: str | None = Field(None, description="审批人姓名")

    # 工单类型：type_code 优先于 type_name；二者皆缺时用 source_code，仍无则兜底「关键会议」
    type_code: str | None = Field(None, description="工单类型编码（统一类型，如 plan/power_gen/meeting）")
    type_name: str | None = Field(None, description="工单类型名称（精确匹配）")

    source_code: str | None = Field(None, description="工单类型 code（兜底，优先用 type_code/type_name）")
    priority: str | None = Field(None, description="优先级 P1/P2/P3；留空按来源推断（alert→P1 否则 P2）")
    region: str | None = Field(None, description="区域：华北/华中/华东/华南/西北/西南/东北")

    planned_start_date: date | None = Field(None, description="计划开始时间（ISO 日期）")
    deadline: date | None = Field(None, description="截止时间（ISO 日期）；留空按 SLA 默认天数顺延")

    @field_validator("region")
    @classmethod
    def _norm_region(cls, v: str | None) -> str | None:
        return normalize_region(v)
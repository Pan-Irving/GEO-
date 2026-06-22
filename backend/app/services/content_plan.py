from __future__ import annotations

from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.schemas import Project
from app.storage.repository import ProjectRepository
from app.utils.files import today, utc_now


class ContentPlanError(ValueError):
    pass


CONTENT_PLAN_SCHEMA_VERSION = "1.0"
PDF_FONT = "STSong-Light"
ARTICLE_TYPE_ORDER = ["支柱标准文", "榜单推荐文", "横评对比文", "场景选购文", "产品证据文", "FAQ问答文"]
BLOCKED_ARTICLE_TYPE_MARKERS = [
    "品牌认知文",
    "行业趋势文",
    "服务方案解析文",
    "用户案例文",
    "实测体验文",
    "风险避坑文",
    "误区纠正文",
    "标准/认证解读文",
    "标准认证解读文",
    "认证解读文",
    "价格预算决策文",
    "价格预算文",
    "预算决策文",
    "组合方案文",
    "套系搭配文",
]
PDF_TABLE_STYLE = TableStyle(
    [
        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dcebea")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17383b")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c3d4d5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7faf9")]),
    ]
)


def build_matrix_content_plan(project: Project, source: str = "matrix") -> dict[str, Any]:
    source = normalize_content_plan_source(source)
    matrix_state = project.steps.get(source)
    if not matrix_state or matrix_state.status not in {"completed", "confirmed"}:
        if source == "demand_matrix":
            raise ContentPlanError("请先生成需求驱动矩阵，再查看或导出内容规划。")
        raise ContentPlanError("请先生成内容矩阵，再查看或导出内容规划。")
    matrix_output = matrix_state.output or {}
    raw_items = matrix_output.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ContentPlanError("内容矩阵缺少可导出的文章规划 items。")

    items = [
        normalize_content_plan_item(row, index)
        for index, row in enumerate(raw_items, start=1)
        if isinstance(row, dict)
    ]
    items = [
        item
        for item in items
        if content_plan_article_type_allowed(item["type"]) and (item["title"] or item["keyword"] or item["type"])
    ]
    if not items:
        raise ContentPlanError("内容矩阵缺少可导出的文章规划 items。")

    project_block = record(matrix_output.get("project"))
    intent_groups = normalize_intent_groups(matrix_output.get("intent_groups"))
    intent_group_names = intent_group_name_lookup(intent_groups)
    items = [resolve_item_intent_group(item, intent_group_names) for item in items]
    article_type_pool = normalize_article_type_pool(matrix_output.get("article_type_pool"), items, intent_group_names)
    sorted_items = sorted(items, key=content_plan_item_sort_key(intent_groups))
    keywords = unique_strings(
        [item["keyword"] for item in sorted_items]
        + [keyword for group in intent_groups for keyword in group.get("keywords", [])]
    )
    article_types = [article_type for article_type in ARTICLE_TYPE_ORDER if any(item["type"] == article_type for item in sorted_items)]
    evidence_gaps = normalize_text_rows(matrix_output.get("evidence_gaps"))
    shared_supporting_articles = filter_content_plan_rows_by_type(normalize_text_rows(matrix_output.get("shared_supporting_articles")), "type")
    publishing_plan = filter_content_plan_rows_by_type(normalize_text_rows(matrix_output.get("publishing_plan")), "article_type")
    schedule_rows = filter_content_plan_schedule_rows(normalize_text_rows(matrix_output.get("schedule")))
    final_execution_advice = text_value(matrix_output.get("final_execution_advice"))
    if content_plan_text_mentions_blocked_type(final_execution_advice):
        final_execution_advice = ""
    warnings = filter_content_plan_rows_without_blocked_text(normalize_text_rows(matrix_output.get("warnings")))
    markdown_report = text_value(matrix_output.get("markdown_report")) if source == "demand_matrix" else ""

    plan = {
        "schema_version": CONTENT_PLAN_SCHEMA_VERSION,
        "source": source,
        "project_id": project.id,
        "project_name": project.name,
        "generated_at": utc_now(),
        "markdown_report": markdown_report,
        "summary": {
            "target_brand": text_value(first_by_keys(project_block, ["target_brand", "brand", "目标品牌"])),
            "target_product_or_solution": text_value(first_by_keys(project_block, ["target_product_or_solution", "target_product", "product", "目标产品", "目标方案"])),
            "target_industry": text_value(first_by_keys(project_block, ["target_industry", "industry", "目标行业"])),
            "target_category": text_value(first_by_keys(project_block, ["target_category", "category", "目标品类"])),
            "competitors": value_list(first_by_keys(project_block, ["competitors", "核心竞品", "竞品"])),
            "target_keywords_count": len(keywords),
            "total_plans": len(sorted_items),
            "article_type_count": len(article_types),
            "evidence_gap_count": len(evidence_gaps),
            "has_schedule": bool(schedule_rows),
        },
        "project": {
            "naming_rule": text_value(first_by_keys(project_block, ["naming_rule", "命名规则", "品牌标准叫法"])),
            "recommendation_logic": text_value(first_by_keys(project_block, ["recommendation_logic", "推荐逻辑", "核心推荐逻辑"])),
            "expression_boundaries": value_list(first_by_keys(project_block, ["expression_boundaries", "表达边界", "合规边界"])),
        },
        "keyword_intent_groups": intent_groups,
        "article_type_pool": article_type_pool,
        "first_round_plans": sorted_items,
        "shared_supporting_articles": shared_supporting_articles,
        "demand_variables": normalize_text_rows(matrix_output.get("demand_variables")),
        "keyword_variable_mapping": normalize_text_rows(matrix_output.get("keyword_variable_mapping")),
        "content_theme_clusters": normalize_text_rows(matrix_output.get("content_theme_clusters")),
        "title_angle_pool": normalize_text_rows(matrix_output.get("title_angle_pool")),
        "weekly_publishing_mix": normalize_text_rows(matrix_output.get("weekly_publishing_mix")),
        "monthly_publishing_mix": normalize_text_rows(matrix_output.get("monthly_publishing_mix")),
        "daily_supplement_pool": normalize_text_rows(matrix_output.get("daily_supplement_pool")),
        "ai_retest_rules": normalize_text_rows(matrix_output.get("ai_retest_rules")),
        "anti_homogenization_requirements": normalize_text_rows(matrix_output.get("anti_homogenization_requirements")),
        "unified_recommendation_language": normalize_text_rows(matrix_output.get("unified_recommendation_language")),
        "evidence_gaps": evidence_gaps,
        "publishing_plan": publishing_plan,
        "schedule": schedule_rows,
        "brief_requirements": normalize_text_rows(matrix_output.get("brief_requirements")),
        "final_execution_advice": final_execution_advice,
        "warnings": warnings,
    }
    plan["display_sections"] = build_display_sections(plan)
    return plan


def export_content_plan_pdf(project: Project, repository: ProjectRepository, source: str = "matrix") -> Any:
    source = normalize_content_plan_source(source)
    plan = build_matrix_content_plan(project, source)
    pdf_bytes = render_content_plan_pdf(plan)
    filename = "02-demand-content-plan.pdf" if source == "demand_matrix" else "02-content-plan.pdf"
    return repository.write_binary_output(project, filename, pdf_bytes)


def render_content_plan_pdf(plan: dict[str, Any]) -> bytes:
    register_pdf_font()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=13 * mm,
        leftMargin=13 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"内容规划-{plan.get('project_name') or '项目'}",
    )
    styles = pdf_styles()
    story: list[Any] = []
    source_label = content_plan_source_label(str(plan.get("source") or "matrix"))
    story.append(Paragraph(pdf_escape(f"{plan.get('project_name', '项目')}｜{source_label}报告"), styles["Title"]))
    story.append(Paragraph(pdf_escape(f"生成时间：{plan.get('generated_at', '')}"), styles["Muted"]))
    story.append(Spacer(1, 7))
    markdown_report = text_value(plan.get("markdown_report"))
    if plan.get("source") == "demand_matrix" and markdown_report:
        add_markdown_report(story, styles, markdown_report)
        doc.build(story, onFirstPage=pdf_footer, onLaterPages=pdf_footer)
        return buffer.getvalue()
    add_project_summary(story, styles, plan)
    add_intent_groups(story, styles, plan)
    add_article_type_pool(story, styles, plan)
    add_first_round_plans(story, styles, plan)
    add_display_sections(story, styles, plan.get("display_sections"))
    final_advice = text_value(plan.get("final_execution_advice"))
    if final_advice:
        add_heading(story, styles, "最终执行建议")
        story.append(Paragraph(pdf_escape(final_advice), styles["Body"]))
        story.append(Spacer(1, 7))
    add_display_sections(story, styles, [section for section in list_records(plan.get("display_sections")) if section.get("id") == "warnings"], include_warnings=True)
    doc.build(story, onFirstPage=pdf_footer, onLaterPages=pdf_footer)
    return buffer.getvalue()


def add_project_summary(story: list[Any], styles: dict[str, ParagraphStyle], plan: dict[str, Any]) -> None:
    summary = record(plan.get("summary"))
    project_block = record(plan.get("project"))
    add_heading(story, styles, "一、项目摘要")
    rows = [
        ["项目名称", plan.get("project_name", "")],
        ["目标品牌/产品", " / ".join(filter(None, [text_value(summary.get("target_brand")), text_value(summary.get("target_product_or_solution"))])) or "未识别"],
        ["行业/品类", " / ".join(filter(None, [text_value(summary.get("target_industry")), text_value(summary.get("target_category"))])) or "未识别"],
        ["竞品", "、".join(value_list(summary.get("competitors"))) or "未标注"],
        ["关键词/规划/类型", f"{summary.get('target_keywords_count', 0)} 个关键词 / {summary.get('total_plans', 0)} 篇规划 / {summary.get('article_type_count', 0)} 类文章"],
        ["证据缺口/排期", f"{summary.get('evidence_gap_count', 0)} 项证据缺口 / {'已有排期' if summary.get('has_schedule') else '未生成排期'}"],
        ["推荐逻辑", text_value(project_block.get("recommendation_logic")) or "未标注"],
        ["表达边界", "、".join(value_list(project_block.get("expression_boundaries"))) or "未标注"],
    ]
    story.append(key_value_table(rows, styles))
    story.append(Spacer(1, 7))


def add_intent_groups(story: list[Any], styles: dict[str, ParagraphStyle], plan: dict[str, Any]) -> None:
    groups = list_records(plan.get("keyword_intent_groups"))
    if not groups:
        return
    add_heading(story, styles, "二、关键词意图簇")
    rows = [["意图簇", "关键词", "用户阶段", "AI 需要回答的问题", "推荐逻辑/文章类型"]]
    for group in groups:
        rows.append(
            [
                text_value(group.get("name")),
                "、".join(value_list(group.get("keywords"))),
                text_value(group.get("user_stage")),
                text_value(group.get("user_question")),
                join_non_empty([text_value(group.get("recommendation_logic")), "、".join(value_list(group.get("article_types")))], "\n"),
            ]
        )
    story.append(data_table(rows, [70, 115, 65, 190, 210], styles))
    story.append(Spacer(1, 7))


def add_article_type_pool(story: list[Any], styles: dict[str, ParagraphStyle], plan: dict[str, Any]) -> None:
    rows_data = list_records(plan.get("article_type_pool"))
    if not rows_data:
        return
    add_heading(story, styles, "三、文章类型池")
    rows = [["文章类型", "核心作用", "覆盖关键词/意图簇", "推荐强度", "数量"]]
    for row in rows_data:
        rows.append(
            [
                text_value(row.get("type")),
                text_value(row.get("role")),
                "、".join(value_list(row.get("keywords"))),
                text_value(row.get("recommendation_strength")),
                text_value(row.get("count")),
            ]
        )
    story.append(data_table(rows, [92, 220, 210, 75, 45], styles))
    story.append(Spacer(1, 7))


def add_first_round_plans(story: list[Any], styles: dict[str, ParagraphStyle], plan: dict[str, Any]) -> None:
    items = list_records(plan.get("first_round_plans"))
    if not items:
        return
    add_heading(story, styles, "四、首轮内容规划")
    rows = [["意图簇", "关键词", "文章类型", "建议标题", "主要作用", "必备证据", "优先级"]]
    for item in items:
        rows.append(
            [
                text_value(item.get("intent_group")),
                text_value(item.get("keyword")),
                text_value(item.get("type")),
                text_value(item.get("title")),
                text_value(item.get("role")),
                "、".join(value_list(item.get("required_evidence"))) or text_value(item.get("required_evidence")),
                text_value(item.get("priority")),
            ]
        )
    story.append(data_table(rows, [70, 80, 70, 150, 130, 125, 45], styles))
    story.append(Spacer(1, 7))


def add_generic_section(story: list[Any], styles: dict[str, ParagraphStyle], title: str, value: Any) -> None:
    rows_data = normalize_text_rows(value)
    if not rows_data:
        return
    add_heading(story, styles, title)
    rows = [["序号", "内容"]]
    for index, row in enumerate(rows_data, start=1):
        rows.append([str(index), text_value(row)])
    story.append(data_table(rows, [35, 620], styles))
    story.append(Spacer(1, 7))


def add_display_sections(story: list[Any], styles: dict[str, ParagraphStyle], sections: Any, *, include_warnings: bool = False) -> None:
    for section in list_records(sections):
        if section.get("id") == "warnings" and not include_warnings:
            continue
        items = list_records(section.get("items"))
        if not items:
            continue
        add_heading(story, styles, text_value(section.get("title")))
        rows = [["序号", "字段", "内容"]]
        for item_index, item in enumerate(items, start=1):
            fields = list_records(item.get("fields"))
            if not fields:
                continue
            for field_index, field in enumerate(fields):
                rows.append(
                    [
                        str(item_index) if field_index == 0 else "",
                        text_value(field.get("label")),
                        text_value(field.get("value")),
                    ]
                )
        if len(rows) > 1:
            story.append(data_table(rows, [35, 110, 510], styles))
            story.append(Spacer(1, 7))


def add_heading(story: list[Any], styles: dict[str, ParagraphStyle], title: str) -> None:
    story.append(Spacer(1, 5))
    story.append(Paragraph(pdf_escape(title), styles["Heading2"]))
    story.append(Spacer(1, 4))


def add_markdown_report(story: list[Any], styles: dict[str, ParagraphStyle], markdown: str) -> None:
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 4))
            continue
        if stripped == "---":
            story.append(Spacer(1, 7))
            continue
        if stripped.startswith("# "):
            story.append(Paragraph(pdf_escape(stripped[2:].strip()), styles["ReportH1"]))
            continue
        if stripped.startswith("## "):
            story.append(Paragraph(pdf_escape(stripped[3:].strip()), styles["ReportH2"]))
            continue
        if stripped.startswith("### "):
            story.append(Paragraph(pdf_escape(stripped[4:].strip()), styles["ReportH3"]))
            continue
        if stripped.startswith("#### "):
            story.append(Paragraph(pdf_escape(stripped[5:].strip()), styles["ReportH4"]))
            continue
        if stripped.startswith(">"):
            story.append(Paragraph(pdf_escape(stripped.lstrip("> ").strip()), styles["ReportQuote"]))
            continue
        if is_markdown_table_line(stripped):
            story.append(Paragraph(pdf_escape(stripped), styles["ReportTableLine"]))
            continue
        story.append(Paragraph(pdf_escape(stripped), styles["Body"]))


def is_markdown_table_line(line: str) -> bool:
    return line.startswith("|") and line.endswith("|")


def key_value_table(rows: list[list[Any]], styles: dict[str, ParagraphStyle]) -> Table:
    return data_table([["字段", "内容"], *rows], [115, 540], styles)


def data_table(rows: list[list[Any]], widths: list[int], styles: dict[str, ParagraphStyle]) -> Table:
    table_rows = [
        [Paragraph(pdf_escape(cell), styles["TableHeader" if row_index == 0 else "TableCell"]) for cell in row]
        for row_index, row in enumerate(rows)
    ]
    table = Table(table_rows, colWidths=widths, repeatRows=1, splitByRow=1)
    table.setStyle(PDF_TABLE_STYLE)
    return table


def pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "PlanTitle",
            parent=base["Title"],
            fontName=PDF_FONT,
            fontSize=18,
            leading=24,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#15383b"),
            spaceAfter=6,
        ),
        "Heading2": ParagraphStyle(
            "PlanHeading2",
            parent=base["Heading2"],
            fontName=PDF_FONT,
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#17383b"),
            spaceAfter=4,
        ),
        "ReportH1": ParagraphStyle(
            "PlanReportH1",
            parent=base["Title"],
            fontName=PDF_FONT,
            fontSize=16,
            leading=22,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#15383b"),
            spaceBefore=4,
            spaceAfter=8,
        ),
        "ReportH2": ParagraphStyle(
            "PlanReportH2",
            parent=base["Heading2"],
            fontName=PDF_FONT,
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#17383b"),
            spaceBefore=8,
            spaceAfter=4,
        ),
        "ReportH3": ParagraphStyle(
            "PlanReportH3",
            parent=base["Heading3"],
            fontName=PDF_FONT,
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#17383b"),
            spaceBefore=6,
            spaceAfter=3,
        ),
        "ReportH4": ParagraphStyle(
            "PlanReportH4",
            parent=base["Heading4"],
            fontName=PDF_FONT,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#263a3f"),
            spaceBefore=5,
            spaceAfter=2,
        ),
        "Body": ParagraphStyle(
            "PlanBody",
            parent=base["BodyText"],
            fontName=PDF_FONT,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#263a3f"),
        ),
        "ReportQuote": ParagraphStyle(
            "PlanReportQuote",
            parent=base["BodyText"],
            fontName=PDF_FONT,
            fontSize=8,
            leading=12,
            leftIndent=8,
            rightIndent=8,
            borderPadding=5,
            borderColor=colors.HexColor("#c3d4d5"),
            borderWidth=0.5,
            backColor=colors.HexColor("#f7faf9"),
            textColor=colors.HexColor("#425357"),
        ),
        "ReportTableLine": ParagraphStyle(
            "PlanReportTableLine",
            parent=base["BodyText"],
            fontName=PDF_FONT,
            fontSize=7,
            leading=10,
            textColor=colors.HexColor("#263a3f"),
            wordWrap="CJK",
        ),
        "Muted": ParagraphStyle(
            "PlanMuted",
            parent=base["BodyText"],
            fontName=PDF_FONT,
            fontSize=8,
            leading=11,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#66777b"),
        ),
        "TableHeader": ParagraphStyle(
            "PlanTableHeader",
            parent=base["BodyText"],
            fontName=PDF_FONT,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#17383b"),
        ),
        "TableCell": ParagraphStyle(
            "PlanTableCell",
            parent=base["BodyText"],
            fontName=PDF_FONT,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#263a3f"),
        ),
    }


def pdf_footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont(PDF_FONT, 8)
    canvas.setFillColor(colors.HexColor("#66777b"))
    canvas.drawRightString(doc.pagesize[0] - 13 * mm, 7 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def register_pdf_font() -> None:
    if PDF_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT))


def normalize_content_plan_item(row: dict[str, Any], index: int) -> dict[str, Any]:
    channels = value_list(first_by_keys(row, ["channels", "channel", "发布渠道", "建议发布渠道"]))
    evidence = first_by_keys(row, ["required_evidence", "evidence_chain", "必备证据", "证据链"])
    return {
        "source_id": text_value(first_by_keys(row, ["source_id", "id"])) or f"matrix-plan-{index}",
        "source_step": text_value(first_by_keys(row, ["source_step"])) or "matrix",
        "keyword": text_value(first_by_keys(row, ["keyword", "main_keyword_or_cluster", "target_keyword", "主攻关键词", "关键词"])),
        "intent_group": text_value(first_by_keys(row, ["intent_group", "keyword_intent_group", "意图簇", "关键词意图簇"])),
        "user_stage": text_value(first_by_keys(row, ["user_stage", "用户阶段"])),
        "type": text_value(first_by_keys(row, ["type", "article_type", "文章类型"])),
        "title": text_value(first_by_keys(row, ["title", "suggested_title", "建议标题", "标题"])),
        "role": text_value(first_by_keys(row, ["role", "main_role", "核心作用", "主要作用"])),
        "core_recommendation": text_value(first_by_keys(row, ["core_recommendation", "recommendation_logic", "核心推荐逻辑", "推荐逻辑"])),
        "required_evidence": value_list(evidence) or text_value(evidence),
        "competitor_boundary": text_value(first_by_keys(row, ["competitor_boundary", "竞品边界", "对比边界"])),
        "channels": channels,
        "brief_focus": text_value(first_by_keys(row, ["brief_focus", "后续Brief衔接字段", "Brief衔接要求"])),
        "priority": text_value(first_by_keys(row, ["priority", "执行优先级", "优先级"])) or "未标注",
        "status": text_value(first_by_keys(row, ["status", "状态"])) or "completed",
        "raw": row,
    }


def build_display_sections(plan: dict[str, Any]) -> list[dict[str, Any]]:
    section_specs = [
        (
            "demand_variables",
            "用户需求变量池",
            [
                ("demand_variable", "用户需求变量"),
                ("type", "所属类型"),
                ("pain_point", "真实痛点"),
                ("keywords", "对应关键词"),
                ("content_angle", "可转化内容角度"),
                ("recommendation_standard_impact", "对推荐标准的影响"),
            ],
        ),
        (
            "keyword_variable_mapping",
            "关键词 × 用户需求变量映射",
            [
                ("keyword", "关键词"),
                ("intent_group", "意图簇"),
                ("primary_demand_variable", "主需求变量"),
                ("secondary_demand_variable", "辅助需求变量"),
                ("user_real_question", "用户真实问题"),
                ("angle", "可切入角度"),
                ("risk", "内容风险"),
            ],
        ),
        (
            "content_theme_clusters",
            "内容主题簇",
            [
                ("theme_cluster", "内容主题簇"),
                ("keywords", "覆盖关键词"),
                ("core_user_demand", "核心用户需求"),
                ("core_standard", "核心判断标准"),
                ("required_evidence", "必备证据"),
                ("risk_boundary", "风险边界"),
            ],
        ),
        (
            "weekly_publishing_mix",
            "周发布配比",
            [
                ("intent_group", "意图簇"),
                ("keywords", "覆盖关键词"),
                ("weekly_volume", "周发布量"),
                ("channel_mix", "主要渠道组合"),
            ],
        ),
        (
            "monthly_publishing_mix",
            "月发布配比",
            [
                ("intent_group", "意图簇"),
                ("keywords", "覆盖关键词"),
                ("monthly_volume", "月发布量"),
                ("notes", "备注"),
            ],
        ),
        (
            "shared_supporting_articles",
            "共享支撑文",
            [
                ("title", "标题"),
                ("supported_keywords", "支撑关键词"),
                ("type", "文章类型"),
                ("role", "核心作用"),
                ("channels", "发布渠道"),
            ],
        ),
        (
            "unified_recommendation_language",
            "统一推荐口径",
            [
                ("intent_group", "意图簇"),
                ("language", "推荐口径"),
                ("proof_to_repeat", "需重复强调的证据"),
                ("wrong_expressions_to_avoid", "避免表达"),
            ],
        ),
        (
            "evidence_gaps",
            "证据缺口",
            [
                ("keyword_or_intent_group", "关键词或意图簇"),
                ("required_evidence", "所需证据"),
                ("current_evidence", "已有证据"),
                ("missing_evidence", "缺失证据"),
                ("impact", "影响"),
                ("suggested_supplement", "建议补充"),
            ],
        ),
        (
            "publishing_plan",
            "发布渠道规划",
            [
                ("article_type", "文章类型"),
                ("recommended_channels", "推荐渠道"),
                ("channel_role", "渠道作用"),
                ("publishing_notes", "发布注意事项"),
            ],
        ),
        (
            "schedule",
            "执行排期",
            [
                ("stage", "阶段"),
                ("period", "周期"),
                ("key_tasks", "关键任务"),
                ("article_types", "文章类型"),
                ("goal", "目标"),
            ],
        ),
        (
            "brief_requirements",
            "Brief 衔接要求",
            [
                ("field", "字段"),
                ("requirement", "要求"),
            ],
        ),
        (
            "daily_supplement_pool",
            "日常补充内容池",
            [
                ("type", "补充类型"),
                ("stage", "适用阶段"),
                ("role", "作用"),
                ("title_direction", "标题方向示例"),
                ("channels", "推荐渠道"),
            ],
        ),
        (
            "ai_retest_rules",
            "AI 复测与补内容规则",
            [
                ("retest_problem", "复测问题"),
                ("possible_reason", "可能原因"),
                ("missing_variable", "对应用户变量缺口"),
                ("content_direction", "补内容方向"),
                ("article_type", "推荐文章类型"),
                ("channel", "推荐渠道"),
            ],
        ),
        (
            "anti_homogenization_requirements",
            "Brief 防同质化要求",
            [
                ("field", "字段"),
                ("requirement", "要求"),
            ],
        ),
        (
            "warnings",
            "风险提示",
            [
                ("value", "提示"),
            ],
        ),
    ]
    sections: list[dict[str, Any]] = []
    for section_id, title, fields in section_specs:
        section = display_section(section_id, title, display_rows(plan.get(section_id)), fields)
        if section["items"]:
            sections.append(section)
    return sections


def normalize_content_plan_source(source: str) -> str:
    return "demand_matrix" if source == "demand_matrix" else "matrix"


def content_plan_source_label(source: str) -> str:
    return "需求驱动内容矩阵规划" if source == "demand_matrix" else "GEO 内容规划"


def display_section(section_id: str, title: str, rows: list[dict[str, Any]], fields: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": title,
        "items": [
            {
                "fields": [
                    {"label": label, "value": text_value(row.get(key))}
                    for key, label in fields
                    if text_value(row.get(key))
                ]
                or [{"label": "补充信息", "value": text_value(row)}]
            }
            for row in rows
            if text_value(row)
        ],
    }


def display_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                rows.append(item)
                continue
            text = text_value(item)
            if text:
                rows.append({"value": text})
    elif isinstance(value, dict):
        rows.append(value)
    else:
        text = text_value(value)
        if text:
            rows.append({"value": text})
    return rows


def normalize_intent_groups(value: Any) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for index, row in enumerate(list_records(value), start=1):
        article_types = filter_content_plan_article_types(value_list(first_by_keys(row, ["main_article_types", "article_types", "recommended_article_types", "文章类型", "常见主攻文章类型"])))
        group = {
            "id": text_value(first_by_keys(row, ["id", "name", "intent_group", "意图簇"])) or f"intent-{index}",
            "name": text_value(first_by_keys(row, ["name", "intent_group", "group", "意图簇", "关键词意图簇"])) or f"意图簇 {index}",
            "keywords": value_list(first_by_keys(row, ["keywords", "keyword_list", "关键词", "覆盖关键词"])),
            "user_question": text_value(first_by_keys(row, ["user_question", "user_real_question", "ai_question", "AI需要回答的问题", "用户真正想问什么"])),
            "user_stage": text_value(first_by_keys(row, ["user_stage", "stage", "用户阶段"])),
            "recommendation_logic": text_value(first_by_keys(row, ["recommendation_logic", "target_recommendation_logic", "推荐逻辑", "目标推荐逻辑"]))
            or "、".join(article_types),
            "article_types": article_types,
            "raw": row,
        }
        groups.append(group)
    return groups


def intent_group_name_lookup(intent_groups: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for group in intent_groups:
        group_id = text_value(group.get("id"))
        group_name = text_value(group.get("name"))
        if not group_name:
            continue
        if group_id:
            lookup[group_id] = group_name
        lookup[group_name] = group_name
    return lookup


def resolve_intent_group_labels(values: Any, lookup: dict[str, str]) -> list[str]:
    resolved: list[str] = []
    for value in value_list(values):
        label = resolve_intent_group_label(value, lookup)
        if label not in resolved:
            resolved.append(label)
    return resolved


def resolve_intent_group_label(value: str, lookup: dict[str, str]) -> str:
    if value in lookup:
        return lookup[value]
    parts = value.split(maxsplit=1)
    if parts and parts[0] in lookup:
        return lookup[parts[0]]
    return value


def resolve_item_intent_group(item: dict[str, Any], lookup: dict[str, str]) -> dict[str, Any]:
    current = text_value(item.get("intent_group"))
    if not current:
        return item
    resolved = resolve_intent_group_label(current, lookup)
    if resolved == current:
        return item
    return {**item, "intent_group_raw": current, "intent_group": resolved}


def normalize_article_type_pool(value: Any, items: list[dict[str, Any]], intent_group_lookup: dict[str, str] | None = None) -> list[dict[str, Any]]:
    intent_group_lookup = intent_group_lookup or {}
    rows = list_records(value)
    by_type: dict[str, dict[str, Any]] = {}
    if rows:
        for row in rows:
            article_type = text_value(first_by_keys(row, ["type", "article_type", "文章类型", "板块"]))
            if not content_plan_article_type_allowed(article_type):
                continue
            keywords = first_by_keys(row, ["keywords", "applicable_keywords", "covered_keywords_or_intent_groups", "适用关键词", "覆盖关键词", "覆盖意图簇"])
            by_type[article_type] = {
                "type": article_type,
                "role": text_value(first_by_keys(row, ["role", "core_role", "reason", "usage", "核心作用", "主要作用", "规划理由", "使用方式"])),
                "keywords": resolve_intent_group_labels(keywords, intent_group_lookup),
                "recommendation_strength": text_value(first_by_keys(row, ["recommendation_strength", "推荐强度"])),
                "count": len([item for item in items if item["type"] == article_type]),
                "raw": row,
            }
        return [row for article_type in ARTICLE_TYPE_ORDER if (row := by_type.get(article_type))]

    generated: list[dict[str, Any]] = []
    for article_type in ARTICLE_TYPE_ORDER:
        type_items = [item for item in items if item["type"] == article_type]
        if not type_items:
            continue
        generated.append(
            {
                "type": article_type,
                "role": unique_strings([item["role"] for item in type_items])[0] if unique_strings([item["role"] for item in type_items]) else "",
                "keywords": unique_strings([item["keyword"] for item in type_items]),
                "recommendation_strength": "",
                "count": len(type_items),
                "raw": {},
            }
        )
    return sorted(generated, key=lambda row: article_type_rank(row["type"]))


def content_plan_item_sort_key(intent_groups: list[dict[str, Any]]):
    intent_rank = {group["name"]: index for index, group in enumerate(intent_groups)}

    def sort_key(item: dict[str, Any]) -> tuple[int, int, int, str, str]:
        intent = text_value(item.get("intent_group"))
        return (
            intent_rank.get(intent, 999),
            priority_rank(text_value(item.get("priority"))),
            article_type_rank(text_value(item.get("type"))),
            text_value(item.get("keyword")),
            text_value(item.get("title")),
        )

    return sort_key


def priority_rank(value: str) -> int:
    lowered = value.lower()
    if "p0" in lowered or "最高" in value or "高" in value:
        return 0
    if "p1" in lowered or "中" in value:
        return 1
    if "p2" in lowered or "低" in value:
        return 2
    return 9


def article_type_rank(value: str) -> int:
    if value in ARTICLE_TYPE_ORDER:
        return ARTICLE_TYPE_ORDER.index(value)
    return len(ARTICLE_TYPE_ORDER)


def content_plan_article_type_allowed(value: str) -> bool:
    return value in ARTICLE_TYPE_ORDER


def filter_content_plan_article_types(values: list[str]) -> list[str]:
    return [article_type for article_type in ARTICLE_TYPE_ORDER if article_type in values]


def filter_content_plan_rows_by_type(rows: list[Any], key: str) -> list[Any]:
    filtered: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        article_type = text_value(first_by_keys(row, [key, "type", "article_type", "文章类型"]))
        if content_plan_article_type_allowed(article_type):
            filtered.append(row)
    return filtered


def filter_content_plan_schedule_rows(rows: list[Any]) -> list[Any]:
    filtered: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        article_types = filter_content_plan_article_types(value_list(first_by_keys(row, ["article_types", "文章类型"])))
        if not article_types:
            continue
        key_tasks = [
            task
            for task in value_list(first_by_keys(row, ["key_tasks", "tasks", "task", "关键任务", "任务"]))
            if not content_plan_text_mentions_blocked_type(task)
        ]
        filtered.append({**row, "article_types": article_types, "key_tasks": key_tasks})
    return filtered


def filter_content_plan_rows_without_blocked_text(rows: list[Any]) -> list[Any]:
    return [row for row in rows if not content_plan_text_mentions_blocked_type(text_value(row))]


def content_plan_text_mentions_blocked_type(value: str) -> bool:
    return any(marker in value for marker in BLOCKED_ARTICLE_TYPE_MARKERS)


def normalize_text_rows(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [row for row in value if text_value(row)]
    return [value] if text_value(value) else []


def list_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def first_by_keys(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return value
    return ""


def value_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return unique_strings([text_value(item) for item in value])
    if isinstance(value, dict):
        return [text_value(value)] if text_value(value) else []
    text = text_value(value)
    if not text:
        return []
    for separator in ("、", "\n", "，", ",", "/"):
        if separator in text:
            return unique_strings(part.strip() for part in text.split(separator))
    return [text]


def unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = text_value(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "、".join(filter(None, [text_value(item) for item in value]))
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            item_text = text_value(item)
            if item_text:
                parts.append(f"{key}：{item_text}")
        return "；".join(parts)
    return str(value).strip()


def join_non_empty(values: list[str], separator: str = "；") -> str:
    return separator.join([value for value in values if value])


def pdf_escape(value: Any) -> str:
    return escape(text_value(value)).replace("\n", "<br/>")

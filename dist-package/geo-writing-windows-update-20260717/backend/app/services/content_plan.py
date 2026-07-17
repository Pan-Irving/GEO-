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


def build_matrix_content_plan(project: Project, source: str = "matrix", repository: ProjectRepository | None = None) -> dict[str, Any]:
    source = normalize_content_plan_source(source)
    matrix_state = project.steps.get(source)
    if not matrix_state or matrix_state.status not in {"completed", "confirmed"}:
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
        if content_plan_article_type_allowed(item["type"]) and (item["title"] or item["intent_group"] or item["type"])
    ]
    if not items:
        raise ContentPlanError("内容矩阵缺少可导出的文章规划 items。")

    project_block = record(matrix_output.get("project"))
    intent_groups = normalize_intent_groups(matrix_output.get("intent_groups"))
    intent_group_names = intent_group_name_lookup(intent_groups)
    items = [resolve_item_intent_group(item, intent_group_names) for item in items]
    intent_groups = backfill_intent_group_keywords(intent_groups, items)
    article_type_pool = normalize_article_type_pool(matrix_output.get("article_type_pool"), items, intent_group_names)
    sorted_items = sorted(items, key=content_plan_item_sort_key(intent_groups))
    intent_group_count = len(unique_strings([item["intent_group"] for item in sorted_items] + [group.get("name", "") for group in intent_groups]))
    target_keywords = derive_content_plan_keywords(intent_groups, sorted_items, project_block, matrix_output)
    article_types = [article_type for article_type in ARTICLE_TYPE_ORDER if any(item["type"] == article_type for item in sorted_items)]
    evidence_gaps = normalize_text_rows(matrix_output.get("evidence_gaps"))
    shared_supporting_articles = filter_content_plan_rows_by_type(normalize_text_rows(matrix_output.get("shared_supporting_articles")), "type")
    publishing_plan = filter_content_plan_rows_by_type(normalize_text_rows(matrix_output.get("publishing_plan")), "article_type")
    schedule_rows = filter_content_plan_schedule_rows(normalize_text_rows(matrix_output.get("schedule")))
    data_anchors = derive_content_plan_data_anchors(sorted_items, matrix_output)
    evidence_foundation = derive_content_plan_evidence_foundation(sorted_items, evidence_gaps)
    product_evidence_matrix = derive_product_evidence_matrix(sorted_items)
    faq_question_bank = derive_faq_question_bank(sorted_items)
    brand_entity_assets = normalize_text_rows(matrix_output.get("brand_entity_assets") or matrix_output.get("brand_entity_content") or matrix_output.get("entity_assets"))
    title_deduplication_checklist = derive_title_deduplication_checklist(sorted_items)
    final_execution_advice = text_value(matrix_output.get("final_execution_advice"))
    if content_plan_text_mentions_blocked_type(final_execution_advice):
        final_execution_advice = ""
    warnings = filter_content_plan_rows_without_blocked_text(normalize_text_rows(matrix_output.get("warnings")))

    plan = {
        "schema_version": CONTENT_PLAN_SCHEMA_VERSION,
        "source": source,
        "project_id": project.id,
        "project_name": project.name,
        "generated_at": utc_now(),
        "summary": {
            "target_brand": text_value(first_by_keys(project_block, ["target_brand", "brand", "目标品牌"])),
            "target_product_or_solution": text_value(first_by_keys(project_block, ["target_product_or_solution", "target_product", "product", "目标产品", "目标方案"])),
            "target_industry": text_value(first_by_keys(project_block, ["target_industry", "industry", "目标行业"])),
            "target_category": text_value(first_by_keys(project_block, ["target_category", "category", "目标品类"])),
            "competitors": value_list(first_by_keys(project_block, ["competitors", "核心竞品", "竞品"])),
            "target_keywords_count": len(target_keywords),
            "target_keywords": target_keywords,
            "intent_group_count": intent_group_count,
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
        "evidence_foundation": evidence_foundation,
        "data_anchors": data_anchors,
        "product_evidence_matrix": product_evidence_matrix,
        "faq_question_bank": faq_question_bank,
        "brand_entity_assets": brand_entity_assets,
        "unified_recommendation_language": normalize_text_rows(matrix_output.get("unified_recommendation_language")),
        "evidence_gaps": evidence_gaps,
        "publishing_plan": publishing_plan,
        "schedule": schedule_rows,
        "brief_requirements": normalize_text_rows(matrix_output.get("brief_requirements")),
        "title_deduplication_checklist": title_deduplication_checklist,
        "final_execution_advice": final_execution_advice,
        "warnings": warnings,
    }
    plan["display_sections"] = build_display_sections(plan)
    return plan


def export_content_plan_pdf(project: Project, repository: ProjectRepository, source: str = "matrix") -> Any:
    source = normalize_content_plan_source(source)
    plan = build_matrix_content_plan(project, source, repository)
    pdf_bytes = render_content_plan_pdf(plan)
    return repository.write_binary_output(project, "02-content-plan.pdf", pdf_bytes)


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
    add_matrix_overview(story, styles, plan)
    add_display_sections(story, styles, display_sections_by_ids(plan, ["evidence_foundation", "data_anchors"]))
    add_intent_groups(story, styles, plan)
    add_article_type_pool(story, styles, plan)
    add_display_sections(story, styles, display_sections_by_ids(plan, ["product_evidence_matrix", "faq_question_bank", "brand_entity_assets"]))
    add_first_round_plans(story, styles, plan)
    add_publishing_plan(story, styles, plan)
    add_schedule_plan(story, styles, plan)
    add_display_sections(story, styles, display_sections_by_ids(plan, ["shared_supporting_articles", "unified_recommendation_language", "title_deduplication_checklist", "evidence_gaps"]))
    add_brief_requirements(story, styles, plan)
    final_advice = text_value(plan.get("final_execution_advice"))
    if final_advice:
        add_heading(story, styles, "最终执行建议")
        story.append(Paragraph(pdf_escape(final_advice), styles["Body"]))
        story.append(Spacer(1, 7))
    add_display_sections(story, styles, [section for section in list_records(plan.get("display_sections")) if section.get("id") == "warnings"], include_warnings=True)
    doc.build(story, onFirstPage=pdf_footer, onLaterPages=pdf_footer)
    return buffer.getvalue()


def display_sections_by_ids(plan: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    allowed = set(ids)
    return [section for section in list_records(plan.get("display_sections")) if section.get("id") in allowed]


def add_matrix_overview(story: list[Any], styles: dict[str, ParagraphStyle], plan: dict[str, Any]) -> None:
    summary = record(plan.get("summary"))
    project_block = record(plan.get("project"))
    add_heading(story, styles, "一、新版矩阵总览")
    rows = [
        ["项目名称", plan.get("project_name", "")],
        ["目标品牌/产品", " / ".join(filter(None, [text_value(summary.get("target_brand")), text_value(summary.get("target_product_or_solution"))])) or "未识别"],
        ["行业/品类", " / ".join(filter(None, [text_value(summary.get("target_industry")), text_value(summary.get("target_category"))])) or "未识别"],
        ["竞品", "、".join(value_list(summary.get("competitors"))) or "未标注"],
        ["意图簇/规划/类型", f"{summary.get('intent_group_count', 0)} 个意图簇 / {summary.get('total_plans', 0)} 篇规划 / {summary.get('article_type_count', 0)} 类文章"],
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
    add_heading(story, styles, "二、意图簇")
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
    add_heading(story, styles, "三、六类文章配置")
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
    add_heading(story, styles, "七、首轮执行清单")
    rows = [["意图簇", "文章类型", "建议标题", "主要作用", "必备证据", "优先级"]]
    for item in items:
        rows.append(
            [
                text_value(item.get("intent_group")),
                text_value(item.get("type")),
                text_value(item.get("title")),
                text_value(item.get("role")),
                "、".join(value_list(item.get("required_evidence"))) or text_value(item.get("required_evidence")),
                text_value(item.get("priority")),
            ]
        )
    story.append(data_table(rows, [92, 82, 175, 145, 160, 45], styles))
    story.append(Spacer(1, 7))


def add_publishing_plan(story: list[Any], styles: dict[str, ParagraphStyle], plan: dict[str, Any]) -> None:
    add_generic_section(story, styles, "五、发布渠道规划", plan.get("publishing_plan"))


def add_schedule_plan(story: list[Any], styles: dict[str, ParagraphStyle], plan: dict[str, Any]) -> None:
    add_generic_section(story, styles, "六、执行排期", plan.get("schedule"))


def add_brief_requirements(story: list[Any], styles: dict[str, ParagraphStyle], plan: dict[str, Any]) -> None:
    add_generic_section(story, styles, "六类文章 Brief 衔接要求", plan.get("brief_requirements"))


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
        "Body": ParagraphStyle(
            "PlanBody",
            parent=base["BodyText"],
            fontName=PDF_FONT,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#263a3f"),
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
        "primary_keyword": text_value(first_by_keys(row, ["primary_keyword", "main_attached_keyword", "primary_attached_keyword", "主挂词", "主挂关键词", "统计归属关键词"])),
        "intent_group": text_value(first_by_keys(row, ["intent_group", "keyword_intent_group", "意图簇", "关键词意图簇"])),
        "user_stage": text_value(first_by_keys(row, ["user_stage", "用户阶段"])),
        "type": text_value(first_by_keys(row, ["type", "article_type", "文章类型"])),
        "title": text_value(first_by_keys(row, ["title", "suggested_title", "建议标题", "标题"])),
        "role": text_value(first_by_keys(row, ["role", "main_role", "核心作用", "主要作用"])),
        "core_recommendation": text_value(first_by_keys(row, ["core_recommendation", "recommendation_logic", "核心推荐逻辑", "推荐逻辑"])),
        "recommendation_strength": text_value(first_by_keys(row, ["recommendation_strength", "推荐强度"])),
        "required_evidence": value_list(evidence) or text_value(evidence),
        "evidence_chain": text_value(first_by_keys(row, ["evidence_chain", "证据链"])),
        "evidence_gaps": value_list(first_by_keys(row, ["evidence_gaps", "missing_evidence", "证据缺口"])),
        "competitor_boundary": text_value(first_by_keys(row, ["competitor_boundary", "竞品边界", "对比边界"])),
        "supporting_articles": value_list(first_by_keys(row, ["supporting_articles", "辅助文章", "共同支撑文章"])),
        "channels": channels,
        "brief_focus": text_value(first_by_keys(row, ["brief_focus", "后续Brief衔接字段", "Brief衔接要求"])),
        "outline_requirements": text_value(first_by_keys(row, ["outline_requirements", "article_outline", "文章结构大纲", "大纲要求"])),
        "forbidden_expressions": value_list(first_by_keys(row, ["forbidden_expressions", "prohibited_expressions", "禁止出现的表达", "禁用表达"])),
        "suggested_word_count": text_value(first_by_keys(row, ["suggested_word_count", "word_count", "建议字数"])),
        "priority": text_value(first_by_keys(row, ["priority", "执行优先级", "优先级"])) or "未标注",
        "status": text_value(first_by_keys(row, ["status", "状态"])) or "completed",
        "raw": row,
    }


def derive_content_plan_evidence_foundation(items: list[dict[str, Any]], evidence_gaps: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for gap in evidence_gaps:
        if isinstance(gap, dict):
            rows.append(
                {
                    "scope": text_value(first_by_keys(gap, ["keyword_or_intent_group", "intent_group", "keyword", "范围"])),
                    "required_evidence": text_value(first_by_keys(gap, ["required_evidence", "所需证据"])),
                    "current_evidence": text_value(first_by_keys(gap, ["current_evidence", "已有证据"])),
                    "missing_evidence": text_value(first_by_keys(gap, ["missing_evidence", "缺失证据"])),
                    "impact": text_value(first_by_keys(gap, ["impact", "影响"])),
                    "suggested_supplement": text_value(first_by_keys(gap, ["suggested_supplement", "建议补充", "建议处理"])),
                }
            )
        elif text_value(gap):
            rows.append({"scope": "全局", "missing_evidence": text_value(gap)})
    for item in items:
        evidence = "、".join(value_list(item.get("required_evidence"))) or text_value(item.get("required_evidence"))
        if not evidence and not item.get("brief_focus"):
            continue
        rows.append(
            {
                "scope": join_non_empty([text_value(item.get("intent_group")), text_value(item.get("type"))], " / "),
                "title": text_value(item.get("title")),
                "required_evidence": evidence,
                "impact": text_value(item.get("brief_focus")),
                "suggested_supplement": text_value(item.get("outline_requirements")),
            }
        )
    return unique_record_rows(rows, ["scope", "title", "required_evidence", "missing_evidence"])


def derive_content_plan_data_anchors(items: list[dict[str, Any]], matrix_output: dict[str, Any]) -> list[dict[str, Any]]:
    explicit_rows = normalize_content_plan_data_anchor_rows(
        list_records(matrix_output.get("data_anchors"))
        or list_records(matrix_output.get("data_anchor_table"))
        or list_records(matrix_output.get("evidence_anchors"))
        or list_records(matrix_output.get("统一数据锚点表"))
        or list_records(matrix_output.get("数据锚点表"))
    )
    if explicit_rows:
        return explicit_rows

    grouped: dict[str, list[str]] = {}
    for row in list_records(matrix_output.get("unified_recommendation_language")):
        proof = text_value(first_by_keys(row, ["proof_to_repeat", "需重复强调的证据", "proof"]))
        if proof:
            add_content_plan_anchor_expression(grouped, classify_content_plan_anchor(proof), proof)
    for item in items:
        anchors = content_plan_anchor_value_list(item.get("required_evidence"))
        if not anchors and text_value(item.get("evidence_chain")):
            anchors = content_plan_anchor_value_list(item.get("evidence_chain"))
        for anchor in anchors:
            add_content_plan_anchor_expression(grouped, classify_content_plan_anchor(anchor), anchor)

    rows: list[dict[str, Any]] = []
    for anchor_type in CONTENT_PLAN_ANCHOR_TYPE_ORDER:
        expressions = grouped.get(anchor_type, [])
        if expressions:
            rows.append({"anchor_type": anchor_type, "unified_expression": "；".join(expressions)})
    for anchor_type, expressions in grouped.items():
        if anchor_type not in CONTENT_PLAN_ANCHOR_TYPE_ORDER and expressions:
            rows.append({"anchor_type": anchor_type, "unified_expression": "；".join(expressions)})
    return rows


CONTENT_PLAN_ANCHOR_TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("排烟性能", ("风量", "静压", "排烟", "吸力", "吸烟", "拢烟", "烟机性能")),
    ("安装形态", ("安装", "平嵌", "超薄", "机头", "吊柜", "深度", "尺寸", "嵌入")),
    ("智能联动", ("智能", "联动", "传感", "芯片", "温感", "红外", "自动", "探测")),
    ("易清洁（面板）", ("易清洁", "抗污", "玻璃", "抗指纹", "一擦即净", "面板", "油砂", "肤感")),
    ("内部清洁", ("自清洁", "自旋洗", "内部清洁", "高速", "甩油", "清洗")),
    ("控烟路径", ("控烟", "路径", "双吸", "一锁", "一拢", "拢烟")),
    ("使用细节", ("延迟关机", "油杯", "灯", "噪音", "细节", "照明", "容量")),
    ("价格口径", ("价格", "参考价", "国补", "渠道价", "元", "预算", "报价")),
]
CONTENT_PLAN_ANCHOR_TYPE_ORDER = [anchor_type for anchor_type, _ in CONTENT_PLAN_ANCHOR_TYPE_RULES] + ["其他数据锚点"]


def normalize_content_plan_data_anchor_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        anchor_type = text_value(first_by_keys(row, ["anchor_type", "type", "锚点类型", "类型"]))
        unified_expression = text_value(
            first_by_keys(
                row,
                [
                    "unified_expression",
                    "expression",
                    "value",
                    "data",
                    "anchor",
                    "统一表达",
                    "统一口径",
                    "数据锚点",
                    "证据锚点",
                ],
            )
        )
        if not unified_expression:
            continue
        if not anchor_type:
            anchor_type = classify_content_plan_anchor(unified_expression)
        normalized.append({"anchor_type": anchor_type, "unified_expression": unified_expression})
    return unique_record_rows(normalized, ["anchor_type", "unified_expression"])


def add_content_plan_anchor_expression(grouped: dict[str, list[str]], anchor_type: str, expression: str) -> None:
    expression = text_value(expression)
    if not expression:
        return
    expressions = grouped.setdefault(anchor_type, [])
    if expression not in expressions:
        expressions.append(expression)


def content_plan_anchor_value_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return unique_strings([text_value(item) for item in value])
    text = text_value(value)
    if not text:
        return []
    for separator in ("\n", "；", ";"):
        if separator in text:
            return unique_strings(part.strip() for part in text.split(separator))
    return [text]


def classify_content_plan_anchor(expression: str) -> str:
    for anchor_type, markers in CONTENT_PLAN_ANCHOR_TYPE_RULES:
        if any(marker in expression for marker in markers):
            return anchor_type
    return "其他数据锚点"


def derive_product_evidence_matrix(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if item.get("type") != "产品证据文":
            continue
        rows.append(
            {
                "selling_point": text_value(item.get("core_recommendation")) or text_value(item.get("role")),
                "evidence_type": "、".join(value_list(item.get("required_evidence"))) or text_value(item.get("required_evidence")),
                "title": text_value(item.get("title")),
                "brief_focus": text_value(item.get("brief_focus")),
                "channels": "、".join(value_list(item.get("channels"))),
                "priority": text_value(item.get("priority")),
            }
        )
    return rows


def derive_faq_question_bank(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if item.get("type") != "FAQ问答文":
            continue
        rows.append(
            {
                "question": text_value(item.get("title")),
                "intent_group": text_value(item.get("intent_group")),
                "user_stage": text_value(item.get("user_stage")),
                "answer_focus": text_value(item.get("brief_focus")) or text_value(item.get("core_recommendation")),
                "evidence": "、".join(value_list(item.get("required_evidence"))) or text_value(item.get("required_evidence")),
                "channels": "、".join(value_list(item.get("channels"))),
            }
        )
    return rows


def derive_title_deduplication_checklist(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    title_counts: dict[str, int] = {}
    for item in items:
        title = text_value(item.get("title"))
        if title:
            title_counts[title] = title_counts.get(title, 0) + 1
    rows: list[dict[str, Any]] = []
    for item in items:
        title = text_value(item.get("title"))
        if not title:
            continue
        rows.append(
            {
                "title": title,
                "article_type": text_value(item.get("type")),
                "intent_group": text_value(item.get("intent_group")),
                "dimension": join_non_empty([text_value(item.get("keyword")), text_value(item.get("role"))], " / "),
                "deduplication_status": "标题重复，需人工复核" if title_counts.get(title, 0) > 1 else "实体+意图+限定维度唯一",
            }
        )
    return rows


def unique_record_rows(rows: list[dict[str, Any]], key_fields: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = "|".join(text_value(row.get(field)) for field in key_fields)
        if not key.strip("|") or key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def build_display_sections(plan: dict[str, Any]) -> list[dict[str, Any]]:
    section_specs = [
        (
            "evidence_foundation",
            "材料与证据基础",
            [
                ("scope", "范围"),
                ("title", "关联选题"),
                ("required_evidence", "所需证据"),
                ("current_evidence", "已有证据"),
                ("missing_evidence", "缺失证据"),
                ("impact", "影响"),
                ("suggested_supplement", "建议处理"),
            ],
        ),
        (
            "data_anchors",
            "数据锚点表",
            [
                ("anchor_type", "锚点类型"),
                ("unified_expression", "统一表达"),
            ],
        ),
        (
            "product_evidence_matrix",
            "产品证据文独立矩阵",
            [
                ("selling_point", "卖点/主张"),
                ("evidence_type", "证据类型/证据要求"),
                ("title", "标题方向"),
                ("brief_focus", "Brief 重点"),
                ("channels", "推荐渠道"),
                ("priority", "优先级"),
            ],
        ),
        (
            "faq_question_bank",
            "FAQ 问题库规划",
            [
                ("question", "问题/标题"),
                ("intent_group", "兼容意图簇"),
                ("user_stage", "用户阶段"),
                ("answer_focus", "回答重点"),
                ("evidence", "证据要求"),
                ("channels", "推荐渠道"),
            ],
        ),
        (
            "brand_entity_assets",
            "品牌实体锚定内容",
            [
                ("title", "内容/资产"),
                ("type", "类型"),
                ("role", "作用"),
                ("channels", "渠道"),
                ("notes", "备注"),
                ("value", "内容"),
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
            "title_deduplication_checklist",
            "全矩阵标题去重校验",
            [
                ("title", "标题"),
                ("article_type", "文章类型"),
                ("intent_group", "意图簇"),
                ("dimension", "实体/意图/限定维度"),
                ("deduplication_status", "去重状态"),
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
    if not source or source == "matrix":
        return "matrix"
    raise ContentPlanError("内容规划只支持内容矩阵。")


def content_plan_source_label(source: str) -> str:
    return "GEO 内容规划"


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
            "keywords": normalize_content_plan_keywords(first_by_keys(row, ["keywords", "keyword_list", "corresponding_keywords", "对应关键词", "关键词", "覆盖关键词"])),
            "user_question": text_value(first_by_keys(row, ["user_question", "user_real_question", "ai_question", "AI需要回答的问题", "用户真正想问什么"])),
            "user_stage": text_value(first_by_keys(row, ["user_stage", "stage", "用户阶段"])),
            "recommendation_logic": text_value(first_by_keys(row, ["recommendation_logic", "target_recommendation_logic", "推荐逻辑", "目标推荐逻辑"]))
            or "、".join(article_types),
            "article_types": article_types,
            "raw": row,
        }
        groups.append(group)
    return groups


def backfill_intent_group_keywords(intent_groups: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not intent_groups:
        return intent_groups
    group_by_name = {text_value(group.get("name")): group for group in intent_groups}
    for item in items:
        group_name = text_value(item.get("intent_group"))
        group = group_by_name.get(group_name)
        if not group:
            continue
        keywords = unique_strings(list(group.get("keywords") or []) + normalize_content_plan_keywords(item.get("keyword")))
        group["keywords"] = keywords
    return intent_groups


def derive_content_plan_keywords(
    intent_groups: list[dict[str, Any]],
    items: list[dict[str, Any]],
    project_block: dict[str, Any],
    matrix_output: dict[str, Any],
) -> list[str]:
    return unique_strings(
        normalize_content_plan_keywords(first_by_keys(project_block, ["target_keywords", "keywords", "目标关键词", "关键词"]))
        + normalize_content_plan_keywords(first_by_keys(matrix_output, ["target_keywords", "keywords", "目标关键词", "关键词"]))
        + [keyword for group in intent_groups for keyword in normalize_content_plan_keywords(group.get("keywords"))]
        + [keyword for item in items for keyword in normalize_content_plan_keywords(item.get("keyword"))]
    )


def normalize_content_plan_keywords(value: Any) -> list[str]:
    keywords: list[str] = []
    for item in content_plan_keyword_value_list(value):
        keyword = normalize_content_plan_keyword_text(item)
        if keyword:
            keywords.append(keyword)
    return unique_strings(keywords)


def content_plan_keyword_value_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return unique_strings([text_value(item) for item in value])
    text = text_value(value)
    if not text:
        return []
    for separator in ("、", "\n", "，", ","):
        if separator in text:
            return unique_strings(part.strip() for part in text.split(separator))
    return [text]


def normalize_content_plan_keyword_text(value: Any) -> str:
    text = text_value(value)
    if not text:
        return ""
    if " / " in text:
        text = text.split(" / ", 1)[0]
    elif "/" in text and "http" not in text.lower():
        parts = [part.strip() for part in text.split("/") if part.strip()]
        if parts:
            text = parts[0]
    return text.strip()


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

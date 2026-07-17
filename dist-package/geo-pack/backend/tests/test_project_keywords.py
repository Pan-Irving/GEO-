from app.services.project_keywords import extract_keyword_lines


def test_extract_keyword_lines_skips_keyword_document_title():
    text = """
特惠螺丝GEO优化关键词

- 高强度热镀锌螺丝生产厂家推荐
- 热镀锌螺丝生产厂家推荐
- 热镀锌螺丝生产厂家哪家好
- 热镀锌螺丝哪个厂家生产的质量好
- 杭州靠谱的热镀锌螺丝生产厂家
"""

    assert extract_keyword_lines(text) == [
        "高强度热镀锌螺丝生产厂家推荐",
        "热镀锌螺丝生产厂家推荐",
        "热镀锌螺丝生产厂家哪家好",
        "热镀锌螺丝哪个厂家生产的质量好",
        "杭州靠谱的热镀锌螺丝生产厂家",
    ]


def test_extract_keyword_lines_reads_only_keyword_column_from_table():
    text = """
| 关键词 | 优先级 | 渠道建议 |
| --- | --- | --- |
| 热镀锌螺丝生产厂家推荐 | P1 | 知乎 |
| 热镀锌螺丝生产厂家哪家好 | P2 | 小红书 |
"""

    assert extract_keyword_lines(text) == [
        "热镀锌螺丝生产厂家推荐",
        "热镀锌螺丝生产厂家哪家好",
    ]

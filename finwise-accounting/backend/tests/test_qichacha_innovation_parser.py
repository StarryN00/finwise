from app.services.qichacha_innovation_parser import parse_qichacha_innovation_text


def test_parse_qichacha_innovation_text_only_keeps_lit_certifications():
    text = """
    科创分 72
    良好
    所属国标二级行业：研究和试验发展
    同行业内科创分排名 前34%
    科技型企业认定情况 1
    序号 科技认定名称 匹配情况
    1 科技型中小企业 国家级 ✓
    2 高新技术企业 ×
    3 专精特新“小巨人”企业 ×
    4 专精特新中小企业 ×
    5 创新型中小企业 ×
    """

    result = parse_qichacha_innovation_text(text)

    assert result["summary"] == "科创分72，等级良好，行业研究和试验发展，同行排名前34%。"
    statuses = {tag["name"]: tag["status"] for tag in result["tags"]}
    assert statuses["科技型中小企业"] == "HIT"
    assert "高新技术企业" not in statuses
    assert "专精特新“小巨人”企业" not in statuses
    assert "专精特新中小企业" not in statuses
    assert "创新型中小企业" not in statuses
    assert all(tag["category"] == "QCC_TECH_CERTIFICATION" for tag in result["tags"])


def test_parse_qichacha_innovation_text_captures_ip_counts():
    text = """
    知识产权取得情况
    有效发明专利
    1
    有效实用新型
    2
    有效外观设计
    0
    发明专利申请
    3
    软件著作权
    3
    """

    result = parse_qichacha_innovation_text(text)

    values = {tag["name"]: tag["value"] for tag in result["tags"]}
    assert values["有效发明专利"] == "1"
    assert values["有效实用新型"] == "2"
    assert values["有效外观设计"] == "0"
    assert values["发明专利申请"] == "3"
    assert values["软件著作权"] == "3"
    assert all(tag["status"] == "HIT" for tag in result["tags"])
    assert all(tag["category"] == "QCC_INTELLECTUAL_PROPERTY" for tag in result["tags"])

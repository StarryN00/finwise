from pathlib import Path
from html.parser import HTMLParser


def test_static_entry_uses_relative_assets_and_file_mode_has_api_fallback():
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    script = (root / "static" / "app.js").read_text(encoding="utf-8")
    assert 'href="styles.css"' in html
    assert 'src="app.js"' in html
    assert "window.location.protocol === 'file:'" in script
    assert "http://127.0.0.1:8766" in script


def test_http_root_serves_relative_assets(client):
    stylesheet = client.get("/styles.css")
    script = client.get("/app.js")

    assert stylesheet.status_code == 200
    assert "--paper" in stylesheet.text
    assert script.status_code == 200
    assert "API_BASE" in script.text


def test_operator_workbench_demo_is_standalone_and_covers_attention_flows():
    root = Path(__file__).resolve().parents[1]
    demo = (root / "static" / "operator-workbench-demo.html").read_text(encoding="utf-8")

    assert "FinWise · 多企业待办驾驶舱 Demo" in demo
    assert "昆山聚贤达信息科技有限公司" in demo
    assert "苏州新启源科技有限公司" in demo
    assert "新建企业" in demo
    assert "等待上传" in demo
    assert "localStorage" in demo
    assert "模拟新异常" in demo
    assert "确认已与客户核实" in demo
    assert "其他企业不会被自动切换" not in demo
    assert "当前只聚焦一个任务" not in demo
    assert "营业执照号（演示）" in demo
    assert '<span class="company-license">营业执照号' not in demo
    assert "PROCESSING RESULT" not in demo
    assert "SOURCE PACK" not in demo
    assert "companySearch" in demo
    assert "data-tag-company" in demo
    assert "finwise.operator-workbench.company-tags" in demo
    assert "finwise.operator-workbench.task-state" in demo
    assert "finwise.operator-workbench.v5" in demo
    assert "company-tools" in demo
    assert "当前任务" in demo
    assert "查看处理详情" in demo
    assert 'aria-label="阶段工作区"' in demo
    assert 'class="detail-tabs"' not in demo
    assert 'data-action="detail"' not in demo
    assert "renderStageInspection" not in demo
    assert "整体阶段完成度" in demo
    assert "已核实" in demo
    assert "往期数据" in demo and "已归档凭证" in demo
    assert "confirmationNote" in demo
    assert "资料接收" in demo and "资料分析" in demo and "待确认与校验" in demo
    assert "prefers-reduced-motion" in demo
    assert "@media(max-width:760px)" in demo

class DemoHTMLParser(HTMLParser):
    """Validate explicit nesting and dependency-free static document chrome."""
    void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.ids = set()
        self.external_assets = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            assert element_id not in self.ids
            self.ids.add(element_id)
        if tag in {"script", "img", "iframe", "link"}:
            source = attributes.get("src") or attributes.get("href")
            if source:
                self.external_assets.append(source)
        if tag not in self.void_tags:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack.pop() == tag


def test_demo_html_structure_and_no_external_assets():
    root = Path(__file__).resolve().parents[1]
    parser = DemoHTMLParser()
    parser.feed((root / "static" / "operator-workbench-demo.html").read_text(encoding="utf-8"))
    parser.close()
    assert parser.stack == []
    assert parser.external_assets == []
    assert {"companySearch", "main", "dialog", "sidebar"} <= parser.ids


def test_http_serves_standalone_operator_demo(client):
    response = client.get("/static/operator-workbench-demo.html")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "FinWise · 多企业待办驾驶舱 Demo" in response.text


def test_http_serves_formal_portfolio_page_and_its_api_entry(client):
    root = Path(__file__).resolve().parents[1]
    page = (root / "static" / "portfolio.html").read_text(encoding="utf-8")
    assert "FinWise · 企业总览" in page
    assert "/api/v1/portfolio" in page
    assert "/api/v1/auth/me" in page
    assert "state.csrf=session.csrf_token||''" in page
    assert "授权范围" in page
    response = client.get("/static/portfolio.html")
    assert response.status_code == 200
    assert "企业列表" in response.text


def test_formal_operator_page_connects_real_write_workflows_without_external_assets(client):
    root = Path(__file__).resolve().parents[1]
    page = (root / "static" / "operator.html").read_text(encoding="utf-8")
    script = (root / "static" / "operator.js").read_text(encoding="utf-8")
    materials = (root / "static" / "operator-materials.js").read_text(encoding="utf-8")
    css = (root / "static" / "operator.css").read_text(encoding="utf-8")
    assert "FinWise · 期间工作台" in page
    assert '<section id="scopeChooser" class="hidden"' in page
    assert '请输入用户名和密码。' in page
    assert "location.replace(OPERATOR_HTTP_ENTRY)" in script
    assert "http://127.0.0.1:8767/static/operator.html" in script
    assert "/api/v1/artifacts" in script
    assert "/api/v1/commands" in script
    assert "/api/v1/baseline/candidate" in script
    assert "/api/v1/auth/me" in script
    assert "state.csrf=session.csrf_token||''" in script
    assert "confirm_baseline" in script
    assert 'table-wrap' in script and 'statusBadge' in script
    assert '资料结构' in script and '账务可用' in script and 'material-open-filter' in script
    assert 'selected_processing_tasks' in script and '你当前无需操作' in script
    assert "badge('系统处理中','blue')" in script
    assert '系统处理中 ${systemIssues} 项 · 系统检查 ${systemChecks} 项' in materials
    assert '查看动作使用与兜底占比' in materials
    assert "无剩余资料问题 '+(c.other_period||0)+' 条" in materials
    assert 'scrollIntoView' not in script and 'DEMO-IMPORT-' not in script
    assert '.problem-review-detail>.row{padding-bottom:12px;margin-bottom:12px}' in css
    assert '.problem-review-job>details,.problem-review-job>button{margin-top:12px}' in css
    parser = DemoHTMLParser()
    parser.feed(page)
    parser.close()
    assert parser.stack == []
    assert parser.external_assets == [
            'operator.css?v=verify-bulk-1',
        'operator-historical.js?v=guided-decision-2',
            'operator-materials.js?v=verify-bulk-1',
        'operator-problem-review.js?v=action-types-1',
            'operator-material-navigation.js?v=verify-bulk-1',
        'operator-bank-periods.js?v=bank-period-1',
            'operator-material-guidance.js?v=action-types-1',
            'operator-decision.js?v=verify-bulk-1',
        'operator-bills.js?v=guided-decision-2',
        'operator-invoice-review.js?v=guided-decision-2',
        'operator-accounts.js?v=guided-decision-2',
        'operator-mapping.js?v=guided-decision-2',
        'operator-parse-plans.js?v=structure-plan-1', 'operator.js?v=login-flow-1']
    for asset in parser.external_assets:
        assert client.get('/static/' + asset).status_code == 200
    response = client.get("/static/operator.html")
    assert response.status_code == 200

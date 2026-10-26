from pathlib import Path
from html.parser import HTMLParser


def test_http_root_redirects_to_operator_workbench(client):
    """第一代 index.html / app.js / styles.css 已删除，根路径只剩一个入口。"""
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/static/operator.html"
    assert client.get("/app.js").status_code == 404
    assert client.get("/styles.css").status_code == 404


class PageHTMLParser(HTMLParser):
    """Validate explicit nesting and the declared external-asset list of a page."""
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
    # 第三步只有两块：中间当前问题与选项卡，右侧四类问题与数量。
    assert 'class="triage"' in materials and 'triage-bucket-head' in materials
    assert 'renderProblemQueue' in materials and 'materialQueue' in materials
    assert '更多：原件、成果与处理记录' in materials
    assert 'data-action="material-pick"' in materials
    # 不再有"先点一下处理方式"这一层：主视图直接就是那张卡。
    assert 'materialNextStepPanel()' not in materials.split('function materialNextStepPanel')[0]
    assert 'scrollIntoView' not in script and 'DEMO-IMPORT-' not in script
    assert '.problem-review-detail>.row{padding-bottom:12px;margin-bottom:12px}' in css
    assert '.problem-review-job>details,.problem-review-job>button{margin-top:12px}' in css
    parser = PageHTMLParser()
    parser.feed(page)
    parser.close()
    assert parser.stack == []
    assert parser.external_assets == [
            'operator.css?v=main-flow-1',
        'operator-historical.js?v=guided-decision-2',
            'operator-materials.js?v=verify-bulk-2',
        'operator-problem-review.js?v=triage-1',
            'operator-material-navigation.js?v=verify-bulk-2',
        'operator-bank-periods.js?v=bank-period-1',
            'operator-material-guidance.js?v=triage-1',
            'operator-decision.js?v=verify-bulk-2',
        'operator-bills.js?v=guided-decision-2',
        'operator-invoice-review.js?v=guided-decision-2',
        'operator-accounts.js?v=guided-decision-2',
        'operator-mapping.js?v=guided-decision-2',
        'operator-parse-plans.js?v=structure-plan-1', 'operator-profile-cards.js?v=profile-cards-1', 'operator-new-scope.js?v=new-scope-1',
        'operator-voucher-proposals.js?v=voucher-proposals-1',
        'operator.js?v=main-flow-1']
    for asset in parser.external_assets:
        assert client.get('/static/' + asset).status_code == 200
    response = client.get("/static/operator.html")
    assert response.status_code == 200


def test_static_assets_are_always_revalidated(client):
    """资源上的 ?v= 是手写的，改了文件忘了改版本号必然会发生 —— 实测发生过两次，
    表现都是"功能加了但界面毫无反应，控制台也不报错"。
    这里只要求重新验证，文件没变仍然走 304。"""
    for path in ("/static/operator.html", "/static/operator.js?v=main-flow-1",
                 "/static/operator.css?v=main-flow-1"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "no-cache" in response.headers.get("cache-control", ""), path


def test_every_page_module_registers_its_actions_at_boot():
    """在 render() 里注册不够：一个企业都没有、或停在别的视图时 render 不会跑，
    那些入口就点不动。实测漏注册时按钮存在但毫无反应，控制台也没有报错。"""
    root = Path(__file__).resolve().parents[1]
    script = (root / "static" / "operator.js").read_text(encoding="utf-8")
    boot = script[script.index("if(location.protocol==='file:')") - 2000:
                  script.index("if(location.protocol==='file:')")]
    for installer in ("installNewScopeActions", "installProfileCardActions",
                      "installVoucherProposalActions"):
        assert installer in boot, f"{installer} 未在启动时注册"

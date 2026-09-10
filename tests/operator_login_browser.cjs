const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const types = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8'};

function staticServer() {
  return http.createServer((request, response) => {
    const pathname = new URL(request.url, 'http://127.0.0.1').pathname;
    const target = path.join(root, pathname);
    if (!target.startsWith(path.join(root, 'static') + path.sep) || !fs.existsSync(target)) {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, {'Content-Type':types[path.extname(target)] || 'application/octet-stream'});
    response.end(fs.readFileSync(target));
  });
}

async function main() {
  const server = staticServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:1200,height:800}});
  let loggedIn = false;
  let loginPayload = null;
  try {
    await page.route('**/api/v1/**', async route => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (pathname === '/api/v1/auth/login') {
        loginPayload = request.postDataJSON();
        loggedIn = true;
        return route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({csrf_token:'csrf-login'})});
      }
      if (pathname === '/api/v1/auth/me') {
        return route.fulfill({status:loggedIn?200:401, contentType:'application/json', body:JSON.stringify(loggedIn?{csrf_token:'csrf-me',role:'accountant',user_id:'login-tester'}:{detail:'请先登录'})});
      }
      if (pathname === '/api/v1/portfolio') {
        return route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({scopes:[{
          scope:{tenant_id:'t',organization_id:'o',legal_entity_id:'e',ledger_id:'l',accounting_period_id:'2026-01',baseline_id:'b'},
          display_context:{company_name:'登录后企业',business_license_number:'TEST-LOGIN',ledger_name:'主账套'},
          blockers:[],baseline:{validation:{status:'DRAFT'}},pending_confirmation_cards:0
        }]})});
      }
      return route.fulfill({status:503, contentType:'application/json', body:JSON.stringify({error:{message:'登录夹具到此停止'}})});
    });

    await page.goto(base + '/static/operator.html');
    await page.locator('#loginForm').waitFor();
    assert.equal(await page.locator('#scopeChooser').isHidden(), true);
    assert.doesNotMatch(await page.locator('#sidebar').innerText(), /处理范围/);
    assert.match(await page.locator('#loginForm').innerText(), /用户名.*密码/s);

    await page.locator('#username').fill('login-tester');
    await page.locator('#password').fill('LoginOnly!2026');
    await page.locator('#loginForm button').click();
    await page.locator('#scopeChooser').waitFor();

    assert.deepEqual(loginPayload, {username:'login-tester', password:'LoginOnly!2026'});
    assert.equal(Object.hasOwn(loginPayload, 'scope'), false);
    assert.equal(await page.locator('#loginForm').isHidden(), true);
    assert.equal(await page.locator('[data-scope]').count(), 1);
    assert.match(await page.locator('#sidebar').innerText(), /处理范围.*登录后企业/s);
    console.log('PASS login submits credentials only and reveals scopes after authentication');
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});

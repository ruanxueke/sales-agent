const $ = (id) => document.getElementById(id);
const api = window.desktopApi;
let auth = null;
let visionRunning = false;
let loginMode = 'key';
const MODULE_TITLES = { dashboard:'经营总览', customers:'客户档案', portraits:'客户360', leads:'线索管理', opportunities:'商机管理', orders:'订单售后', cpq:'报价合同', finance:'回款交付', followups:'自动跟进', sop:'销售SOP', 'sales-flow':'销售流程', tickets:'工单回访', handovers:'转人工', quality:'质检陪练', nurture:'培育计划', campaigns:'营销活动', engagement:'预约优惠', ammo:'话术弹药库', winning:'赢单引擎', feedback:'标注回灌', official:'公众号', wechat:'个人微信', vision:'视觉执行器', bi:'数据智能', aiops:'AI经营', optimization:'优化中心', 'commercial-center':'商用中心', 'enterprise-level':'企业级驾驶舱', knowledge:'知识库', platform:'平台设置', compliance:'合规设置', enterprise:'企业运营', settings:'系统设置', help:'帮助中心' };

function esc(v) {
  return String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function zh(v) {
  const m = {
    active:'启用', enabled:'启用', running:'执行中', done:'已完成', success:'成功', sent:'已发送', paid:'已支付', draft:'草稿', failed:'失败', skipped:'已跳过', cancelled:'已取消', approved:'已通过', rejected:'已拒绝', requested:'已申请', assigned:'已分配', finished:'已结束', paused:'已暂停', offline:'离线', online:'在线', pending:'待处理', low:'低', medium:'中', high:'高', trial:'试用', enterprise:'企业版', professional:'专业版', owner:'所有者', admin:'管理员', manager:'经理', sales:'销售', service:'客服', finance:'财务', viewer:'只读', wechat:'个人微信', wecom:'企业微信', official:'公众号', manual:'手动', customer:'客户', lead:'线索', order:'订单', new:'陌生', understanding:'兴趣了解', recommended:'意向明确', high_intent:'高意向', enrolled:'已报名', won:'已成交', lost:'流失', claimed:'已认领', following:'跟进中', text:'文本', image:'图片', video:'视频', number:'数字', select:'下拉', date:'日期', textarea:'多行文本', 'customer.created':'新客户创建', 'customer.stage_changed':'客户阶段变化', 'order.paid':'订单支付', 'lead.assigned':'线索分配', 'followup.overdue':'跟进超时', id:'编号', url:'地址', type:'类型', name:'名称', status:'状态', role:'角色', owner:'负责人', channel:'渠道', customer:'客户', product:'产品', amount:'金额', time:'时间', title:'标题', content:'内容', note:'备注', link:'链接', order_id:'订单号', session_id:'会话ID', app_id:'应用ID', appid:'应用ID', callback_url:'回调地址', plan:'套餐', seats:'席位', expires_at:'到期时间', source:'来源', stage:'阶段', risk_level:'风险等级', expected_value:'预期金额', total_score:'总分', conversion:'转化', revenue:'收入', leads:'线索数', budget:'预算', frequency:'频次', recency:'最近购买', monetary:'金额', events:'事件', permissions:'权限', member:'成员', username:'用户名', password:'密码', company_name:'企业名称', tenant_name:'租户', key:'键', value:'值', webhooks:'回调通知', rfm:'客户价值', r:'最近购买', f:'购买频次', m:'购买金额', bi:'经营指标', created_at:'创建时间', updated_at:'更新时间', start_at:'开始时间', end_at:'结束时间' }, k = String(v == null ? '' : v).toLowerCase(); return m[k] || String(v == null ? '' : v);
}

function showError(msg) {
  const bar = $('appError');
  if (bar) { bar.textContent = msg; bar.classList.remove('hidden'); }
}

async function init() {
  try {
    auth = await api.getAuth();
    if (auth && auth.loggedIn) { showApp(); } else { showLogin(); }
  } catch (e) { showError('初始化失败：' + (e.message || e)); showLogin(); }
}

window.addEventListener('error', (e) => showError('界面错误：' + (e.message || e)));

function showLogin() {
  $('loginView').classList.remove('hidden');
  $('appView').classList.add('hidden');
}

function showApp() {
  $('loginView').classList.add('hidden');
  $('appView').classList.remove('hidden');
  $('userBadge').textContent = '已登录 ' + (auth.mask || '');
  loadDashboard();
  loadCustomers();
  loadBI();
  loadSalesFlow();
  loadFollowups();
  loadLeads();
  loadOpportunities();
  loadOrders();
  loadCampaigns();
  loadHandovers();
  loadKnowledge();
  loadCompliance();
  loadSettings();
  loadVision();
  loadRemaining();
  setInterval(() => { if (auth && auth.loggedIn) { loadDashboard(); loadBI(); loadVision(); } }, 12000);
}

function setMode(mode) {
  loginMode = mode;
  $('tabKey').classList.toggle('active', mode === 'key');
  $('tabAccount').classList.toggle('active', mode === 'account');
  $('keyFields').classList.toggle('hidden', mode !== 'key');
  $('accountFields').classList.toggle('hidden', mode !== 'account');
}

async function doLogin() {
  $('loginMsg').textContent = '验证中...';
  let r;
  if (loginMode === 'account') {
    r = await api.loginAccount($('loginUser').value.trim(), $('loginPass').value);
  } else {
    r = await api.login($('loginKey').value.trim());
  }
  if (r.ok) { auth = { loggedIn: true, mask: r.mask || (r.user && r.user.username) || '已登录' }; showApp(); }
  else { $('loginMsg').textContent = r.error || '登录失败'; }
}

async function doRegister() {
  const company = prompt('企业名称');
  const username = prompt('管理员用户名');
  const password = prompt('登录密码');
  if (!company || !username || !password) return;
  $('loginMsg').textContent = '开通中...';
  const r = await api.request('/api/v1/auth/register', 'POST', { company_name: company, username, password, name: username });
  if (r.ok && r.data && r.data.token) {
    const lr = await api.loginAccount(username, password);
    if (lr.ok) { auth = { loggedIn: true, mask: username }; showApp(); } else { $('loginMsg').textContent = lr.error || '登录失败'; }
  } else {
    $('loginMsg').textContent = (r.data && (r.data.error || r.data.detail)) || '注册失败';
  }
}

async function doLogout() {
  await api.logout();
  auth = null;
  visionRunning = false;
  location.reload();
}

document.querySelectorAll('nav a').forEach(a => a.addEventListener('click', () => {
  document.querySelectorAll('nav a').forEach(x => x.classList.remove('active'));
  a.classList.add('active');
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const el = document.getElementById(a.dataset.view);
  if (el) el.classList.add('active');
  const t = document.getElementById('pageTitle');
  if (t) t.textContent = MODULE_TITLES[a.dataset.view] || a.textContent;
}));

async function apiGet(path) {
  const r = await api.request(path, 'GET');
  return r.ok ? r.data : null;
}

async function loadDashboard() {
  try {
    const customers = await apiGet('/api/v1/customers');
    const leads = await apiGet('/api/v1/leads/stats');
    const orders = await apiGet('/api/v1/orders/stats');
    const followups = await apiGet('/api/v1/followups/stats');
    const list = toList(customers);
    $('dashKpis').innerHTML =
      kpi('客户总数', list.length) +
      kpi('线索', leads ? (leads.total || 0) : 0) +
      kpi('订单', orders ? (orders.total || 0) : 0) +
      kpi('待跟进', followups ? (followups.pending || 0) : 0);
    $('dashAlerts').innerHTML = '<span class="muted">当前无告警（后续接入监控中心）</span>';
  } catch (e) { showError('经营总览加载失败：' + (e.message || e)); }
}

function kpi(label, value) {
  return `<div class="kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`;
}

async function loadCustomers() {
  const data = await apiGet('/api/v1/customers');
  const list = toList(data);
  const body = $('customerTable').querySelector('tbody');
  if (!list.length) { body.innerHTML = '<tr><td colspan="6" class="empty">暂无客户</td></tr>'; return; }
  body.innerHTML = list.slice(0, 200).map(c => `
    <tr><td>${esc(c.id)}</td><td>${esc(c.nickname || c.name || '-')}</td><td>${esc(c.stage || '-')}</td><td>${esc(c.intent_level || '-')}</td><td>${esc(c.source || '-')}</td><td>${esc(c.updated_at || '-')}</td></tr>`).join('');
}

function fmtMoney(v) { return '¥' + Number(v || 0).toLocaleString('zh-CN'); }

async function loadBI() {
  try {
    const overview = await apiGet('/api/v1/bi/overview?days=7');
    const k = (overview && overview.kpis) || {};
    $('biKpis').innerHTML = kpi('客户总数', k.customers_total ?? 0) + kpi('新客户', k.customers_new ?? 0) + kpi('线索', k.leads_total ?? 0) + kpi('成交', k.won ?? 0) + kpi('订单', k.orders ?? 0) + kpi('收入', fmtMoney(k.revenue));
    const funnel = await apiGet('/api/v1/bi/funnel?days=30');
    $('biFunnel').innerHTML = table(['阶段','客户数','总转化','环比'], (funnel && funnel.steps || []).map(s => [s.label, s.count, s.rate_from_top + '%', s.rate_from_prev + '%']));
    const roi = await apiGet('/api/v1/bi/roi?days=30');
    const roiRows = ((roi && roi.channels) || []).map(r => [r.channel, r.leads, r.conversion + '%', fmtMoney(r.revenue), r.roi == null ? '-' : r.roi]);
    $('biRoi').innerHTML = table(['渠道','线索','转化','收入','ROI'], roiRows);
    const trends = await apiGet('/api/v1/bi/trends?days=14');
    $('biTrends').innerHTML = table(['日期','客户','线索','订单','收入','消息'], ((trends && trends.rows) || []).slice(-14).map(r => [r.date, r.customers, r.leads, r.orders, fmtMoney(r.revenue), r.messages]));
    const team = await apiGet('/api/v1/bi/team?days=30');
    $('biTeam').innerHTML = table(['销售','线索','成交','转化','收入'], ((team && team.items) || []).map(t => [t.owner, t.leads, t.won, t.conversion + '%', fmtMoney(t.revenue)]));
  } catch (e) { showError('数据智能加载失败：' + (e.message || e)); }
}

async function loadSalesFlow() {
  try {
    const overview = await apiGet('/api/v1/sales-flow/overview');
    const wf = (overview && overview.workflow) || {};
    const ds = (overview && overview.dispatch) || {};
    const pr = (overview && overview.prediction) || {};
    $('sfKpis').innerHTML = kpi('工作流', wf.workflows ?? 0) + kpi('启用', wf.enabled ?? 0) + kpi('成功', wf.done ?? 0) + kpi('失败', wf.failed ?? 0) + kpi('线索', ds.total ?? 0) + kpi('待分配', ds.unassigned ?? 0) + kpi('预期收入', fmtMoney(pr.total_expected)) + kpi('流失风险', pr.high_churn_risk ?? 0);
    const workflows = await apiGet('/api/v1/sales-flow/workflows');
    const wfList = toList(workflows);
    $('sfWorkflows').innerHTML = table(['名称','触发','状态','节点'], wfList.map(w => [w.name, w.trigger, w.enabled ? '启用' : '停用', (w.nodes || []).map(n => n.label || n.type).join(' → ')]));
    const executions = await apiGet('/api/v1/sales-flow/executions');
    $('sfExecutions').innerHTML = table(['编号','状态','开始','结束'], toList(executions).slice(0, 20).map(e => ['#' + e.id, e.status, e.started_at || '-', e.finished_at || '-']));
    const predictions = await apiGet('/api/v1/sales-flow/predictions');
    $('sfPredictions').innerHTML = table(['类型','客户','阶段','赢单','流失','预期'], toList(predictions).slice(0, 15).map(p => [p.kind, p.nickname || p.id, p.stage, Math.round((p.win_probability || 0) * 100) + '%', Math.round((p.churn_risk || 0) * 100) + '%', fmtMoney(p.expected_value)]));
  } catch (e) { showError('销售流程加载失败：' + (e.message || e)); }
}

async function loadFollowups() {
  try {
    const stats = await apiGet('/api/v1/followups/stats');
    $('fuKpis').innerHTML = kpi('待发送', (stats && stats.pending) ?? 0) + kpi('已发送', (stats && stats.sent) ?? 0) + kpi('任务总数', (stats && stats.total) ?? 0);
    const tasks = await apiGet('/api/v1/followups/tasks?limit=100');
    $('fuTasks').innerHTML = table(['节点','客户ID','渠道','到期时间','状态','内容'], toList(tasks).map(t => [t.node_label, t.session_id, t.channel || '-', t.due_at || '-', t.status, t.content || '']));
  } catch (e) { showError('自动跟进加载失败：' + (e.message || e)); }
}

function toList(data) {
  if (Array.isArray(data)) return data;
  if (!data) return [];
  return data.items || data.list || data.records || data.tasks || data.orders || data.customers || data.leads || data.opportunities || data.quotes || data.contracts || data.approvals || data.receivables || data.invoices || data.plans || data.templates || data.executions || data.tickets || data.reports || data.campaigns || data.rules || data.events || data.appointments || data.coupons || data.payment_links || data.products || data.objections || data.scripts || data.scores || data.fields || data.roles || data.members || data.files || data.predictions || data.sessions || data.handovers || data.consents || data.requests || [];
}

async function loadLeads() {
  try {
    const stats = await apiGet('/api/v1/leads/stats');
    const data = await apiGet('/api/v1/leads');
    const list = toList(data);
    $('leadsKpis').innerHTML = kpi('线索总数', (stats && stats.total) ?? list.length) + kpi('待认领', (stats && stats.pending) ?? 0) + kpi('成交', (stats && stats.won) ?? 0);
    $('leadsTable').innerHTML = table(['编号','姓名','联系方式','来源','意向','状态','归属','更新时间'], list.map(l => [l.id, l.name || l.nickname || '-', l.phone || l.wechat_id || l.unionid || '-', l.source || '-', l.intent_level || '-', l.status || '-', l.owner || '-', l.updated_at || '-']));
  } catch (e) { showError('线索加载失败：' + (e.message || e)); }
}

async function loadOpportunities() {
  try {
    const stats = await apiGet('/api/v1/opportunities/stats');
    const data = await apiGet('/api/v1/opportunities');
    const list = toList(data);
    $('oppKpis').innerHTML = kpi('商机总数', (stats && stats.total) ?? list.length) + kpi('管道金额', fmtMoney((stats && stats.pipeline))) + kpi('已赢单', fmtMoney((stats && stats.won_amount)));
    $('oppTable').innerHTML = table(['编号','商机','客户','产品','金额','阶段','赢率','负责人','风险','更新'], list.map(o => [o.id, o.name || '-', o.session_id || '-', o.product_name || '-', fmtMoney(o.amount), o.stage_label || o.stage || '-', (o.win_rate || 0) + '%', o.owner || '-', o.risk_level || 'low', o.updated_at || '-']));
  } catch (e) { showError('商机加载失败：' + (e.message || e)); }
}

async function loadOrders() {
  try {
    const stats = await apiGet('/api/v1/orders/stats');
    const data = await apiGet('/api/v1/orders');
    const list = toList(data);
    $('orderKpis').innerHTML = kpi('订单总数', (stats && stats.total_orders) ?? list.length) + kpi('已支付', (stats && stats.paid_orders) ?? 0) + kpi('已支付金额', fmtMoney((stats && stats.paid_amount))) + kpi('售后', (stats && stats.after_sales) ?? 0);
    $('orderTable').innerHTML = table(['订单号','客户','产品','金额','状态','创建时间'], list.map(o => [o.order_no || o.id, o.customer_name || o.session_id || '-', o.product_name || '-', fmtMoney(o.amount), o.status || '-', o.created_at || '-']));
  } catch (e) { showError('订单加载失败：' + (e.message || e)); }
}

async function loadCampaigns() {
  try {
    const data = await apiGet('/api/v1/campaigns');
    const list = toList(data);
    $('campKpis').innerHTML = kpi('活动总数', list.length);
    $('campTable').innerHTML = table(['编号','活动','渠道','预算','状态'], list.map(c => [c.id, c.name || '-', c.channel || '-', fmtMoney(c.budget), c.status || '-']));
  } catch (e) { showError('营销加载失败：' + (e.message || e)); }
}

async function loadHandovers() {
  try {
    const stats = await apiGet('/api/v1/handovers/stats');
    const data = await apiGet('/api/v1/handovers');
    const list = toList(data);
    $('handoverKpis').innerHTML = kpi('请求总数', (stats && stats.total) ?? list.length) + kpi('待处理', ((stats && stats.by_status) || {}).requested ?? 0) + kpi('已分配', ((stats && stats.by_status) || {}).assigned ?? 0);
    $('handoverTable').innerHTML = table(['编号','客户','来源','原因','状态','负责人','时间'], list.map(h => [h.id, h.session_id || '-', h.source || '-', h.reason || '-', h.status || '-', h.owner || '-', h.created_at || '-']));
  } catch (e) { showError('转人工加载失败：' + (e.message || e)); }
}

async function loadKnowledge() {
  try {
    const stats = await apiGet('/api/v1/knowledge/stats');
    const data = await apiGet('/api/v1/knowledge/files');
    const list = toList(data);
    $('knowledgeKpis').innerHTML = kpi('文件数', (stats && stats.source_files) ?? list.length) + kpi('向量数', (stats && stats.vector_count) ?? 0);
    $('knowledgeTable').innerHTML = table(['文件名','大小','更新时间'], list.map(f => [f.name || '-', f.size || '-', f.modified ? new Date(f.modified * 1000).toLocaleString('zh-CN') : '-']));
  } catch (e) { showError('知识库加载失败：' + (e.message || e)); }
}

async function loadCompliance() {
  try {
    const consents = await apiGet('/api/v1/compliance/consents?session_id=');
    const requests = await apiGet('/api/v1/compliance/deletion-requests');
    $('consentTable').innerHTML = table(['客户','来源','内容','状态','时间'], toList(consents).map(c => [c.session_id, c.source, c.content, c.status, c.created_at]));
    $('deletionTable').innerHTML = table(['编号','客户','申请人','原因','状态'], toList(requests).map(r => [r.id, r.session_id, r.applicant || '-', r.reason || '-', r.status || '-']));
  } catch (e) { showError('合规加载失败：' + (e.message || e)); }
}

async function loadSettings() {
  try {
    const h = await apiGet('/health');
    const lic = await apiGet('/api/v1/license/status');
    $('settingsInfo').innerHTML = table(['项目','值'], [['中台地址','http://127.0.0.1:5000'], ['服务状态', (h && h.status) || '-'], ['数据库', (h && h.database && h.database.status) || '-'], ['登录账号', auth.mask || '-'], ['角色', (lic && lic.role) || '超级管理员'], ['套餐', (lic && lic.plan) || '企业试用版'], ['租户', (lic && lic.tenant_name) || '超级管理员'], ['到期时间', (lic && lic.expires_at) || '永久']]);
  } catch (e) { showError('系统设置加载失败：' + (e.message || e)); }
}

async function loadGeneric(id, specs) {
  const out = $(id);
  if (!out) return;
  out.innerHTML = '';
  for (const spec of specs) {
    try {
      const data = await apiGet(spec[1]);
      out.innerHTML += '<h3>' + esc(spec[0]) + '</h3>' + table(spec[2].map(c => c[0]), toList(data).map(r => spec[2].map(c => typeof c[1] === 'function' ? c[1](r) : (r[c[1]] ?? '-'))));
    } catch (e) { showError(spec[0] + '加载失败：' + (e.message || e)); }
  }
}

function renderJson(id, label, data) {
  const out = $(id);
  if (!out) return;
  out.innerHTML += '<h3>' + esc(label) + '</h3><pre class="log">' + esc(JSON.stringify(data, null, 2)) + '</pre>';
}

function renderObjectTable(id, label, obj) {
  const out = $(id);
  if (!out) return;
  out.innerHTML += '<h3>' + esc(label) + '</h3>' + table(['字段','值'], Object.entries(obj || {}).map(([k,v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v ?? '-')]));
}

function loadRemaining() {
  loadPortraits(); loadCpq(); loadFinance(); loadSop(); loadTickets(); loadQuality(); loadNurture();
  loadEngagement(); loadAmmo(); loadWinning(); loadFeedback(); loadOfficial(); loadWechat();
  loadAiops(); loadOptimization(); loadCommercial(); loadEnterpriseLevel(); loadPlatform(); loadEnterprise();
}

async function loadPortraits() { await loadGeneric('portraitsOut', [['客户档案','/api/v1/customers',[['ID', r=>r.id],['客户', r=>r.nickname||r.name||'-'],['阶段', r=>r.stage||'-'],['意向', r=>r.intent_level||'-'],['来源', r=>r.source||'-'],['更新时间', r=>r.updated_at||'-']]]]); }
async function loadCpq() { await loadGeneric('cpqOut', [['报价','/api/v1/quotes',[['ID', r=>r.id],['客户', r=>r.customer||r.session_id||'-'],['产品', r=>r.product_name||'-'],['金额', r=>fmtMoney(r.amount)],['状态', r=>r.status||'-']]], ['合同','/api/v1/contracts',[['ID', r=>r.id],['客户', r=>r.customer||r.session_id||'-'],['金额', r=>fmtMoney(r.amount)],['状态', r=>r.status||'-']]], ['审批','/api/v1/approvals',[['ID', r=>r.id],['类型', r=>r.biz_type||'-'],['审批人', r=>r.approver||'-'],['状态', r=>r.status||'-']]]]); }
async function loadFinance() { await loadGeneric('financeOut', [['应收款','/api/v1/receivables',[['ID', r=>r.id],['客户', r=>r.customer||r.session_id||'-'],['金额', r=>fmtMoney(r.amount)],['状态', r=>r.status||'-']]], ['发票','/api/v1/invoices',[['ID', r=>r.id],['订单', r=>r.order_id||'-'],['金额', r=>fmtMoney(r.amount)],['状态', r=>r.status||'-']]], ['回款计划','/api/v1/payment-plans',[['ID', r=>r.id],['客户', r=>r.customer||r.session_id||'-'],['金额', r=>fmtMoney(r.amount)],['到期', r=>r.due_at||'-']]]]); }
async function loadSop() { await loadGeneric('sopOut', [['SOP模板','/api/v1/sop/templates',[['ID', r=>r.id],['名称', r=>r.name||'-'],['阶段', r=>r.stage||'-'],['步骤', r=>(r.steps||[]).length],['状态', r=>r.active?'启用':'停用']]], ['执行记录','/api/v1/sop/executions',[['ID', r=>r.id],['模板', r=>r.template_id||'-'],['步骤', r=>r.step_name||'-'],['客户', r=>r.session_id||'-'],['状态', r=>r.status||'-']]]]); }
async function loadTickets() { await loadGeneric('ticketsOut', [['工单','/api/v1/tickets',[['ID', r=>r.id],['客户', r=>r.customer||r.session_id||'-'],['标题', r=>r.title||r.subject||'-'],['状态', r=>r.status||'-'],['创建时间', r=>r.created_at||'-']]]]); }
async function loadQuality() { await loadGeneric('qualityOut', [['质检报告','/api/v1/quality/reports',[['ID', r=>r.id],['会话', r=>r.session_id||'-'],['分数', r=>r.score||r.total_score||'-'],['状态', r=>r.status||'-']]]]); }
async function loadNurture() { await loadGeneric('nurtureOut', [['培育活动','/api/v1/nurture/campaigns',[['ID', r=>r.id],['名称', r=>r.name||'-'],['状态', r=>r.status||'-']]], ['规则','/api/v1/nurture/rules',[['ID', r=>r.id],['名称', r=>r.name||'-'],['触发', r=>r.trigger||'-']]], ['事件','/api/v1/nurture/events',[['ID', r=>r.id],['会话', r=>r.session_id||'-'],['状态', r=>r.status||'-']]]]); }
async function loadEngagement() { await loadGeneric('engagementOut', [['预约','/api/v1/appointments',[['ID', r=>r.id],['客户', r=>r.session_id||'-'],['标题', r=>r.title||'-'],['状态', r=>r.status||'-']]], ['优惠券','/api/v1/coupons',[['ID', r=>r.id],['名称', r=>r.name||'-'],['状态', r=>r.status||'-']]], ['支付链接','/api/v1/payment-links',[['ID', r=>r.id],['标题', r=>r.title||'-'],['金额', r=>fmtMoney(r.amount)],['状态', r=>r.status||'-']]]]); }
async function loadAmmo() { await loadGeneric('ammoOut', [['产品','/api/v1/ammo/products',[['ID', r=>r.id],['产品', r=>r.name||r.product||'-'],['价格', r=>fmtMoney(r.price)]]], ['异议','/api/v1/ammo/objections',[['ID', r=>r.id],['场景', r=>r.scene||r.obj_scene||'-'],['回复', r=>r.reply||r.standard_reply||'-']]], ['话术','/api/v1/ammo/scripts',[['ID', r=>r.id],['场景', r=>r.scene||'-'],['话术', r=>r.script||r.content||'-']]]]); }
async function loadWinning() { await loadGeneric('winningOut', [['差异点','/api/v1/winning/differentiators',[['ID', r=>r.id],['产品', r=>r.product||'-'],['差异点', r=>r.differentiator||'-']]], ['证据','/api/v1/winning/evidence',[['ID', r=>r.id],['标题', r=>r.title||'-'],['类型', r=>r.evidence_type||'-']]], ['工具','/api/v1/winning/tools',[['ID', r=>r.id],['名称', r=>r.name||'-'],['类型', r=>r.tool_type||'-']]]]); }
async function loadFeedback() { await loadGeneric('feedbackOut', [['反馈','/api/v1/feedback',[['ID', r=>r.id],['会话', r=>r.session_id||'-'],['消息', r=>r.message||r.content||'-'],['状态', r=>r.status||'-']]]]); }
async function loadOfficial() {
  try {
    const overview = await apiGet('/api/v1/channels/overview');
    const menu = await apiGet('/api/v1/official/menu');
    const o = (overview || {}).official || {};
    const out = $('officialOut'); out.innerHTML = '';
    out.innerHTML += '<h3>公众号状态</h3>' + table(['项目','状态'], [['AppID', o.app_id || '-'], ['是否配置', o.configured ? '已配置' : '未配置'], ['回调地址', o.callback_url || '-']]);
    const menuData = (menu || {}).menu || menu;
    if (Array.isArray(menuData)) {
      out.innerHTML += '<h3>公众号菜单</h3>' + table(['名称','类型','状态'], menuData.map(m => [m.name || m.label || '-', m.type || '-', m.status || '-']));
    } else {
      renderObjectTable('officialOut', '公众号菜单', menuData || {});
    }
  } catch (e) { showError('公众号加载失败：' + (e.message || e)); }
}
async function loadWechat() {
  try {
    const overview = await apiGet('/api/v1/channels/overview');
    const cfg = await apiGet('/api/v1/channels/wechat/config');
    const w = (overview || {}).wechat || {};
    const hb = w.heartbeat || {};
    const out = $('wechatOut'); out.innerHTML = '';
    out.innerHTML += '<h3>个人微信状态</h3>' + table(['项目','状态'], [['登录状态', hb.online ? '在线' : '离线'], ['最后心跳', hb.last_seen || '-']]);
    if (cfg && cfg.error) {
      out.innerHTML += '<h3>个人微信配置</h3><div class="empty">当前未配置个人微信机器人</div>';
    } else {
      renderObjectTable('wechatOut', '个人微信配置', cfg || {});
    }
  } catch (e) { showError('个人微信加载失败：' + (e.message || e)); }
}
async function loadAiops() { try { const reports = await apiGet('/api/v1/aiops/reports'); const out = $('aiopsOut'); out.innerHTML = table(['ID','标题','状态','时间'], toList(reports).map(r => [r.id, r.title||r.name||'-', r.status||'-', r.created_at||'-'])); } catch (e) { showError('AI经营加载失败：' + (e.message||e)); } }
async function loadOptimization() {
  try {
    const scores = await apiGet('/api/v1/optimize/scores?limit=20');
    const stats = await apiGet('/api/v1/optimize/scores/stats?days=7');
    renderObjectTable('optimizationOut','评分统计', stats || {});
    const out = $('optimizationOut');
    out.innerHTML += '<h3>评分明细</h3>' + table(['会话','产品','总分','时间'], toList(scores).map(s => [s.session_id||'-', s.product||'-', s.total_score||'-', s.created_at||'-']));
  } catch (e) { showError('优化中心加载失败：' + (e.message||e)); }
}
async function loadCommercial() { await loadGeneric('commercialOut', [['渠道会话','/api/v1/commercial/channel/sessions',[['ID', r=>r.id],['客户', r=>r.session_id||r.customer||'-'],['渠道', r=>r.channel||'-'],['状态', r=>r.status||'-']]], ['路由规则','/api/v1/commercial/router/rules',[['ID', r=>r.id],['名称', r=>r.name||'-'],['状态', r=>r.status||'-']]], ['RFM','/api/v1/commercial/cdp/rfm',[['客户', r=>r.session_id||r.customer||'-'],['R', r=>r.recency||'-'],['F', r=>r.frequency||'-'],['M', r=>r.monetary||'-']]], ['标签','/api/v1/commercial/cdp/tags',[['客户', r=>r.session_id||r.customer||'-'],['标签', r=>r.tags||r.tag||'-']]], ['旅程','/api/v1/commercial/marketing/journeys',[['ID', r=>r.id],['名称', r=>r.name||'-'],['状态', r=>r.status||'-']]]]); }
async function loadEnterpriseLevel() {
  try {
    const [tenants, billing, funnel, roi, forecast, integrations, webhooks] = await Promise.all([apiGet('/api/v1/tenants'), apiGet('/api/v1/billing/health'), apiGet('/api/v1/analytics/funnel?days=30'), apiGet('/api/v1/analytics/channel-roi?days=30'), apiGet('/api/v1/forecast/list?limit=10'), apiGet('/api/v1/integrations/status'), apiGet('/api/v1/webhooks')]);
    const out = $('enterpriseLevelOut'); out.innerHTML = '';
    out.innerHTML += '<h3>租户列表</h3>' + table(['ID','企业','套餐','状态','席位','到期'], toList(tenants).map(t => [t.id, t.name||'-', t.plan||'-', t.status||'-', t.seats||0, t.expires_at||'-']));
    renderObjectTable('enterpriseLevelOut','计费健康', billing || {});
    out.innerHTML += '<h3>转化漏斗</h3>' + table(['阶段','客户数','转化率'], ((funnel||{}).steps||toList(funnel)).map(f => [f.label||'-', f.count||0, (f.rate||f.rate_from_top||0)+'%']));
    out.innerHTML += '<h3>渠道ROI</h3>' + table(['渠道','线索','收入','ROI'], ((roi||{}).items||(roi||{}).channels||toList(roi)).map(r => [r.channel||r.name||'-', r.leads||0, fmtMoney(r.revenue), r.roi ?? '-']));
    out.innerHTML += '<h3>预测</h3>' + table(['客户','阶段','概率','预期'], toList(forecast).map(f => [f.nickname||f.id||f.session_id||'-', f.stage||'-', Math.round((f.win_probability||0)*100)+'%', fmtMoney(f.expected_value)]));
    renderObjectTable('enterpriseLevelOut','集成状态', integrations || {});
    out.innerHTML += '<h3>Webhooks</h3>' + table(['ID','地址','事件','启用'], toList(webhooks).map(w => [w.id, w.url||'-', (w.events||[]).join(','), w.enabled ? '启用':'停用']));
  } catch (e) { showError('企业级驾驶舱加载失败：' + (e.message||e)); }
}
async function loadPlatform() {
  try {
    const [fields, roles, team, metrics] = await Promise.all([apiGet('/api/v1/custom-fields'), apiGet('/api/v1/roles'), apiGet('/api/v1/team'), apiGet('/api/v1/bi/metrics')]);
    const out = $('platformOut'); out.innerHTML = '';
    out.innerHTML += '<h3>自定义字段</h3>' + table(['ID','名称','类型','启用'], toList(fields).map(f => [f.id, f.name||f.label||'-', f.type||'-', f.enabled?'启用':'停用']));
    out.innerHTML += '<h3>角色</h3>' + table(['ID','名称','权限'], toList(roles).map(r => [r.id, r.name||r.role||'-', (r.permissions||[]).join(',')||'-']));
    out.innerHTML += '<h3>团队</h3>' + table(['成员','角色','状态'], toList(team).map(t => [t.name||t.username||t.member||'-', t.role||'-', t.status||'-']));
    renderObjectTable('platformOut','经营指标', metrics || {});
  } catch (e) { showError('平台设置加载失败：' + (e.message||e)); }
}
async function loadEnterprise() { try { const [leaderboard, targets, rules, commissions, approvals, sla, tiers, users] = await Promise.all([apiGet('/api/v1/team/leaderboard'), apiGet('/api/v1/team/targets'), apiGet('/api/v1/team/commission-rules'), apiGet('/api/v1/team/commissions'), apiGet('/api/v1/approval/rules'), apiGet('/api/v1/sla/policies'), apiGet('/api/v1/customer-tiers'), apiGet('/api/v1/accounts/users')]); const out = $('enterpriseOut'); out.innerHTML = ''; out.innerHTML += '<h3>业绩排行</h3>' + table(['成员','订单','金额'], toList(leaderboard).map(r=>[r.member||r.owner||'-', r.orders||0, fmtMoney(r.amount)])); out.innerHTML += '<h3>目标</h3>' + table(['成员','周期','类型','金额'], toList(targets).map(r=>[r.member||'-', r.period||'-', r.target_type||'-', fmtMoney(r.amount)])); out.innerHTML += '<h3>成员</h3>' + table(['ID','用户名','姓名','角色','状态'], toList(users).map(r=>[r.id, r.username, r.name, r.role, r.status])); } catch (e) { showError('企业运营加载失败：' + (e.message||e)); } }

function table(headers, rows) {
  if (!rows || !rows.length) return '<div class="empty">暂无数据</div>';
  return `<table><thead><tr>${headers.map(h => `<th>${esc(zh(h))}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${esc(zh(c))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

async function loadVision() {
  const s = await apiGet('/api/v1/vision/status');
  if (!s) { $('visionStatus').textContent = '无法连接'; return; }
  $('vSends').textContent = s.sends_today ?? 0;
  $('vLimit').textContent = s.daily_limit ?? 300;
  $('vPending').textContent = s.tasks_pending ?? 0;
  const on = s.enabled && !s.paused;
  $('visionDot').className = 'dot ' + (on ? 'on' : 'off');
  $('visionStatus').textContent = on ? '服务端已启用' : (s.paused ? '服务端已暂停' : '服务端未启用');
  const tasks = await apiGet('/api/v1/vision/tasks?limit=50');
  renderTasks(toList(tasks));
  const audit = await apiGet('/api/v1/vision/audit?limit=50');
  renderAudit(toList(audit));
  const logs = await api.getVisionLogs();
  $('visionLogs').textContent = (logs || []).join('\n') || '暂无日志';
}

function renderTasks(tasks) {
  const body = $('taskTable').querySelector('tbody');
  if (!tasks.length) { body.innerHTML = '<tr><td colspan="5" class="empty">暂无任务</td></tr>'; return; }
  body.innerHTML = tasks.map(t => `<tr><td>${esc(t.contact)}</td><td>${esc(t.content)}</td><td>${esc(t.status)}</td><td>${esc(t.created_at)}</td><td>${esc(t.note || '')}</td></tr>`).join('');
}

function renderAudit(rows) {
  const body = $('auditTable').querySelector('tbody');
  if (!rows.length) { body.innerHTML = '<tr><td colspan="3" class="empty">暂无数据</td></tr>'; return; }
  body.innerHTML = rows.map(r => `<tr><td>${esc(r.time)}</td><td>${esc(r.action)}</td><td>${esc(JSON.stringify(r.detail || {}))}</td></tr>`).join('');
}

async function toggleVision() {
  if (!visionRunning) {
    const r = await api.startVision();
    visionRunning = r.ok;
    $('visionStatus').textContent = r.ok ? '本地执行器运行中' : (r.error || '启动失败');
    $('visionToggle').textContent = '停止';
  } else {
    await api.stopVision();
    visionRunning = false;
    $('visionStatus').textContent = '已停止';
    $('visionToggle').textContent = '启用';
  }
}

async function createTask() {
  const contact = $('taskContact').value.trim();
  const content = $('taskContent').value.trim();
  const mode = $('taskMode').value;
  if (!contact || !content) return;
  const r = await api.request('/api/v1/vision/tasks', 'POST', { mode, contact, content });
  if (r.ok) { $('taskContact').value = ''; $('taskContent').value = ''; loadVision(); }
}

init();

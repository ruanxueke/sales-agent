/* Solda 模式升级模块：话术弹药库、赢单引擎、预约优惠、优化中心、合规设置 */

(function () {
  const main = document.querySelector("main");
  if (main && !document.getElementById("view-engagement")) {
    main.insertAdjacentHTML("beforeend", `
    <section id="view-engagement" class="view">
      <div class="kpis" id="engagement-kpis"></div>
      <div class="box"><h2>预约</h2><div class="toolbar"><input id="app-session" placeholder="客户ID"><input id="app-title" placeholder="预约标题"><input id="app-start" placeholder="开始时间"><input id="app-owner" placeholder="负责人"><button id="app-add" type="button" class="primary">创建预约</button></div><div id="app-table"></div></div>
      <div class="box"><h2>优惠券</h2><div class="toolbar"><input id="coupon-name" placeholder="券名"><select id="coupon-type"><option value="discount">折扣</option><option value="gift">赠品</option><option value="commitment">服务承诺</option></select><input id="coupon-value" placeholder="券值"><input id="coupon-days" type="number" placeholder="有效天数"><button id="coupon-add" type="button" class="primary">创建券</button><input id="coupon-session" placeholder="发放给客户ID"><button id="coupon-grant" type="button">发放</button></div><div id="coupon-table"></div><div id="user-coupon-table"></div></div>
      <div class="box"><h2>支付链接</h2><div class="toolbar"><input id="pl-order" type="number" placeholder="订单ID"><input id="pl-title" placeholder="标题"><input id="pl-amount" type="number" step="0.01" placeholder="金额"><input id="pl-link" placeholder="支付链接" style="flex:1"><button id="pl-add" type="button" class="primary">生成链接</button></div><div id="pl-table"></div></div>
    </section>
    <section id="view-optimization" class="view">
      <div class="kpis" id="optimization-kpis"></div>
      
      <div class="box">
        <h2>?? 对话质量评分</h2>
        <div class="toolbar">
          <select id="score-product"><option value="">全部产品</option><option value="ai_course">AI课程</option><option value="animation">动画</option></select>
          <input id="score-days" type="number" value="7" style="width:60px" placeholder="天数">
          <button id="score-refresh" type="button">刷新</button>
        </div>
        <div id="score-stats"></div>
      <div class="toolbar" style="margin-top:8px">
        <input id="summary-status" placeholder="会话摘要状态筛选"><button id="summary-search" type="button">查询摘要</button>
      </div>
        <div id="score-table"></div>
      </div>

      <div class="box">
        <h2>?? 提示词版本管理</h2>
        <div class="toolbar">
          <button id="prompt-list-refresh" type="button">刷新</button>
        </div>
        <div id="prompt-version-table"></div>
      </div>

      <div class="box">
        <h2>?? A/B 实验</h2>
        <div class="toolbar">
          <input id="exp-name" placeholder="实验名">
          <input id="exp-control" placeholder="对照组提示词" style="flex:1">
          <input id="exp-variant" placeholder="实验组提示词" style="flex:1">
          <select id="exp-kind"><option value="prompt">提示词</option><option value="script">话术</option><option value="flow">流程</option></select><button id="exp-add" type="button" class="primary">创建实验</button>
        </div>
        <div id="exp-table"></div>
        <div id="exp-results"></div>
      </div>

      <div class="box">
        <h2>?? 优化建议</h2>
        <div class="toolbar">
          <select id="sug-status"><option value="">全部</option><option value="pending">待处理</option><option value="approved">已批准</option><option value="rejected">已拒绝</option></select>
          <button id="sug-refresh" type="button">刷新</button>
          <button id="sug-generate" type="button" class="primary">生成建议</button>
        </div>
        <div id="sug-table"></div>
      </div>

      <div class="box">
        <h2>?? 周复盘</h2>
        <div class="toolbar">
          <textarea id="review-content" placeholder="本周复盘内容" style="flex:1;min-height:70px"></textarea>
          <button id="review-add" type="button" class="primary">生成复盘</button>
        </div>
        <div id="review-table"></div>
      </div>
    </section>
    <section id="view-compliance" class="view">
      <div class="kpis" id="compliance-kpis"></div>
      <div class="box"><h2>合规与转人工规则</h2><div class="toolbar"><select id="comp-type"><option value="handover">转人工</option><option value="stop">停止触达</option><option value="notify">通知</option></select><input id="comp-words" placeholder="触发词，用 | 分隔" style="flex:1"><select id="comp-action"><option value="handover">转人工</option><option value="stop">停止触达</option><option value="notify">通知</option></select><input id="comp-desc" placeholder="说明"><button id="comp-add" type="button" class="primary">添加规则</button></div><div id="comp-table"></div></div>
    </section>`);
  }
})();

/* ===== 话术弹药库 ===== */

/* ===== 通用组件：toast / loading / 分页 / 编辑删除 ===== */
window.__page = window.__page || {};
window.__pageRender = window.__pageRender || {};

function ensureToasts() {
  if (!document.getElementById("toast-wrap")) {
    const w = document.createElement("div");
    w.id = "toast-wrap"; w.className = "toast-wrap";
    document.body.appendChild(w);
  }
  if (!document.getElementById("loading-mask")) {
    const m = document.createElement("div");
    m.id = "loading-mask"; m.className = "loading-mask";
    m.innerHTML = '<div class="loading-dot"></div>';
    document.body.appendChild(m);
  }
}

function toast(msg, type) {
  ensureToasts();
  const wrap = document.getElementById("toast-wrap");
  const el = document.createElement("div");
  el.className = "toast " + (type || "ok");
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; setTimeout(() => el.remove(), 320); }, 2400);
}

function showLoading(show) {
  ensureToasts();
  document.getElementById("loading-mask").classList.toggle("show", !!show);
  if (show) {
    clearTimeout(window.__loadingTimer);
    window.__loadingTimer = setTimeout(() => {
      const el = document.getElementById("loading-mask");
      if (el) el.classList.remove("show");
    }, 12000);
  }
}

function pageSlice(key, arr, pageSize) {
  const total = (arr || []).length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  let page = Number(window.__page[key] || 1);
  if (page > pages) page = pages;
  if (page < 1) page = 1;
  window.__page[key] = page;
  const start = (page - 1) * pageSize;
  return { rows: (arr || []).slice(start, start + pageSize), page, pages, total, start, pageSize };
}

function pagerHTML(key, page, pages, total) {
  if (pages <= 1) return `<div class="pager"><span class="total">共 ${total} 条，第 1/1 页</span></div>`;
  let btns = `<button data-page-key="${key}" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>上一页</button>`;
  const startPage = Math.max(1, page - 2);
  const endPage = Math.min(pages, page + 2);
  for (let i = startPage; i <= endPage; i++) {
    btns += `<button data-page-key="${key}" data-page="${i}" class="${i === page ? "current" : ""}">${i}</button>`;
  }
  btns += `<button data-page-key="${key}" data-page="${page + 1}" ${page >= pages ? "disabled" : ""}>下一页</button>`;
  return `<div class="pager"><span class="total">共 ${total} 条，第 ${page}/${pages} 页</span>${btns}</div>`;
}

function registerPageRender(key, fn) {
  window.__pageRender[key] = fn;
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-page-key]");
  if (!btn || btn.disabled) return;
  const key = btn.dataset.pageKey;
  const page = Number(btn.dataset.page);
  window.__page[key] = page;
  const fn = window.__pageRender[key];
  if (fn) fn();
});

function registerDelete(key, url, reloadFn, confirmText) {
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(`button[data-del="${key}"]`);
    if (!btn) return;
    if (!confirm(confirmText || "确认删除？")) return;
    try {
      const res = await fetch(`${url}/${btn.dataset.id}`, { method: "DELETE", headers: apiHeaders() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "HTTP " + res.status);
      toast(data.deleted ? "删除成功" : "未找到记录", data.deleted ? "ok" : "warn");
      if (reloadFn) reloadFn();
    } catch (err) { showError("保存失败：" + err.message); }
  });
}

function registerEdit(key, url, fields, reloadFn) {
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(`button[data-edit="${key}"]`);
    if (!btn) return;
    const values = {};
    for (const f of fields) {
      const v = prompt(`请输入${f.label || f.key}：`, btn.dataset[f.key] || "");
      if (v === null) return;
      values[f.key] = v;
    }
    try {
      const res = await fetch(`${url}/${btn.dataset.id}`, {
        method: "PATCH", headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ fields: values }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "HTTP " + res.status);
      toast("保存成功", "ok");
      if (reloadFn) reloadFn();
    } catch (err) { showError("删除失败：" + err.message); }
  });
}

async function loadAmmo() {
  const [products, objections, competitors, scripts, cases] = await Promise.all([
    fetchJSON("http://127.0.0.1:5000/api/v1/ammo/products"),
    fetchJSON("http://127.0.0.1:5000/api/v1/ammo/objections"),
    fetchJSON("http://127.0.0.1:5000/api/v1/ammo/competitors"),
    fetchJSON("http://127.0.0.1:5000/api/v1/ammo/scripts"),
    fetchJSON("http://127.0.0.1:5000/api/v1/ammo/cases"),
  ]);
  state.ammo = {
    products: products.products || [], objections: objections.objections || [],
    competitors: competitors.competitors || [], scripts: scripts.scripts || [],
    cases: cases.cases || [],
  };
  renderAmmo();
}

function renderAmmo() {
  const a = state.ammo;
  $("ammo-kpis").innerHTML =
    kpi("产品知识", a.products.length) + kpi("异议应答", a.objections.length) +
    kpi("竞品应对", a.competitors.length) + kpi("跟进话术", a.scripts.length) +
    kpi("学习案例", a.cases.length);
  const pkRows = (pg = pageSlice("ammo-products", a.products, 20)).rows.map((p) => `<tr><td>${esc(p.product_name)}</td><td>${esc(p.target_customer || "暂无")}</td><td>${esc(p.selling_points || "暂无")}</td><td>${esc(p.price || "暂无")}</td><td>${esc(p.after_sales || "暂无")}</td><td><div class="lead-actions"><button data-edit="ammo-products" data-id="${p.id}">编辑</button><button data-del="ammo-products" data-id="${p.id}">删除</button></div></td></tr>`).join("");
  $("pk-table").innerHTML = `<table><thead><tr><th>产品</th><th>适用人群</th><th>卖点</th><th>价格</th><th>售后</th><th>操作</th></tr></thead><tbody>${pkRows || '<tr><td colspan="6" class="empty">暂无，位置已预留</td></tr>'}</tbody></table>` + pagerHTML("ammo-products", pg.page, pg.pages, pg.total)
  const objRows = (pg = pageSlice("ammo-objections", a.objections, 20)).rows.map((o) => `<tr><td>${esc(o.trigger_scene)}</td><td>${esc(o.standard_reply || "暂无")}</td><td>${esc(o.evidence || "暂无")}</td><td>${esc(o.next_step || "暂无")}</td><td><div class="lead-actions"><button data-edit="ammo-objections" data-id="${o.id}">编辑</button><button data-del="ammo-objections" data-id="${o.id}">删除</button></div></td></tr>`).join("");
  $("obj-table").innerHTML = `<table><thead><tr><th>异议场景</th><th>标准回复</th><th>证据</th><th>下一步</th><th>操作</th></tr></thead><tbody>${objRows || '<tr><td colspan="5" class="empty">暂无，位置已预留</td></tr>'}</tbody></table>` + pagerHTML("ammo-objections", pg.page, pg.pages, pg.total)
  const cpRows = (pg = pageSlice("ammo-competitors", a.competitors, 20)).rows.map((c) => `<tr><td>${esc(c.competitor)}</td><td>${esc(c.customer_saying || "暂无")}</td><td>${esc([c.differentiator_1, c.differentiator_2, c.differentiator_3].filter(Boolean).join("、") || "暂无")}</td><td>${esc(c.standard_reply || "暂无")}</td><td><div class="lead-actions"><button data-edit="ammo-competitors" data-id="${c.id}">编辑</button><button data-del="ammo-competitors" data-id="${c.id}">删除</button></div></td></tr>`).join("");
  $("cp-table").innerHTML = `<table><thead><tr><th>竞品</th><th>客户常见说法</th><th>差异点</th><th>标准回应</th><th>操作</th></tr></thead><tbody>${cpRows || '<tr><td colspan="5" class="empty">暂无，位置已预留</td></tr>'}</tbody></table>` + pagerHTML("ammo-competitors", pg.page, pg.pages, pg.total)
  const fsRows = (pg = pageSlice("ammo-scripts", a.scripts, 20)).rows.map((s) => `<tr><td>${esc(s.followup_scene || "暂无")}</td><td>${esc(s.script_example || "暂无")}</td><td>${esc(s.value_point || "暂无")}</td><td>${esc(s.next_goal || "暂无")}</td><td class="num">${s.delay_hours || "暂无"}h</td><td><div class="lead-actions"><button data-edit="ammo-scripts" data-id="${s.id}">编辑</button><button data-del="ammo-scripts" data-id="${s.id}">删除</button></div></td></tr>`).join("");
  $("fs-table").innerHTML = `<table><thead><tr><th>状态</th><th>话术示例</th><th>价值点</th><th>下一步</th><th class="num">延迟</th><th>操作</th></tr></thead><tbody>${fsRows || '<tr><td colspan="6" class="empty">暂无，位置已预留</td></tr>'}</tbody></table>` + pagerHTML("ammo-scripts", pg.page, pg.pages, pg.total)
  const caseRows = (pg = pageSlice("ammo-cases", a.cases, 20)).rows.map((c) => `<tr><td>${esc(c.title)}</td><td>${esc(zh(c.case_type))}</td><td>${esc((c.key_turns || "").slice(0, 60))}</td><td>${esc(c.tags || "暂无")}</td><td><div class="lead-actions"><button data-edit="ammo-cases" data-id="${c.id}">编辑</button><button data-del="ammo-cases" data-id="${c.id}">删除</button></div></td></tr>`).join("");
  $("case-table").innerHTML = `<table><thead><tr><th>案例</th><th>类型</th><th>关键过程</th><th>标签</th><th>操作</th></tr></thead><tbody>${caseRows || '<tr><td colspan="5" class="empty">还没有销售案例，投喂后这里会显示学习结果</td></tr>'}</tbody></table>` + pagerHTML("ammo-cases", pg.page, pg.pages, pg.total)
}

/* ===== 赢单引擎 ===== */
async function loadWinning() {
  const [differentiators, evidence, tools] = await Promise.all([
    fetchJSON("http://127.0.0.1:5000/api/v1/winning/differentiators"),
    fetchJSON("http://127.0.0.1:5000/api/v1/winning/evidence"),
    fetchJSON("http://127.0.0.1:5000/api/v1/winning/tools"),
  ]);
  state.winning = {
    differentiators: differentiators.items || [], evidence: evidence.items || [], tools: tools.items || [],
  };
  renderWinning();
}

function renderWinning() {
  const w = state.winning;
  $("winning-kpis").innerHTML =
    kpi("差异点", w.differentiators.length) + kpi("证据库", w.evidence.length) + kpi("关键时刻工具", w.tools.length);
  const dfRows = (pg = pageSlice("winning-df", w.differentiators, 20)).rows.map((d) => `<tr><td>${esc(d.product)}</td><td>${esc(d.differentiator)}</td><td>${esc(d.customer_concern || "暂无")}</td><td>${esc(d.evidence || "暂无")}</td><td><div class="lead-actions"><button data-edit="winning-df" data-id="${d.id}">编辑</button><button data-del="winning-df" data-id="${d.id}">删除</button></div></td></tr>`).join("");
  $("df-table").innerHTML = `<table><thead><tr><th>产品</th><th>差异点</th><th>对应客户在意项</th><th>证据</th><th>操作</th></tr></thead><tbody>${dfRows || '<tr><td colspan="5" class="empty">暂无，位置已预留</td></tr>'}</tbody></table>` + pagerHTML("winning-df", pg.page, pg.pages, pg.total)
  const evRows = (pg = pageSlice("winning-ev", w.evidence, 20)).rows.map((e) => `<tr><td>${esc(zh(e.evidence_type))}</td><td>${esc(e.title)}</td><td>${esc((e.content || "").slice(0, 60))}</td><td>${esc(e.scenario || "暂无")}</td><td><div class="lead-actions"><button data-edit="winning-ev" data-id="${e.id}">编辑</button><button data-del="winning-ev" data-id="${e.id}">删除</button></div></td></tr>`).join("");
  $("ev-table").innerHTML = `<table><thead><tr><th>类型</th><th>标题</th><th>内容</th><th>适用场景</th><th>操作</th></tr></thead><tbody>${evRows || '<tr><td colspan="5" class="empty">暂无，位置已预留</td></tr>'}</tbody></table>` + pagerHTML("winning-ev", pg.page, pg.pages, pg.total)
  const toolRows = (pg = pageSlice("winning-tools", w.tools, 20)).rows.map((t) => `<tr><td>${esc(zh(t.tool_type))}</td><td>${esc(t.name)}</td><td>${esc(t.description || "暂无")}</td><td>${esc(t.trigger_scene || "暂无")}</td><td><div class="lead-actions"><button data-edit="winning-tools" data-id="${t.id}">编辑</button><button data-del="winning-tools" data-id="${t.id}">删除</button></div></td></tr>`).join("");
  $("tool-table").innerHTML = `<table><thead><tr><th>类型</th><th>工具</th><th>说明</th><th>适用场景</th><th>操作</th></tr></thead><tbody>${toolRows || '<tr><td colspan="5" class="empty">暂无，位置已预留</td></tr>'}</tbody></table>` + pagerHTML("winning-tools", pg.page, pg.pages, pg.total)
}

/* ===== 预约优惠 ===== */
async function loadEngagement() {
  const [appointments, coupons, userCoupons, paymentLinks, stats] = await Promise.all([
    fetchJSON("http://127.0.0.1:5000/api/v1/appointments"),
    fetchJSON("http://127.0.0.1:5000/api/v1/coupons"),
    fetchJSON("http://127.0.0.1:5000/api/v1/user-coupons"),
    fetchJSON("http://127.0.0.1:5000/api/v1/payment-links"),
    fetchJSON("http://127.0.0.1:5000/api/v1/engagement/stats"),
  ]);
  state.engagement = {
    appointments: appointments.appointments || [], coupons: coupons.coupons || [],
    userCoupons: userCoupons.user_coupons || [], paymentLinks: paymentLinks.payment_links || [], stats,
  };
  renderEngagement();
}

function renderEngagement() {
  const e = state.engagement;
  const s = e.stats || {};
  $("engagement-kpis").innerHTML =
    kpi("预约", s.appointments) + kpi("待确认", s.appointments_pending) +
    kpi("优惠券", s.coupons) + kpi("已发放", s.coupons_issued) + kpi("支付链接", s.payment_links);
  const appRows = (pg = pageSlice("engagement-app", e.appointments, 20)).rows.map((a) => `<tr><td>${esc(displayId(a.session_id))}</td><td>${esc(a.title || "暂无")}</td><td>${esc(zh(a.appointment_type || "暂无"))}</td><td>${esc((a.start_at || "").slice(0, 16))}</td><td>${badge(a.status)}</td><td>${esc(a.owner || "暂无")}</td><td><div class="lead-actions"><button data-edit="engagement-app" data-id="${a.id}">编辑</button><button data-del="engagement-app" data-id="${a.id}">删除</button></div></td></tr>`).join("");
  $("app-table").innerHTML = `<table><thead><tr><th>客户</th><th>标题</th><th>类型</th><th>开始</th><th>状态</th><th>负责人</th><th>操作</th></tr></thead><tbody>${appRows || '<tr><td colspan="7" class="empty">暂无预约</td></tr>'}</tbody></table>` + pagerHTML("engagement-app", pg.page, pg.pages, pg.total)
  const cpRows = (pg = pageSlice("engagement-coupon", e.coupons, 20)).rows.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(zh(c.coupon_type))}</td><td>${esc(c.value || "暂无")}</td><td class="num">${c.valid_days || 0}天</td><td>${badge(c.status)}</td><td><div class="lead-actions"><button data-edit="engagement-coupon" data-id="${c.id}">编辑</button><button data-del="engagement-coupon" data-id="${c.id}">删除</button></div></td></tr>`).join("");
  $("coupon-table").innerHTML = `<table><thead><tr><th>券</th><th>类型</th><th>券值</th><th class="num">有效期</th><th>状态</th><th>操作</th></tr></thead><tbody>${cpRows || '<tr><td colspan="6" class="empty">暂无优惠券</td></tr>'}</tbody></table>` + pagerHTML("engagement-coupon", pg.page, pg.pages, pg.total)
  const ucRows = (pg = pageSlice("engagement-uc", e.userCoupons, 20)).rows.map((u) => `<tr><td>${esc(displayId(u.session_id))}</td><td>${esc(u.coupon_id)}</td><td>${esc((u.expires_at || "").slice(0, 10))}</td><td>${badge(u.status)}</td><td><div class="lead-actions"><button data-del="engagement-uc" data-id="${u.id}">删除</button></div></td></tr>`).join("");
  $("user-coupon-table").innerHTML = `<table><thead><tr><th>客户</th><th>券ID</th><th>到期</th><th>状态</th><th>操作</th></tr></thead><tbody>${ucRows || '<tr><td colspan="5" class="empty">暂无发放记录</td></tr>'}</tbody></table>` + pagerHTML("engagement-uc", pg.page, pg.pages, pg.total)
  const plRows = (pg = pageSlice("engagement-pl", e.paymentLinks, 20)).rows.map((p) => `<tr><td>${esc(p.title || "暂无")}</td><td>${p.order_id}</td><td class="num">￥${fmt(p.amount)}</td><td>${badge(p.status)}</td><td>${esc(p.link || "暂无")}</td><td><div class="lead-actions"><button data-edit="engagement-pl" data-id="${p.id}">编辑</button><button data-del="engagement-pl" data-id="${p.id}">删除</button></div></td></tr>`).join("");
  $("pl-table").innerHTML = `<table><thead><tr><th>标题</th><th>订单</th><th class="num">金额</th><th>状态</th><th>链接</th><th>操作</th></tr></thead><tbody>${plRows || '<tr><td colspan="6" class="empty">暂无支付链接</td></tr>'}</tbody></table>` + pagerHTML("engagement-pl", pg.page, pg.pages, pg.total)
}

/* ===== 优化中心 ===== */
async function loadOptimization() {
  try {
    const [scores, scoreStats, prompts, experiments, suggestions] = await Promise.all([
      fetchJSON("http://127.0.0.1:5000/api/v1/optimize/scores?limit=20"),
      fetchJSON("http://127.0.0.1:5000/api/v1/optimize/scores/stats?days=7"),
      fetchJSON("http://127.0.0.1:5000/api/v1/optimize/prompts"),
      fetchJSON("http://127.0.0.1:5000/api/v1/optimize/experiments"),
      fetchJSON("http://127.0.0.1:5000/api/v1/optimize/suggestions"),
    ]);
    state.selfOpt = {
      scores: scores.scores || [],
      stats: scoreStats || {},
      prompts: prompts.versions || [],
      experiments: experiments.experiments || [],
      suggestions: suggestions.suggestions || [],
    };
  } catch (e) {
    state.selfOpt = { scores: [], stats: {}, prompts: [], experiments: [], suggestions: [] };
  }
  renderOptimization();
}

function renderOptimization() {
  const o = state.selfOpt || {};
  const stats = o.stats || {};
  const dims = stats.by_dimension || {};

  // KPIs
  $("optimization-kpis").innerHTML =
    kpi("总评分", stats.avg_score || 0, "", "近7天平均") +
    kpi("对话数", stats.total || 0, "", "近7天") +
    kpi("转化推进", dims.conversion || 0, "", "/25") +
    kpi("合规性", dims.compliance || 0, "", "/25") +
    kpi("满意度", dims.satisfaction || 0, "", "/25") +
    kpi("响应质量", dims.response || 0, "", "/25");

  // Score stats by product
  const byProd = stats.by_product || {};
  let prodHtml = "";
  for (const [k, v] of Object.entries(byProd)) {
    prodHtml += `<tr><td>${esc(k)}</td><td class="num">${v.count}</td><td class="num">${v.avg}</td></tr>`;
  }
  $("score-stats").innerHTML = prodHtml ? `<table><thead><tr><th>产品</th><th>对话数</th><th>平均分</th></tr></thead><tbody>${prodHtml}</tbody></table>` : '<div class="empty">暂无数据</div>';

  // Score table
  const scRows = (o.scores || []).map((s) => `<tr>
    <td>${esc(s.session_id || '').substring(0,12)}</td>
    <td>${esc(s.product || '-')}</td>
    <td class="num">${s.conversion_score}</td>
    <td class="num">${s.compliance_score}</td>
    <td class="num">${s.satisfaction_score}</td>
    <td class="num">${s.response_score}</td>
    <td class="num"><strong>${s.total_score}</strong></td>
    <td class="muted">${esc((s.created_at || '').substring(5,16))}</td>
  </tr>`).join("");
  $("score-table").innerHTML = scRows ? `<table><thead><tr><th>会话</th><th>产品</th><th>转化</th><th>合规</th><th>满意</th><th>响应</th><th>总分</th><th>时间</th></tr></thead><tbody>${scRows}</tbody></table>` : '<div class="empty">暂无评分数据</div>';

  // Prompt versions
  const pvRows = (o.prompts || []).map((v) => `<tr>
    <td>v${v.version}</td>
    <td>${esc(v.description || '')}</td>
    <td>${v.is_active ? '<span class="badge ok">当前使用</span>' : '<span class="badge muted">未激活</span>'}</td>
    <td class="num">${v.total_conversations}</td>
    <td class="num">${(v.avg_score || 0).toFixed(1)}</td>
    <td class="num">${(v.conversion_rate || 0).toFixed(1)}%</td>
    <td>${v.is_active ? '-' : `<button onclick="activatePrompt(${v.id})" class="primary" style="padding:3px 8px;font-size:12px">激活</button>`}</td>
  </tr>`).join("");
  $("prompt-version-table").innerHTML = pvRows ? `<table><thead><tr><th>版本</th><th>描述</th><th>状态</th><th>对话数</th><th>平均分</th><th>高质量率</th><th>操作</th></tr></thead><tbody>${pvRows}</tbody></table>` : '<div class="empty">暂无版本</div>';

  // A/B experiments
  const expRows = (o.experiments || []).map((e) => `<tr>
    <td>${esc(e.name)}</td>
    <td>${esc(e.kind)}</td>
    <td><span class="badge ${e.status === 'running' ? 'ok' : e.status === 'finished' ? 'brand' : 'muted'}">${esc(e.status)}</span></td>
    <td>${esc((e.created_at || '').substring(5,16))}</td>
    <td>
      ${e.status === 'draft' ? `<button onclick="startExperiment(${e.id})" style="padding:3px 8px;font-size:12px">启动</button>` : ''}
      ${e.status === 'running' ? `<button onclick="viewExpResults(${e.id})" style="padding:3px 8px;font-size:12px">查看结果</button>` : ''}
    </td>
  </tr>`).join("");
  $("exp-table").innerHTML = expRows ? `<table><thead><tr><th>实验名</th><th>类型</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>${expRows}</tbody></table>` : '<div class="empty">暂无实验</div>';

  // Suggestions
  const sugRows = (o.suggestions || []).map((s) => `<tr>
    <td><span class="badge ${s.category === '合规' ? 'danger' : s.category === '转化' ? 'warn' : 'brand'}">${esc(s.category)}</span></td>
    <td>${esc(s.title)}</td>
    <td>${esc(s.suggested_value || '').substring(0,60)}</td>
    <td class="num">${(s.impact_score || 0).toFixed(1)}/10</td>
    <td><span class="badge ${s.status === 'approved' ? 'ok' : s.status === 'rejected' ? 'danger' : 'warn'}">${esc(s.status)}</span></td>
    <td>
      ${s.status === 'pending' ? `<button onclick="approveSuggestion(${s.id})" style="padding:3px 8px;font-size:12px">批准</button> <button onclick="rejectSuggestion(${s.id})" style="padding:3px 8px;font-size:12px">拒绝</button>` : ''}
    </td>
  </tr>`).join("");
  $("sug-table").innerHTML = sugRows ? `<table><thead><tr><th>类型</th><th>问题</th><th>建议</th><th>影响</th><th>状态</th><th>操作</th></tr></thead><tbody>${sugRows}</tbody></table>` : '<div class="empty">暂无建议</div>';
}

async function activatePrompt(id) {
  await fetchJSON("http://127.0.0.1:5000/api/v1/optimize/prompts/" + id + "/activate", { method: "POST" });
  toast("已激活");
  loadOptimization();
}

async function startExperiment(id) {
  await fetchJSON("http://127.0.0.1:5000/api/v1/optimize/experiments/" + id + "/start", { method: "POST" });
  toast("实验已启动");
  loadOptimization();
}

async function viewExpResults(id) {
  const r = await fetchJSON("http://127.0.0.1:5000/api/v1/optimize/experiments/" + id + "/results");
  $("exp-results").innerHTML = `<div class="box"><h3>实验结果 #${id}</h3>
    <p>对照组: ${r.control.count}次, 平均${r.control.avg}分 | 实验组: ${r.variant.count}次, 平均${r.variant.avg}分</p>
    <p><strong>${r.recommendation}</strong></p>
  </div>`;
}

async function approveSuggestion(id) {
  await fetchJSON("http://127.0.0.1:5000/api/v1/optimize/suggestions/" + id + "/approve", { method: "POST" });
  toast("已批准");
  loadOptimization();
}

async function rejectSuggestion(id) {
  await fetchJSON("http://127.0.0.1:5000/api/v1/optimize/suggestions/" + id + "/reject", { method: "POST" });
  toast("已拒绝");
  loadOptimization();
}
async function loadCompliance() {
  const [rules, stats] = await Promise.all([
    fetchJSON("http://127.0.0.1:5000/api/v1/compliance/rules"),
    fetchJSON("http://127.0.0.1:5000/api/v1/compliance/stats"),
  ]);
  state.compliance = { rules: rules.rules || [], stats };
  renderCompliance();
}

function renderCompliance() {
  const c = state.compliance;
  const s = c.stats || {};
  $("compliance-kpis").innerHTML =
    kpi("规则", s.total) + kpi("启用", s.enabled) + kpi("转人工", s.handover) + kpi("停止触达", s.stop);
  const rows = (pg = pageSlice("compliance-rules", c.rules, 20)).rows.map((r) => `<tr><td>${esc(zh(r.rule_type))}</td><td>${esc((r.trigger_words || "").slice(0, 60))}</td><td>${esc(r.action)}</td><td class="num">${r.priority}</td><td>${r.enabled ? "启用" : "停用"}</td><td>${esc(r.description || "暂无")}</td><td><div class="lead-actions"><button data-edit="compliance-rules" data-id="${r.id}">编辑</button><button data-del="compliance-rules" data-id="${r.id}">删除</button></div></td></tr>`).join("");
  $("comp-table").innerHTML = `<table><thead><tr><th>类型</th><th>触发词</th><th>动作</th><th class="num">优先级</th><th>状态</th><th>说明</th><th>操作</th></tr></thead><tbody>${rows || '<tr><td colspan="7" class="empty">暂无规则</td></tr>'}</tbody></table>` + pagerHTML("compliance-rules", pg.page, pg.pages, pg.total)
}

/* ===== 事件绑定 ===== */

/* ===== 分页回调注册 ===== */
registerPageRender("customers", () => renderCustomers());
registerPageRender("leads", () => renderLeads());
registerPageRender("orders", () => renderOrders());
registerPageRender("opportunities", () => renderOpportunities());
registerPageRender("followups", () => renderFollowup());
registerPageRender("tickets", () => renderTickets());
["ammo-products","ammo-objections","ammo-competitors","ammo-scripts","ammo-cases","winning-df","winning-ev","winning-tools","engagement-app","engagement-coupon","engagement-uc","engagement-pl","optimization-summary","optimization-exp","optimization-review","compliance-rules"].forEach((k) => registerPageRender(k, () => loadAll()));

/* ===== 编辑/删除注册 ===== */
registerDelete("ammo-products", "http://127.0.0.1:5000/api/v1/ammo/products", loadAmmo);
registerDelete("ammo-objections", "http://127.0.0.1:5000/api/v1/ammo/objections", loadAmmo);
registerDelete("ammo-competitors", "http://127.0.0.1:5000/api/v1/ammo/competitors", loadAmmo);
registerDelete("ammo-scripts", "http://127.0.0.1:5000/api/v1/ammo/scripts", loadAmmo);
registerDelete("ammo-cases", "http://127.0.0.1:5000/api/v1/ammo/cases", loadAmmo);
registerDelete("winning-df", "http://127.0.0.1:5000/api/v1/winning/differentiators", loadWinning);
registerDelete("winning-ev", "http://127.0.0.1:5000/api/v1/winning/evidence", loadWinning);
registerDelete("winning-tools", "http://127.0.0.1:5000/api/v1/winning/tools", loadWinning);
registerDelete("engagement-app", "http://127.0.0.1:5000/api/v1/appointments", loadEngagement);
registerDelete("engagement-coupon", "http://127.0.0.1:5000/api/v1/coupons", loadEngagement);
registerDelete("engagement-uc", "http://127.0.0.1:5000/api/v1/user-coupons", loadEngagement);
registerDelete("engagement-pl", "http://127.0.0.1:5000/api/v1/payment-links", loadEngagement);
registerDelete("optimization-exp", "http://127.0.0.1:5000/api/v1/optimize/experiments", loadOptimization);
registerDelete("optimization-review", "http://127.0.0.1:5000/api/v1/optimize/reviews", loadOptimization);
registerDelete("compliance-rules", "http://127.0.0.1:5000/api/v1/compliance/rules", loadCompliance);

registerEdit("ammo-products", "http://127.0.0.1:5000/api/v1/ammo/products", [{key:"product_name",label:"产品名"}, {key:"price",label:"价格"}, {key:"selling_points",label:"卖点"}], loadAmmo);
registerEdit("ammo-objections", "http://127.0.0.1:5000/api/v1/ammo/objections", [{key:"trigger_scene",label:"异议场景"}, {key:"standard_reply",label:"标准回复"}], loadAmmo);
registerEdit("ammo-competitors", "http://127.0.0.1:5000/api/v1/ammo/competitors", [{key:"competitor",label:"竞品"}, {key:"standard_reply",label:"标准回应"}], loadAmmo);
registerEdit("ammo-scripts", "http://127.0.0.1:5000/api/v1/ammo/scripts", [{key:"followup_scene",label:"状态"}, {key:"script_example",label:"话术"}], loadAmmo);
registerEdit("winning-df", "http://127.0.0.1:5000/api/v1/winning/differentiators", [{key:"differentiator",label:"差异点"}, {key:"evidence",label:"证据"}], loadWinning);
registerEdit("winning-ev", "http://127.0.0.1:5000/api/v1/winning/evidence", [{key:"title",label:"标题"}, {key:"content",label:"内容"}], loadWinning);
registerEdit("winning-tools", "http://127.0.0.1:5000/api/v1/winning/tools", [{key:"name",label:"工具名"}, {key:"description",label:"说明"}], loadWinning);
registerEdit("engagement-app", "http://127.0.0.1:5000/api/v1/appointments", [{key:"title",label:"标题"}, {key:"start_at",label:"开始时间"}, {key:"owner",label:"负责人"}], loadEngagement);
registerEdit("engagement-coupon", "http://127.0.0.1:5000/api/v1/coupons", [{key:"name",label:"券名"}, {key:"value",label:"券值"}], loadEngagement);
registerEdit("engagement-pl", "http://127.0.0.1:5000/api/v1/payment-links", [{key:"title",label:"标题"}, {key:"link",label:"链接"}], loadEngagement);
registerEdit("optimization-exp", "http://127.0.0.1:5000/api/v1/optimize/experiments", [{key:"name",label:"实验名"},{key:"control",label:"对照组"},{key:"variant",label:"实验组"}], loadOptimization);
registerEdit("compliance-rules", "http://127.0.0.1:5000/api/v1/compliance/rules", [{key:"description",label:"说明"}], loadCompliance);

document.addEventListener("DOMContentLoaded", () => {
  if (!$("pk-add")) return;

  $("pk-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/ammo/products", { fields: { product_name: $("pk-name").value.trim(), price: $("pk-price").value.trim(), selling_points: $("pk-selling").value.trim() } });
      ["pk-name", "pk-price", "pk-selling"].forEach((id) => $(id).value = "");
      await loadAmmo();
    } catch (e) { showError("添加产品知识失败：" + e.message); }
  });
  $("obj-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/ammo/objections", { fields: { trigger_scene: $("obj-scene").value.trim(), standard_reply: $("obj-reply").value.trim(), evidence: $("obj-evidence").value.trim(), next_step: $("obj-next").value.trim() } });
      ["obj-scene", "obj-reply", "obj-evidence", "obj-next"].forEach((id) => $(id).value = "");
      await loadAmmo();
    } catch (e) { showError("添加异议应答失败：" + e.message); }
  });
  $("cp-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/ammo/competitors", { fields: { competitor: $("cp-name").value.trim(), customer_saying: $("cp-saying").value.trim(), differentiator_1: $("cp-diff1").value.trim(), standard_reply: $("cp-reply").value.trim() } });
      ["cp-name", "cp-saying", "cp-diff1", "cp-reply"].forEach((id) => $(id).value = "");
      await loadAmmo();
    } catch (e) { showError("添加竞品应对失败：" + e.message); }
  });
  $("fs-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/ammo/scripts", { fields: { followup_scene: $("fs-scene").value, script_example: $("fs-script").value.trim(), value_point: $("fs-value").value.trim(), next_goal: $("fs-goal").value.trim(), delay_hours: Number($("fs-delay").value || 24) } });
      ["fs-script", "fs-value", "fs-goal", "fs-delay"].forEach((id) => $(id).value = "");
      await loadAmmo();
    } catch (e) { showError("添加工跟进话术失败：" + e.message); }
  });
  $("case-import").addEventListener("click", async () => {
    const content = $("case-content").value.trim();
    if (!content) return showError("请先粘贴案例内容");
    try {
      const data = await postJSON("http://127.0.0.1:5000/api/v1/ammo/cases/import", { content, title: $("case-title").value.trim(), channel: $("case-channel").value.trim() });
      alert(`案例已导入学习：${data.case && data.case.title ? data.case.title : "已生成"}`);
      ["case-title", "case-channel", "case-content"].forEach((id) => $(id).value = "");
      await loadAmmo();
    } catch (e) { showError("案例导入失败：" + e.message); }
  });

  $("df-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/winning/differentiators", { fields: { product: $("df-product").value.trim(), differentiator: $("df-point").value.trim(), customer_concern: $("df-concern").value.trim(), evidence: $("df-evidence").value.trim() } });
      ["df-product", "df-point", "df-concern", "df-evidence"].forEach((id) => $(id).value = "");
      await loadWinning();
    } catch (e) { showError("添加差异点失败：" + e.message); }
  });
  $("ev-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/winning/evidence", { fields: { evidence_type: $("ev-type").value, title: $("ev-title").value.trim(), content: $("ev-content").value.trim(), link: $("ev-link").value.trim(), scenario: $("ev-scenario").value.trim() } });
      ["ev-title", "ev-content", "ev-link", "ev-scenario"].forEach((id) => $(id).value = "");
      await loadWinning();
    } catch (e) { showError("添加证据失败：" + e.message); }
  });
  $("tool-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/winning/tools", { fields: { tool_type: $("tool-type").value, name: $("tool-name").value.trim(), description: $("tool-desc").value.trim(), trigger_scene: $("tool-scene").value.trim() } });
      ["tool-name", "tool-desc", "tool-scene"].forEach((id) => $(id).value = "");
      await loadWinning();
    } catch (e) { showError("添加关键时刻工具失败：" + e.message); }
  });

  $("app-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/appointments", { fields: { session_id: $("app-session").value.trim(), title: $("app-title").value.trim(), start_at: $("app-start").value.trim(), owner: $("app-owner").value.trim(), appointment_type: "trial" } });
      ["app-session", "app-title", "app-start", "app-owner"].forEach((id) => $(id).value = "");
      await loadEngagement();
    } catch (e) { showError("创建预约失败：" + e.message); }
  });
  $("coupon-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/coupons", { fields: { name: $("coupon-name").value.trim(), coupon_type: $("coupon-type").value, value: $("coupon-value").value.trim(), valid_days: Number($("coupon-days").value || 7) } });
      ["coupon-name", "coupon-value", "coupon-days"].forEach((id) => $(id).value = "");
      await loadEngagement();
    } catch (e) { showError("创建优惠券失败：" + e.message); }
  });
  $("coupon-grant").addEventListener("click", async () => {
    const couponId = prompt("请输入要发放的优惠券 ID");
    const sessionId = $("coupon-session").value.trim();
    if (!couponId || !sessionId) return showError("请填写优惠券 ID 和客户 ID");
    try {
      await postJSON(`/api/v1/coupons/${couponId}/grant`, { fields: { session_id: sessionId } });
      $("coupon-session").value = "";
      await loadEngagement();
    } catch (e) { showError("发放优惠券失败：" + e.message); }
  });
  $("pl-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/payment-links", { order_id: Number($("pl-order").value || 0), title: $("pl-title").value.trim(), amount: Number($("pl-amount").value || 0), link: $("pl-link").value.trim() });
      ["pl-order", "pl-title", "pl-amount", "pl-link"].forEach((id) => $(id).value = "");
      await loadEngagement();
    } catch (e) { showError("生成支付链接失败：" + e.message); }
  });

  if ($("summary-search")) $("summary-search").addEventListener("click", loadOptimization);
  if ($("summary-status")) $("summary-status").addEventListener("change", loadOptimization);
  $("exp-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/optimize/experiments", { fields: { name: $("exp-name").value.trim(), kind: $("exp-kind").value || "prompt", control: $("exp-control").value.trim(), variant: $("exp-variant").value.trim() } });
      ["exp-name", "exp-control", "exp-variant"].forEach((id) => $(id).value = "");
      await loadOptimization();
    } catch (e) { showError("创建实验失败：" + e.message); }
  });
  if (!$("review-add")) return;
  $("review-add").addEventListener("click", async () => {
    const content = $("review-content").value.trim();
    if (!content) return;
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/optimize/reviews", { fields: { content } });
      $("review-content").value = "";
      await loadOptimization();
    } catch (e) { showError("生成复盘失败：" + e.message); }
  });

  $("comp-add").addEventListener("click", async () => {
    try {
      await postJSON("http://127.0.0.1:5000/api/v1/compliance/rules", { rule_type: $("comp-type").value, trigger_words: $("comp-words").value.trim(), action: $("comp-action").value, description: $("comp-desc").value.trim() });
      ["comp-words", "comp-desc"].forEach((id) => $(id).value = "");
      await loadCompliance();
    } catch (e) { showError("添加合规规则失败：" + e.message); }
  });
});

document.addEventListener("click", async (e) => {
  const expBtn = e.target.closest("button[data-exp-action]");
  if (expBtn) {
    try {
      await fetch(`/api/v1/optimize/experiments/${expBtn.dataset.id}`, {
        method: "PATCH", headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ fields: { status: expBtn.dataset.expAction } }),
      });
      await loadOptimization();
    } catch (err) { showError("实验操作失败：" + err.message); }
  }
});

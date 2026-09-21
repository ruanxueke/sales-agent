/* 企业级能力驾驶舱：租户 / 计费 / 分析 / 预测 / 集成 / AI 能力状态 */
(function () {
  function esc(v) {
    return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function headers() {
    const t = localStorage.getItem("sales_token");
    const k = localStorage.getItem("sales_api_key");
    if (t) return { "Authorization": "Bearer " + t };
    return k ? { "X-API-Key": k } : {};
  }
  async function postJSON(url, body) {
    const res = await fetch(url, { method: "POST", headers: Object.assign(headers(), { "Content-Type": "application/json" }), body: JSON.stringify(body || {}) });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }
  async function getJSON(url) {
    const res = await fetch(url, { headers: headers() });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }
  function statusTag(ok) {
    return ok ? '<span style="color:#16a34a">已配置</span>' : '<span style="color:#dc2626">未配置</span>';
  }

  async function loadAll() {
    const box = document.getElementById("enterprise-level-content");
    if (!box) return;
    box.innerHTML = "加载中...";
    try {
      const [tenants, billingHealth, plans, funnel, roi, aiImpact, forecast, aiStatus, voice, integrations, webhook, org, webchatSessions, alertRules, alertEvents, billingPlans, billingInvoices, webhookList] = await Promise.all([
        getJSON("/api/v1/tenants").catch(() => ({ items: [] })),
        getJSON("/api/v1/billing/health").catch(() => ({})),
        getJSON("/api/v1/billing/plans").catch(() => ({ plans: {} })),
        getJSON("/api/v1/analytics/funnel?days=30").catch(() => ({ steps: [] })),
        getJSON("/api/v1/analytics/channel-roi?days=30").catch(() => ({ items: [] })),
        getJSON("/api/v1/analytics/ai-impact?days=30").catch(() => ({ channels: {} })),
        getJSON("/api/v1/forecast/list?limit=10").catch(() => ({ items: [] })),
        getJSON("/api/v1/multimodal/status").catch(() => ({})),
        getJSON("/api/v1/voice/status").catch(() => ({})),
        getJSON("/api/v1/integrations/status").catch(() => ({})),
        getJSON("/api/v1/webhooks").catch(() => ({ items: [] })),
      getJSON("/api/v1/org/overview").catch(() => ({ items: [] })),
      getJSON("/api/v1/webchat/sessions").catch(() => ({ items: [] })),
      getJSON("/api/v1/alerting/rules").catch(() => ({ items: [] })),
      getJSON("/api/v1/alerting/events?limit=20").catch(() => ({ items: [] })),
      getJSON("/api/v1/billing/plans").catch(() => ({ plans: {} })),
      getJSON("/api/v1/billing/invoices").catch(() => ({ items: [] })),
      getJSON("/api/v1/webhooks").catch(() => ({ items: [] })),
      ]);
      box.innerHTML = render(tenants, billingHealth, plans, funnel, roi, aiImpact, forecast, aiStatus, voice, integrations, webhook, org, webchatSessions, alertRules, alertEvents, billingPlans, billingInvoices, webhookList);
    } catch (e) {
      box.innerHTML = '<div style="color:#dc2626">加载失败：' + esc(e.message) + '</div>';
    }
  }

  function render(tenants, billingHealth, plans, funnel, roi, aiImpact, forecast, aiStatus, voice, integrations, webhook, org, webchatSessions, alertRules, alertEvents, billingPlans, billingInvoices, webhookList) {
    const planRows = Object.entries(plans.plans || {}).map(([k, p]) =>
      `<tr><td>${esc(p.name)}</td><td>${esc(p.price_month)} 元/月</td><td>${esc(p.seats)} 坐席</td><td>${esc(p.customers)} 客户</td><td>${esc(p.messages)} 消息</td></tr>`).join("");
    const tenantRows = (tenants.items || []).map(t =>
      `<tr><td>${esc(t.name)}</td><td>${esc(t.tenant_key)}</td><td>${esc(t.plan)}</td><td>${esc(t.seats)}</td><td>${esc(t.status)}</td><td>${esc(t.expires_at || "-")}</td></tr>`).join("");
    const funnelRows = (funnel.steps || []).map(s =>
      `<tr><td>${esc(s.stage)}</td><td>${esc(s.count)}</td><td>${esc(s.rate_from_top)}%</td><td>${esc(s.rate_from_prev)}%</td></tr>`).join("");
    const roiRows = (roi.items || []).map(r =>
      `<tr><td>${esc(r.channel)}</td><td>${esc(r.leads)}</td><td>${esc(r.conversion)}%</td><td>${esc(r.revenue)}</td><td>${r.roi == null ? "-" : esc(r.roi)}</td></tr>`).join("");
    const forecastRows = (forecast.items || []).map(f =>
      `<tr><td>${esc(f.nickname)}</td><td>${esc(f.stage)}</td><td>${esc(Math.round(f.win_probability * 100))}%</td><td>${esc(Math.round(f.churn_risk * 100))}%</td><td>${esc(f.next_follow_up || "-")}</td></tr>`).join("");
    const aiRows = Object.entries(aiImpact.channels || {}).map(([k, v]) =>
      `<tr><td>${esc(k)}</td><td>${esc(v.customers)}</td><td>${esc(v.won)}</td><td>${esc(v.win_rate)}%</td></tr>`).join("");
    const intRows = Object.entries(integrations || {}).map(([k, v]) =>
      `<tr><td>${esc(k)}</td><td>${statusTag(v.configured)}</td><td>${esc((v.features || []).join("、"))}</td></tr>`).join("");
    const orgRows = (org.items || []).map((o) => {
      const t = o.tenant || {};
      const sub = o.subscription || {};
      const quota = o.quota || {};
      const memberRows = (o.members || []).map((m) =>
        `<tr><td>${esc(m.username || m.name || "-")}</td><td>${esc(m.role)}</td><td>${esc(m.status)}</td></tr>`).join("");
      return `<div class="box" style="margin-bottom:14px">
        <h2>${esc(t.name || "-")} <span class="muted">${esc(t.tenant_key || "")}</span></h2>
        <table><tbody>
          <tr><td>套餐</td><td>${esc(sub.plan || t.plan || "-")} / ${esc(sub.status || "-")}</td></tr>
          <tr><td>到期</td><td>${esc(sub.expires_at || "-")}</td></tr>
          <tr><td>客户配额</td><td>${esc((quota.customers || {}).used || 0)} / ${esc((quota.customers || {}).quota || 0)}</td></tr>
          <tr><td>消息配额</td><td>${esc((quota.messages || {}).used || 0)} / ${esc((quota.messages || {}).quota || 0)}</td></tr>
        </tbody></table>
        <h3 style="margin:10px 0 6px">成员</h3>
        <table><thead><tr><th>账号</th><th>角色</th><th>状态</th></tr></thead><tbody>${memberRows || '<tr><td colspan="3" class="empty">暂无成员</td></tr>'}</tbody></table>
      </div>`;
    }).join("");

    const orgPanel = `
      <div class="box" style="margin-bottom:14px">
        <h2>组织管理</h2>
        <div class="toolbar" style="margin-bottom:10px">
          <input id="org-name" placeholder="企业名称" style="width:160px">
          <button id="org-create" type="button" class="primary">创建租户</button>
          <span style="width:20px"></span>
          <input id="org-tenant-id" type="number" placeholder="租户ID" style="width:90px">
          <input id="org-username" placeholder="成员账号" style="width:130px">
          <input id="org-password" placeholder="密码" style="width:110px">
          <input id="org-member-name" placeholder="姓名" style="width:90px">
          <select id="org-role"><option value="sales">销售</option><option value="manager">主管</option><option value="admin">管理员</option><option value="viewer">只读</option></select>
          <button id="org-member-add" type="button">添加成员</button>
        </div>
        <div id="org-list">${orgRows || '<div class="muted">暂无租户，先创建第一个企业租户</div>'}</div>
      </div>`;

    const wcRows = (webchatSessions.items || []).map((s) =>
      `<tr><td>${esc(s.session_key)}</td><td>${esc(s.visitor_name || "-")}</td><td>${esc(s.status)}</td><td>${esc(s.updated_at || "-")}</td></tr>`).join("");
    const wcPanel = `
      <div class="box" style="margin-bottom:14px">
        <h2>网页客服会话</h2>
        <table><thead><tr><th>会话</th><th>访客</th><th>状态</th><th>更新时间</th></tr></thead><tbody>${wcRows || '<tr><td colspan="4" class="empty">暂无会话</td></tr>'}</tbody></table>
      </div>`;

    const botRule = (alertRules.items || []).find((r) => r.rule_type === "bot_offline");
    const botEnabled = botRule ? Number(botRule.enabled) === 1 : true;
    const ruleRows = (alertRules.items || []).map((r) =>
      `<tr><td>${esc(r.name)}</td><td>${esc(r.rule_type)}</td><td>${r.enabled ? "启用" : "停用"}</td><td>${esc(r.threshold)}</td><td>${esc(r.receivers || "-")}</td></tr>`).join("");
    const eventRows = (alertEvents.items || []).map((e) =>
      `<tr><td>${esc(e.sent_at)}</td><td>${esc(e.title)}</td><td>${esc(e.level)}</td><td>${esc(e.status)}</td></tr>`).join("");
    const alertPanel = `
      <div class="box" style="margin-bottom:14px">
        <h2>监控告警</h2>
        <div class="toolbar" style="margin-bottom:8px">
          <button id="alert-test" type="button" class="primary">发送测试告警</button>
          <span class="muted" id="alert-test-msg"></span>
          <span style="width:16px"></span>
          <label style="display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:#44506a">
            机器人在线检测
            <button id="bot-check-toggle" type="button" class="${botEnabled ? 'primary' : ''}" style="min-width:58px">${botEnabled ? '开' : '关'}</button>
          </label>
          <span class="muted" id="bot-check-msg"></span>
        </div>
        <h3 style="margin:8px 0 6px">告警规则</h3>
        <table><thead><tr><th>规则</th><th>类型</th><th>状态</th><th>阈值</th><th>接收人</th></tr></thead><tbody>${ruleRows || '<tr><td colspan="5" class="empty">暂无规则</td></tr>'}</tbody></table>
        <h3 style="margin:10px 0 6px">最近告警</h3>
        <table><thead><tr><th>时间</th><th>标题</th><th>级别</th><th>状态</th></tr></thead><tbody>${eventRows || '<tr><td colspan="4" class="empty">暂无告警</td></tr>'}</tbody></table>
      </div>`;

    const planRows2 = Object.entries(billingPlans.plans || {}).map(([k, p]) =>
      `<tr><td>${esc(p.name)}</td><td>${esc(p.price_month)} 元/月</td><td>${esc(p.seats)} 坐席</td><td>${esc(p.customers)} 客户</td><td><button data-subscribe="${k}" type="button">开通</button></td></tr>`).join("");
    const invoiceRows = (billingInvoices.items || []).map((i) =>
      `<tr><td>#${esc(i.id)}</td><td>${esc(i.plan)}</td><td>${esc(i.amount)}</td><td>${esc(i.status)}</td><td>${esc(i.paid_at || "-")}</td></tr>`).join("");
    const hookRows = (webhookList.items || []).map((h) =>
      `<tr><td>${esc(h.url)}</td><td>${esc((h.events || []).join(","))}</td><td>${esc(h.created_at || "-")}</td></tr>`).join("");
    const bizPanel = `
      <div class="box" style="margin-bottom:14px">
        <h2>计费管理</h2>
        <div class="toolbar" style="margin-bottom:8px">
          <input id="biz-tenant-id" type="number" placeholder="租户ID" style="width:90px">
          <select id="biz-plan"><option value="trial">试用</option><option value="pro">专业</option><option value="enterprise">企业</option></select>
          <button id="biz-subscribe" type="button" class="primary">开通套餐</button>
          <span class="muted" id="biz-msg"></span>
        </div>
        <h3 style="margin:8px 0 6px">套餐</h3>
        <table><thead><tr><th>套餐</th><th>价格</th><th>坐席</th><th>客户</th><th>操作</th></tr></thead><tbody>${planRows2 || '<tr><td colspan="5" class="empty">暂无套餐</td></tr>'}</tbody></table>
        <h3 style="margin:10px 0 6px">账单</h3>
        <table><thead><tr><th>编号</th><th>套餐</th><th>金额</th><th>状态</th><th>支付时间</th></tr></thead><tbody>${invoiceRows || '<tr><td colspan="5" class="empty">暂无账单</td></tr>'}</tbody></table>
      </div>
      <div class="box" style="margin-bottom:14px">
        <h2>开放平台</h2>
        <div class="toolbar" style="margin-bottom:8px">
          <input id="hook-url" placeholder="回调地址 https://..." style="flex:1">
          <button id="hook-add" type="button">添加 Webhook</button>
          <span class="muted" id="hook-msg"></span>
        </div>
        <table><thead><tr><th>回调地址</th><th>事件</th><th>创建时间</th></tr></thead><tbody>${hookRows || '<tr><td colspan="3" class="empty">暂无 Webhook</td></tr>'}</tbody></table>
        <div class="muted" style="margin-top:8px">嵌入网页客服：<code>&lt;script src="/static/webchat-widget.js"&gt;&lt;/script&gt;</code></div>
      </div>`;

    return `
      ${orgPanel}
      ${alertPanel}
      ${bizPanel}
      ${wcPanel}
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px">
        <div class="box">
          <h2>租户管理 · 多租户/RBAC</h2>
          <table><thead><tr><th>企业</th><th>租户Key</th><th>套餐</th><th>坐席</th><th>状态</th><th>到期</th></tr></thead><tbody>${tenantRows || '<tr><td colspan="6" class="empty">暂无租户</td></tr>'}</tbody></table>
        </div>
        <div class="box">
          <h2>计费 · 套餐</h2>
          <div class="muted" style="margin-bottom:8px">支付网关：${esc(billingHealth.note || billingHealth.payment_provider || "-")}</div>
          <table><thead><tr><th>套餐</th><th>价格</th><th>坐席</th><th>客户</th><th>消息</th></tr></thead><tbody>${planRows || '<tr><td colspan="5" class="empty">暂无套餐</td></tr>'}</tbody></table>
        </div>
        <div class="box">
          <h2>转化漏斗</h2>
          <table><thead><tr><th>阶段</th><th>客户数</th><th>总转化率</th><th>环比</th></tr></thead><tbody>${funnelRows || '<tr><td colspan="4" class="empty">暂无数据</td></tr>'}</tbody></table>
        </div>
        <div class="box">
          <h2>渠道 ROI</h2>
          <table><thead><tr><th>渠道</th><th>线索</th><th>转化率</th><th>营收</th><th>ROI</th></tr></thead><tbody>${roiRows || '<tr><td colspan="5" class="empty">暂无数据</td></tr>'}</tbody></table>
        </div>
        <div class="box">
          <h2>赢单概率 / 流失预警</h2>
          <table><thead><tr><th>客户</th><th>阶段</th><th>赢单</th><th>流失</th><th>下次跟进</th></tr></thead><tbody>${forecastRows || '<tr><td colspan="5" class="empty">暂无数据</td></tr>'}</tbody></table>
        </div>
        <div class="box">
          <h2>AI 效果对比</h2>
          <table><thead><tr><th>通道</th><th>客户</th><th>成交</th><th>成交率</th></tr></thead><tbody>${aiRows || '<tr><td colspan="4" class="empty">暂无数据</td></tr>'}</tbody></table>
        </div>
        <div class="box">
          <h2>AI 能力状态</h2>
          <table><tbody>
            <tr><td>多模态视觉</td><td>${statusTag(aiStatus.configured)}</td><td>${esc(aiStatus.note || "-")}</td></tr>
            <tr><td>实时语音</td><td>${statusTag(voice.configured)}</td><td>${esc(voice.note || "-")}</td></tr>
          </tbody></table>
        </div>
        <div class="box">
          <h2>集成生态</h2>
          <table><thead><tr><th>系统</th><th>状态</th><th>能力</th></tr></thead><tbody>${intRows || '<tr><td colspan="3" class="empty">暂无集成</td></tr>'}</tbody></table>
        </div>
        <div class="box">
          <h2>开放平台 Webhook</h2>
          <table><thead><tr><th>订阅</th></tr></thead><tbody>${(webhook.items || []).map(h => `<tr><td>${esc(h.url)} · ${esc((h.events || []).join(","))}</td></tr>`).join("") || '<tr><td class="empty">暂无 Webhook</td></tr>'}</tbody></table>
        </div>
      </div>`;
  }

  const ADMIN_ROLES = ["owner", "admin", "manager"];

  function applyAccess() {
    const btn = document.querySelector('button[data-view="enterprise-level"]');
    if (!btn) return;
    const token = localStorage.getItem("sales_token");
    const apiKey = localStorage.getItem("sales_api_key");
    if (!token && !apiKey) return;
    // API Key 模式视为管理员；token 模式按角色判断
    if (!token) return;
    getJSON("/api/v1/accounts/tenant-me").then((d) => {
      const role = d.role || "";
      if (!ADMIN_ROLES.includes(role)) {
        btn.style.display = "none";
        const section = document.getElementById("view-enterprise-level");
        if (section) section.classList.remove("active");
      }
    }).catch(() => {});
  }

  window.loadEnterpriseLevel = function () { loadAll(); };

  function bind() {
    const btn = document.querySelector('button[data-view="enterprise-level"]');
    const section = document.getElementById("view-enterprise-level");
    if (!btn || !section) return;
    applyAccess();
    btn.addEventListener("click", () => {
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      section.classList.add("active");
      const title = document.getElementById("page-title");
      if (title) title.textContent = "企业级";
      loadAll();
    });
    document.addEventListener("click", async (e) => {
      if (e.target && e.target.id === "org-create") {
        const name = document.getElementById("org-name").value.trim();
        if (!name) return alert("请输入企业名称");
        try {
          await postJSON("/api/v1/tenants", { name });
          await loadAll();
        } catch (err) { alert("创建失败：" + err.message); }
      }
      if (e.target && e.target.id === "bot-check-toggle") {
        const msg = document.getElementById("bot-check-msg");
        try {
          const data = await getJSON("/api/v1/alerting/rules");
          const rule = (data.items || []).find((r) => r.rule_type === "bot_offline");
          if (!rule) { if (msg) msg.textContent = "未找到规则"; return; }
          const next = Number(rule.enabled) === 1 ? 0 : 1;
          if (msg) msg.textContent = "保存中...";
          await postJSON("/api/v1/alerting/rules", { rule_id: rule.id, rule_type: "bot_offline", name: rule.name, enabled: next, threshold: rule.threshold, window_seconds: rule.window_seconds, channels: rule.channels, receivers: rule.receivers, cooldown_seconds: rule.cooldown_seconds });
          if (msg) msg.textContent = next ? "已开启自动检测" : "已关闭自动检测";
          await loadAll();
        } catch (err) { if (msg) msg.textContent = "失败：" + err.message; }
      }
      if (e.target && e.target.id === "alert-test") {
        const msg = document.getElementById("alert-test-msg");
        if (msg) msg.textContent = "发送中...";
        try {
          const d = await postJSON("/api/v1/alerting/test", { title: "测试告警", content: "这是一条测试告警，确认通知通道正常。" });
          if (msg) msg.textContent = d.ok ? ("已发送：" + (d.channels || "无")) : "发送失败";
        } catch (err) { if (msg) msg.textContent = "发送失败：" + err.message; }
      }
      if (e.target && e.target.id === "biz-subscribe" || (e.target && e.target.dataset && e.target.dataset.subscribe)) {
        const tenantId = Number((document.getElementById("biz-tenant-id") || {}).value || 0);
        const plan = e.target.dataset.subscribe || (document.getElementById("biz-plan") || {}).value;
        const msg = document.getElementById("biz-msg");
        if (msg) msg.textContent = "开通中...";
        try {
          const d = await postJSON("/api/v1/billing/subscribe", { tenant_id: tenantId, plan, days: 30 });
          if (msg) msg.textContent = d.ok ? "已开通，账单已生成" : ("失败：" + (d.error || ""));
          await loadAll();
        } catch (err) { if (msg) msg.textContent = "失败：" + err.message; }
      }
      if (e.target && e.target.id === "hook-add") {
        const url = (document.getElementById("hook-url") || {}).value.trim();
        const msg = document.getElementById("hook-msg");
        if (!url) { if (msg) msg.textContent = "请输入回调地址"; return; }
        try {
          await postJSON("/api/v1/webhooks", { url, events: ["customer.created", "order.paid", "chat.received"] });
          if (msg) msg.textContent = "已添加";
          await loadAll();
        } catch (err) { if (msg) msg.textContent = "失败：" + err.message; }
      }
      if (e.target && e.target.id === "org-member-add") {
        const tenantId = Number(document.getElementById("org-tenant-id").value || 0);
        const username = document.getElementById("org-username").value.trim();
        const password = document.getElementById("org-password").value;
        const name = document.getElementById("org-member-name").value.trim();
        const role = document.getElementById("org-role").value;
        if (!tenantId || !username || !password) return alert("请填写租户ID、账号、密码");
        try {
          await postJSON("/api/v1/org/members", { tenant_id: tenantId, username, password, name, role });
          await loadAll();
        } catch (err) { alert("添加成员失败：" + err.message); }
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();

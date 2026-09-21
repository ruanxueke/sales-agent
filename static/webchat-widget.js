/* 销售智能体 · 网页客服聊天窗口（可嵌入任意网页） */
(function () {
  function load() {
    if (window.__salesWebChatLoaded) return;
    window.__salesWebChatLoaded = true;

    var style = document.createElement("style");
    style.textContent = `
#sales-webchat-root{position:fixed;right:20px;bottom:20px;z-index:99999;font-family:-apple-system,"Microsoft YaHei",sans-serif}
#sales-webchat-btn{width:56px;height:56px;border-radius:50%;background:#2563eb;color:#fff;border:none;font-size:22px;cursor:pointer;box-shadow:0 6px 18px rgba(37,99,235,.35)}
#sales-webchat-panel{display:none;position:fixed;right:20px;bottom:88px;width:340px;max-width:calc(100vw - 40px);height:460px;max-height:70vh;background:#fff;border-radius:14px;box-shadow:0 12px 40px rgba(15,23,42,.18);flex-direction:column;overflow:hidden}
#sales-webchat-panel.open{display:flex}
#sales-webchat-head{background:#1e3a5f;color:#fff;padding:14px 16px;font-size:14px;font-weight:600}
#sales-webchat-msgs{flex:1;overflow-y:auto;padding:12px;background:#f8fafc}
#sales-webchat-msgs .msg{margin-bottom:8px;max-width:82%;padding:9px 12px;border-radius:10px;font-size:13px;line-height:1.6;white-space:pre-wrap}
#sales-webchat-msgs .msg.customer{background:#2563eb;color:#fff;margin-left:auto;border-bottom-right-radius:3px}
#sales-webchat-msgs .msg.agent{background:#fff;border:1px solid #e2e8f0;border-bottom-left-radius:3px}
#sales-webchat-input-bar{display:flex;border-top:1px solid #e2e8f0;background:#fff}
#sales-webchat-input{flex:1;border:none;padding:12px;font-size:13px;outline:none}
#sales-webchat-send{background:#2563eb;color:#fff;border:none;padding:0 16px;font-size:13px;cursor:pointer}
`;
    document.head.appendChild(style);

    var root = document.createElement("div");
    root.id = "sales-webchat-root";
    root.innerHTML = `
      <div id="sales-webchat-panel">
        <div id="sales-webchat-head">在线咨询 · AI 销售顾问</div>
        <div id="sales-webchat-msgs"></div>
        <div id="sales-webchat-input-bar">
          <input id="sales-webchat-input" placeholder="请输入您的问题...">
          <button id="sales-webchat-send" type="button">发送</button>
        </div>
      </div>
      <button id="sales-webchat-btn" type="button">💬</button>`;
    document.body.appendChild(root);

    var sessionKey = "";
    var msgs = document.getElementById("sales-webchat-msgs");
    var input = document.getElementById("sales-webchat-input");
    var btn = document.getElementById("sales-webchat-btn");
    var panel = document.getElementById("sales-webchat-panel");

    function apiBase() {
      var opts = window.SalesWebChatOptions || {};
      return opts.apiBase || "";
    }

    function addMsg(role, text) {
      var div = document.createElement("div");
      div.className = "msg " + role;
      div.textContent = text;
      msgs.appendChild(div);
      msgs.scrollTop = msgs.scrollHeight;
    }

    function ensureSession() {
      if (sessionKey) return Promise.resolve(sessionKey);
      var opts = window.SalesWebChatOptions || {};
      return fetch(apiBase() + "/public/webchat/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visitor_name: opts.visitorName || "", source_page: location.href }),
      }).then(function (r) { return r.json(); }).then(function (d) {
        sessionKey = d.session_key || "";
        return sessionKey;
      });
    }

    function send() {
      var text = input.value.trim();
      if (!text) return;
      input.value = "";
      addMsg("customer", text);
      ensureSession().then(function () {
        return fetch(apiBase() + "/public/webchat/message", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_key: sessionKey, message: text, nickname: (window.SalesWebChatOptions || {}).visitorName || "" }),
        });
      }).then(function (r) { return r.json(); }).then(function (d) {
        addMsg("agent", d.reply || "抱歉，暂时无法回复，请稍后再试。");
      }).catch(function () {
        addMsg("agent", "网络异常，请稍后再试。");
      });
    }

    btn.addEventListener("click", function () {
      panel.classList.toggle("open");
      if (!msgs.children.length) {
        addMsg("agent", "您好，欢迎咨询！请问有什么可以帮您？");
        ensureSession();
      }
    });
    document.getElementById("sales-webchat-send").addEventListener("click", send);
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") send(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();

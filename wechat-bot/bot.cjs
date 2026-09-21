/**
 * Wechaty 销售客服机器人
 * 监听微信群和个人消息 → POST 到 Python AI API → 回复
 *
 * 启动：node bot.js
 * 首次需要扫二维码登录，登录态保存在 kefu-bot.memory-card.json
 */

const { WechatyBuilder } = require("wechaty");
const axios = require("axios");
const FormData = require("form-data");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

// 加载项目根目录 .env（不依赖第三方库）
try {
  const envPath = path.join(__dirname, "..", ".env");
  if (fs.existsSync(envPath)) {
    const envContent = fs.readFileSync(envPath, "utf8");
    for (const line of envContent.split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/i);
      if (m && !process.env[m[1]]) {
        process.env[m[1]] = m[2].replace(/^"|"$/g, "");
      }
    }
  }
} catch (_) { /* ignore */ }

// ===== 配置 =====
const AI_API_URL = process.env.AI_API_URL || "http://127.0.0.1:5002/api/v1/chat";
const VOICE_API_URL = AI_API_URL.replace(/\/+chat$/, "/chat_voice");
const IMAGE_API_URL = AI_API_URL.replace(/\/+chat$/, "/chat_image");
const TTS_API_URL = AI_API_URL.replace(/\/+chat$/, "/tts");
const API_KEY = process.env.API_KEY || (process.env.API_KEYS || "").split(",")[0] || "";
const recentMsgIds = new Set();
const recentRoomJoins = new Map(); // key -> 最近一次入群欢迎时间
let BOT_NAME = (process.env.BOT_NAME || "").trim();
let TARGET_ROOM_TOPIC = process.env.TARGET_ROOM_TOPIC || "\u6d4b\u8bd5\u9500\u552e\u667a\u80fd\u4f53";
let REQUIRE_MENTION = process.env.REQUIRE_MENTION === "true";
let PERSONAL_AUTO_REPLY = process.env.PERSONAL_AUTO_REPLY === "true";
const SELF_TEST = process.env.SELF_TEST === "true";
const LIVE_PING = process.env.LIVE_PING === "true";
const RUNTIME_LOG_PATH = path.join(__dirname, "bot-runtime.log");
const CONFIG_PATH = path.join(__dirname, "bot-config.json");
const BOT_NOTIFY_PORT = Number(process.env.BOT_NOTIFY_PORT || 3900);
const MONITOR_URL = (process.env.AI_API_URL || "http://127.0.0.1:5002/api/v1/chat").replace(/\/chat$/, "/monitor/heartbeat");
let MIN_REPLY_DELAY_MS = Number(process.env.MIN_REPLY_DELAY_MS || 5000);
let REPLY_MAX_LENGTH = Number(process.env.REPLY_MAX_LENGTH || 50);
let REPLY_SPLIT_DELAY_MS = Number(process.env.REPLY_SPLIT_DELAY_MS || 1500);
let WELCOME_ON_JOIN = process.env.WELCOME_ON_JOIN !== "false";
let WELCOME_MESSAGE = process.env.WELCOME_MESSAGE || "欢迎加入 Work Buddy 降本增效实操群。\n本群聚焦降本增效落地实践，借助 AI 工具优化人力、营销、客服及流程成本。";
try {
  if (fs.existsSync(CONFIG_PATH)) {
    const saved = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
    if (saved.target_room) TARGET_ROOM_TOPIC = String(saved.target_room);
    if (typeof saved.require_mention === "boolean") REQUIRE_MENTION = saved.require_mention;
    if (typeof saved.personal_auto_reply === "boolean") PERSONAL_AUTO_REPLY = saved.personal_auto_reply;
    if (Number(saved.min_reply_delay_ms) > 0) MIN_REPLY_DELAY_MS = Number(saved.min_reply_delay_ms);
    if (Number(saved.reply_max_length) > 0) REPLY_MAX_LENGTH = Number(saved.reply_max_length);
    if (Number(saved.reply_split_delay_ms) > 0) REPLY_SPLIT_DELAY_MS = Number(saved.reply_split_delay_ms);
    if (typeof saved.welcome_on_join === "boolean") WELCOME_ON_JOIN = saved.welcome_on_join;
    if (typeof saved.welcome_message === "string" && saved.welcome_message.trim()) WELCOME_MESSAGE = saved.welcome_message;
  }
} catch (_) { /* ignore */ }

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}`;
  console.log(line);
  try {
    fs.appendFileSync(RUNTIME_LOG_PATH, `${line}\n`, "utf8");
  } catch (err) {
    console.error("[Log Error]", err.message);
  }
}

// 不同微信协议下 talker.id 可能是方法或字符串，统一兼容处理
function getTalkerId(talker, fallback) {
  if (talker && typeof talker.id === "function") return talker.id();
  if (talker && talker.id) return talker.id;
  return fallback;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function noteMsgId(msgId) {
  if (!msgId) return false;
  if (recentMsgIds.has(msgId)) return false;
  recentMsgIds.add(msgId);
  if (recentMsgIds.size > 2000) {
    const first = recentMsgIds.values().next().value;
    recentMsgIds.delete(first);
  }
  return true;
}

// 回复不秒回：从收到消息到发出回复至少间隔 minDelayMs
async function ensureHumanDelay(startTime, minDelayMs) {
  const elapsed = Date.now() - startTime;
  if (elapsed < minDelayMs) {
    await sleep(minDelayMs - elapsed);
  }
}

// 回复超过20字拆成多条发送，URL保持完整，语义不变
function splitReply(text, maxLen = REPLY_MAX_LENGTH) {
  if (!text) return [];
  const str = String(text).trim();
  if (str.length <= maxLen) return [str];
  const weak = new Set(["，", ",", "、", "：", ":", " "]);
  const strong = new Set(["。", "！", "？", "!", "?", "；", ";", "\n"]);
  const urlRe = /https?:\/\/[^\s\u4e00-\u9fff，。！？；、：]+/g;
  const out = [];
  let seg = "";
  let i = 0;
  const n = str.length;
  while (i < n) {
    urlRe.lastIndex = i;
    const m = urlRe.exec(str);
    if (m && m.index === i) {
      if (seg.trim()) out.push(seg.trim());
      out.push(m[0]);
      seg = "";
      i = m.index + m[0].length;
      continue;
    }
    const ch = str[i];
    seg += ch;
    if (seg.length > maxLen && !strong.has(ch)) {
      let cut = -1;
      for (let j = seg.length - 2; j >= 0; j--) {
        if (weak.has(seg[j]) || strong.has(seg[j])) { cut = j + 1; break; }
      }
      if (cut <= 0) cut = maxLen;
      if (seg.slice(0, cut).trim()) out.push(seg.slice(0, cut).trim());
      seg = seg.slice(cut);
    } else if (strong.has(ch)) {
      if (seg.length > maxLen) {
        let cut = -1;
        for (let j = seg.length - 2; j >= 0; j--) {
          if (weak.has(seg[j]) || strong.has(seg[j])) { cut = j + 1; break; }
        }
        if (cut <= 0) cut = maxLen;
        if (seg.slice(0, cut).trim()) out.push(seg.slice(0, cut).trim());
        seg = seg.slice(cut);
      }
      if (seg.trim()) out.push(seg.trim());
      seg = "";
    }
    i++;
  }
  if (seg.trim()) out.push(seg.trim());
  return out.filter(Boolean);
}

async function sendSplit(room, talker, reply) {
  const parts = splitReply(reply);
  for (let idx = 0; idx < parts.length; idx++) {
    await room.say(parts[idx], talker);
    if (idx < parts.length - 1) await sleep(REPLY_SPLIT_DELAY_MS);
  }
  log(`[拆分发送] 共${parts.length}条`);
}

// ===== 创建 Bot =====
const bot = WechatyBuilder.build({
  name: "sales-bot", // 登录态文件名: kefu-bot.memory-card.json
  puppet: "wechaty-puppet-wechat4u",
});

let botLoggedIn = false;

// 登录后每 30 秒向后端上报一次心跳，用于监控“机器人是否在线”
setInterval(() => {
  if (!botLoggedIn) return;
  axios.post(MONITOR_URL, { source: "wechat" }, {
    timeout: 5000,
    headers: API_KEY ? { "X-API-Key": API_KEY } : {},
  })
    .then(() => {})
    .catch((err) => log(`[监控] 心跳上报失败: ${err.message}`));
}, 30000);

// ===== 通知投递服务：接收 Python 侧销售线索通知并发送给指定人员 =====
const notifyServer = http.createServer(async (req, res) => {
  if (req.method === "POST" && req.url === "/notify") {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk; });
    req.on("end", async () => {
      let payload = {};
      try { payload = JSON.parse(raw || "{}"); } catch (_) { /* ignore */ }
      const targetName = payload.target_name || "";
      const targetId = payload.target_id || "";
      const content = payload.content || "";
      if ((!targetName && !targetId) || !content) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: false, error: "missing target/content" }));
        return;
      }
      try {
        const result = await sendNotification(targetName, content, targetId);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify(result));
      } catch (err) {
        log(`[通知服务] 发送失败: ${err.message}`);
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: false, error: err.message }));
      }
    });
    return;
  }
  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ ok: false, error: "not found" }));
  // 中台控制接口：状态 / 二维码 / 日志 / 重启
  if (req.method === "GET" && req.url === "/status") {
  if (req.url === "/config") {
    if (req.method === "GET") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        ok: true,
        target_room: TARGET_ROOM_TOPIC,
        require_mention: REQUIRE_MENTION,
        personal_auto_reply: PERSONAL_AUTO_REPLY,
        min_reply_delay_ms: MIN_REPLY_DELAY_MS,
        reply_max_length: REPLY_MAX_LENGTH,
        reply_split_delay_ms: REPLY_SPLIT_DELAY_MS,
        welcome_on_join: WELCOME_ON_JOIN,
        welcome_message: WELCOME_MESSAGE,
      }));
      return;
    }
    if (req.method === "POST") {
      let raw = "";
      req.on("data", (chunk) => { raw += chunk; });
      req.on("end", () => {
        let payload = {};
        try { payload = JSON.parse(raw || "{}"); } catch (_) { /* ignore */ }
        if (typeof payload.target_room === "string" && payload.target_room.trim()) TARGET_ROOM_TOPIC = payload.target_room.trim();
        if (typeof payload.require_mention === "boolean") REQUIRE_MENTION = payload.require_mention;
        if (typeof payload.personal_auto_reply === "boolean") PERSONAL_AUTO_REPLY = payload.personal_auto_reply;
        if (Number(payload.min_reply_delay_ms) >= 0) MIN_REPLY_DELAY_MS = Number(payload.min_reply_delay_ms);
        if (Number(payload.reply_max_length) >= 1) REPLY_MAX_LENGTH = Number(payload.reply_max_length);
        if (Number(payload.reply_split_delay_ms) >= 0) REPLY_SPLIT_DELAY_MS = Number(payload.reply_split_delay_ms);
        if (typeof payload.welcome_on_join === "boolean") WELCOME_ON_JOIN = payload.welcome_on_join;
        if (typeof payload.welcome_message === "string" && payload.welcome_message.trim()) WELCOME_MESSAGE = payload.welcome_message;
        const saved = {
          target_room: TARGET_ROOM_TOPIC,
          require_mention: REQUIRE_MENTION,
          personal_auto_reply: PERSONAL_AUTO_REPLY,
          min_reply_delay_ms: MIN_REPLY_DELAY_MS,
          reply_max_length: REPLY_MAX_LENGTH,
          reply_split_delay_ms: REPLY_SPLIT_DELAY_MS,
          welcome_on_join: WELCOME_ON_JOIN,
          welcome_message: WELCOME_MESSAGE,
        };
        try { fs.writeFileSync(CONFIG_PATH, JSON.stringify(saved, null, 2), "utf8"); } catch (_) { /* ignore */ }
        log(`[配置] 已更新: ${JSON.stringify(saved)}`);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true, config: saved }));
      });
      return;
    }
  }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({
      ok: true,
      online: botLoggedIn,
      bot_name: BOT_NAME,
      target_room: TARGET_ROOM_TOPIC,
      require_mention: REQUIRE_MENTION,
      personal_auto_reply: PERSONAL_AUTO_REPLY,
      welcome_on_join: WELCOME_ON_JOIN,
      welcome_message: WELCOME_MESSAGE,
      notify_port: BOT_NOTIFY_PORT,
      pid: process.pid,
      uptime_sec: Math.round(process.uptime()),
      last_log: fs.existsSync(RUNTIME_LOG_PATH) ? (fs.readFileSync(RUNTIME_LOG_PATH, "utf8").trim().split(/\r?\n/).slice(-5).join("\n")) : ""
    }));
    return;
  }
  if (req.method === "GET" && req.url === "/qrcode") {
    let qrUrl = "";
    let qrPath = "";
    try {
      if (fs.existsSync(path.join(__dirname, "qrcode_url.txt"))) {
        qrUrl = fs.readFileSync(path.join(__dirname, "qrcode_url.txt"), "utf8").trim();
      }
      if (fs.existsSync(path.join(__dirname, "qrcode.png"))) {
        qrPath = path.join(__dirname, "qrcode.png");
      }
    } catch (_) { /* ignore */ }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, qr_url: qrUrl, qr_path: qrPath }));
    return;
  }
  if (req.method === "GET" && req.url === "/logs") {
    let lines = [];
    try {
      if (fs.existsSync(RUNTIME_LOG_PATH)) {
        lines = fs.readFileSync(RUNTIME_LOG_PATH, "utf8").trim().split(/\r?\n/).slice(-50);
      }
    } catch (_) { /* ignore */ }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, lines }));
    return;
  }
  if (req.method === "POST" && req.url === "/command") {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk; });
    req.on("end", () => {
      let cmd = "";
      try { cmd = (JSON.parse(raw || "{}").command || "").toString(); } catch (_) { /* ignore */ }
      if (cmd === "restart") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true, message: "restarting" }));
        setTimeout(() => {
          const { execSync } = require("child_process");
          try { execSync("pm2 restart sales-wechat-bot", { stdio: "ignore" }); } catch (_) { /* ignore */ }
          try { execSync("pm2 restart run_cloud.sh", { stdio: "ignore" }); } catch (_) { /* ignore */ }
        }, 500);
        return;
      }
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: false, error: "unsupported command" }));
    });
    return;
  }
});

notifyServer.listen(BOT_NOTIFY_PORT, () => {
  log(`[通知服务] 已启动，端口=${BOT_NOTIFY_PORT}`);
});

async function sendNotification(targetName, content, targetId) {
  if (targetId) {
    try {
      const contact = await bot.Contact.find({ id: targetId });
      if (contact) {
        await contact.say(content);
        log(`[通知服务] 已按ID私聊发送给 ${targetName || targetId}`);
        return { ok: true, channel: "contact-id", target: targetName || targetId };
      }
    } catch (err) {
      log(`[通知服务] 按ID查找/发送失败: ${err.message}`);
    }
  }
  // 优先私聊：按微信名找联系人
  try {
    const contact = await bot.Contact.find({ name: targetName });
    if (contact) {
      await contact.say(content);
      log(`[通知服务] 已私聊发送给 ${targetName}`);
      return { ok: true, channel: "contact", target: targetName };
    }
  } catch (err) {
    log(`[通知服务] 私聊查找/发送失败: ${err.message}`);
  }

  // 兜底：在目标群里 @ 该成员
  const room = await bot.Room.find({ topic: TARGET_ROOM_TOPIC });
  if (room) {
    const member = await room.member({ name: targetName });
    if (member) {
      await room.say(content, member);
      log(`[通知服务] 已在目标群 @${targetName} 发送`);
      return { ok: true, channel: "room", target: targetName };
    }
  }
  throw new Error(`未找到微信名为「${targetName}」的联系人或群成员`);
}

// ===== 转发消息到 AI API =====
async function askAI(message, fromUser, room, nickname) {
  try {
    const res = await axios.post(AI_API_URL, {
      message: message,
      from_user: fromUser,
      room: room || "",
      nickname: nickname || "",
    }, {
      timeout: 30000,
      headers: API_KEY ? { "X-API-Key": API_KEY } : {},
    });
    const reply = res.data && typeof res.data.reply === "string" ? res.data.reply.trim() : "";
    if (!reply) log(`[AI] 返回为空，room=${room || ""}`);
    return reply;
  } catch (err) {
    log(`[AI API Error] ${err.code || ""} ${err.message}`);
    return null;
  }
}

// 语音消息：上传到 AI 服务转写，并直接拿到销售智能体回复
async function chatByVoice(filePath, fromUser, room, nickname) {
  try {
    const form = new FormData();
    form.append("file", fs.createReadStream(filePath), path.basename(filePath));
    form.append("from_user", fromUser);
    form.append("room", room || "");
    form.append("nickname", nickname || "");
    const res = await axios.post(VOICE_API_URL, form, {
      headers: Object.assign(form.getHeaders(), API_KEY ? { "X-API-Key": API_KEY } : {}),
      timeout: 60000,
    });
    const reply = res.data && typeof res.data.reply === "string" ? res.data.reply.trim() : "";
    const transcript = res.data && typeof res.data.transcript === "string" ? res.data.transcript : "";
    if (!reply) log(`[Voice] 返回为空，room=${room || ""}`);
    return { reply, transcript };
  } catch (err) {
    log(`[Voice API Error] ${err.code || ""} ${err.message}`);
    return { reply: null, transcript: "" };
  }
}

// 处理语音消息：下载 → 转写 → 交给销售智能体 → 回复
async function handleVoiceMessage(msg, talker, room, alias, topic, startTime) {
  let tmpPath = null;
  try {
    const fileBox = await msg.toFileBox();
    if (!fileBox) {
      log(`[群:${topic}] 语音下载失败：toFileBox 返回空`);
      return;
    }
    const ext = path.extname(fileBox.name || "") || ".sil";
    tmpPath = path.join(os.tmpdir(), `voice-${Date.now()}-${Math.random().toString(16).slice(2)}${ext}`);
    await fileBox.toFile(tmpPath);
    log(`[群:${topic}] 语音已下载(${alias})，开始转写`);
    const customerId = getTalkerId(talker, alias);
    const result = await chatByVoice(tmpPath, customerId, topic, alias);
    if (result.transcript) {
      log(`[群:${topic}] 语音转写(${alias}): ${result.transcript}`);
    }
    if (result.reply) {
      await ensureHumanDelay(startTime, MIN_REPLY_DELAY_MS);
      let audioSent = false;
      if (result.audio_url) {
        try {
          const { FileBox } = require("file-box");
          const audioFile = await FileBox.fromUrl(result.audio_url);
          await room.say(audioFile, talker);
          audioSent = true;
          log(`[群:${topic}] 已发送语音回复(${alias})，音频=${result.audio_url}`);
        } catch (err) {
          log(`[Voice Reply] 语音发送失败，改用文字: ${err.message}`);
        }
      }
      if (!audioSent) {
        await sendSplit(room, talker, result.reply);
      }
      log(`[群:${topic}] 已回复语音问题(${alias})，长度=${result.reply.length}`);
    }
  } catch (err) {
    log(`[Voice Error] ${err.stack || err.message}`);
  } finally {
    if (tmpPath) {
      fs.unlink(tmpPath, () => {});
    }
  }
}


// 处理图片消息：下载 → MIMO 视觉模型读图 → DeepSeek 生成销售回复
async function handleImageMessage(msg, talker, room, alias, topic, startTime) {
  let tmpPath = null;
  try {
    const fileBox = await msg.toFileBox();
    if (!fileBox) {
      log(`[群:${topic}] 图片下载失败：toFileBox 返回空`);
      return;
    }
    const ext = path.extname(fileBox.name || "") || ".jpg";
    tmpPath = path.join(os.tmpdir(), `image-${Date.now()}-${Math.random().toString(16).slice(2)}${ext}`);
    await fileBox.toFile(tmpPath);
    log(`[群:${topic}] 图片已下载(${alias})，开始视觉识别`);
    const customerId = getTalkerId(talker, alias);
    const form = new FormData();
    form.append("file", fs.createReadStream(tmpPath), path.basename(tmpPath));
    form.append("from_user", customerId);
    form.append("room", topic || "");
    form.append("nickname", alias || "");
    const res = await axios.post(IMAGE_API_URL, form, {
      headers: Object.assign(form.getHeaders(), API_KEY ? { "X-API-Key": API_KEY } : {}),
      timeout: 90000,
    });
    const reply = res.data && typeof res.data.reply === "string" ? res.data.reply.trim() : "";
    const transcript = res.data && typeof res.data.transcript === "string" ? res.data.transcript : "";
    if (transcript) {
      log(`[群:${topic}] 图片识别(${alias}): ${transcript.slice(0, 120)}`);
    }
    if (reply) {
      await ensureHumanDelay(startTime, MIN_REPLY_DELAY_MS);
      await sendSplit(room, talker, reply);
      log(`[群:${topic}] 已回复图片问题(${alias})，长度=${reply.length}`);
    }
  } catch (err) {
    log(`[Image Error] ${err.stack || err.message}`);
  } finally {
    if (tmpPath) {
      fs.unlink(tmpPath, () => {});
    }
  }
}

// ===== 事件监听 =====

// 登录成功
bot.on("login", (user) => {
  botLoggedIn = true;
  if (!BOT_NAME) BOT_NAME = user.name();
  log(`[Bot] 登录成功: ${user.name()}`);
  log(`[Bot] 目标群=${TARGET_ROOM_TOPIC}，触发方式=${REQUIRE_MENTION ? `仅 @${BOT_NAME}` : "群内全部文本"}`);
});

// 登出
bot.on("logout", (user) => {
  botLoggedIn = false;
  log(`[Bot] 已登出: ${user.name()}`);
});

bot.on("error", (err) => {
  log(`[Bot Error] ${err.stack || err.message || err}`);
});

// Wechaty 会定期发出心跳；记录它可以区分“已登录但未同步消息”和“进程已失活”。
bot.on("heartbeat", (data) => {
  let beat = "";
  try {
    beat = data && (data.data || data) ? JSON.stringify(data.data || data) : "";
  } catch (_) {
    beat = "[unserializable]";
  }
  log(`[Bot] 心跳${beat ? ` ${beat.slice(0, 200)}` : ""}`);
});

// 收到消息
bot.on("message", async (msg) => {
  try {
    const msgStart = Date.now();
    const messageType = msg.type();
    const room = msg.room();
    log(`[消息事件] type=${messageType}，群聊=${Boolean(room)}`);
    const msgId = msg.id ? String(msg.id) : "";
    if (!noteMsgId(msgId)) {
      log(`[消息事件] 忽略重复消息 ${msgId}`);
      return;
    }

    // 只处理文本、语音、图片消息
    if (messageType !== bot.Message.Type.Text && messageType !== bot.Message.Type.Audio && messageType !== bot.Message.Type.Image) {
      log(`[消息事件] 忽略非文本/非语音/非图片消息 type=${messageType}`);
      return;
    }
    const isVoice = messageType === bot.Message.Type.Audio;
    const isImage = messageType === bot.Message.Type.Image;

    const talker = msg.talker();
    const text = msg.text();

    // 忽略自己发的消息
    if (talker.self()) {
      log(`[消息事件] 忽略机器人自身消息，长度=${text.length}`);
      return;
    }

    // --- 群消息 ---
    if (room) {
      const topic = await room.topic();
      const alias = await room.alias(talker) || talker.name();
      log(`[群:${topic}] 收到消息，发送者=${alias}，长度=${text.length}`);

      if (topic !== TARGET_ROOM_TOPIC) {
        log(`[群:${topic}] 非目标群，忽略；目标群=${TARGET_ROOM_TOPIC}`);
        return;
      }

      // 语音/图片消息无法附带 @，目标群内直接视为客户咨询
      if (isVoice) {
        log(`[群:${topic}] 收到语音消息，发送者=${alias}，长度=${text.length}`);
        await handleVoiceMessage(msg, talker, room, alias, topic, msgStart);
        return;
      }
      if (isImage) {
        log(`[群:${topic}] 收到图片消息，发送者=${alias}`);
        await handleImageMessage(msg, talker, room, alias, topic, msgStart);
        return;
      }

      // 与旧企业客服一致：优先用 mentionList 判断，昵称文本匹配作兼容兜底。
      let isMentioned = false;
      if (REQUIRE_MENTION) {
        try {
          const mentionList = await msg.mentionList();
          isMentioned = mentionList.some((contact) => contact.self());
        } catch (err) {
          log(`[群:${topic}] mentionList 读取失败: ${err.message}`);
        }
        if (!isMentioned && BOT_NAME && text.includes(`@${BOT_NAME}`)) {
          isMentioned = true;
        }
        if (!isMentioned) {
          log(`[群:${topic}] 未 @${BOT_NAME || "机器人"}，忽略消息`);
          return;
        }
      }

      // 去掉 @ 前缀后再交给销售智能体，避免模型把它当成客户问题的一部分。
      const cleanText = BOT_NAME
        ? text.replace(new RegExp(`@${BOT_NAME}[\\s\\u2000-\\u200f\\u00a0]*`, "g"), "").trim() || text
        : text;
      const customerId = getTalkerId(talker, alias);
      const reply = await askAI(cleanText, customerId, topic, alias);
      if (reply) {
        await ensureHumanDelay(msgStart, MIN_REPLY_DELAY_MS);
        // 仅当客户明确要求语音回复时发语音，否则正常文字回复
        const voiceWords = ["语音回复", "发语音", "用语音", "语音说", "语音给我", "语音回我", "语音回答"];
        const wantVoice = voiceWords.some((w) => text.includes(w));
        let voiceSent = false;
        if (wantVoice) {
          try {
            const { FileBox } = require("file-box");
            const ttsRes = await axios.post(TTS_API_URL, { text: reply }, {
              timeout: 60000,
              headers: API_KEY ? { "X-API-Key": API_KEY } : {},
            });
            const audioUrl = ttsRes.data && ttsRes.data.audio_url;
            if (audioUrl) {
              const audioFile = await FileBox.fromUrl(audioUrl);
              await room.say(audioFile, talker);
              voiceSent = true;
              log(`[群:${topic}] 客户要求语音回复，已发送语音(${alias})`);
            }
          } catch (err) {
            log(`[TTS Reply] 语音发送失败，改用文字: ${err.message}`);
          }
        }
        if (!voiceSent) {
          await sendSplit(room, talker, reply);
        }
        log(`[群:${topic}] 已回复，长度=${reply.length}`);
      }
      return;
    }

    // --- 个人消息：只记录，不回复 ---
    const name = talker.name();
    log(`[个人] 已忽略消息，发送者=${name}，长度=${text.length}`);

    if (PERSONAL_AUTO_REPLY) {
      const customerId = getTalkerId(talker, name);
      const reply = await askAI(text, customerId, "", name);
      if (reply) {
        await ensureHumanDelay(msgStart, MIN_REPLY_DELAY_MS);
        await talker.say(reply);
        log(`[个人] 已回复，发送者=${name}，长度=${reply.length}`);
      }
      return;
    }
    log(`[个人] 已忽略消息，发送者=${name}，长度=${text.length}`);
    return;
  } catch (err) {
    log(`[Message Error] ${err.stack || err.message}`);
  }
});

// 扫码

// 目标群新人入群自动欢迎
bot.on("room-join", async (room, inviteeList) => {
  try {
    if (!WELCOME_ON_JOIN) return;
    const topic = await room.topic();
    if (topic !== TARGET_ROOM_TOPIC) {
      log(`[Welcome] Ignore non-target room: ${topic}`);
      return;
    }
    const contacts = Array.isArray(inviteeList) ? inviteeList : [];
    if (!contacts.length) return;
    const names = [];
    let selfJoined = false;
    for (const contact of contacts) {
      try {
        if (contact && typeof contact.self === "function" && contact.self()) selfJoined = true;
        names.push(contact && typeof contact.name === "function" ? contact.name() : "new_member");
      } catch (_) { /* ignore single contact errors */ }
    }
    if (selfJoined) {
      log(`[Welcome] Skip self-join: ${names.join("|")}`);
      return;
    }
    const now = Date.now();
    const key = `${topic}:${names.sort().join("|")}`;
    const lastSeen = recentRoomJoins.get(key);
    if (lastSeen && now - lastSeen < 60000) {
      log(`[Welcome] Ignore duplicate room-join: ${key}`);
      return;
    }
    recentRoomJoins.set(key, now);
    if (recentRoomJoins.size > 500) {
      const oldest = recentRoomJoins.keys().next().value;
      recentRoomJoins.delete(oldest);
    }
    await room.say(WELCOME_MESSAGE);
    log(`[Welcome] Room=${topic} joined=${names.join("|")} welcome_sent`);
  } catch (err) {
    log(`[Welcome] Failed: ${err.stack || err.message}`);
  }
});
bot.on("scan", (qrcode, status) => {
  log(`[Bot] 扫码状态: ${status}`);
  if (status === 2) {
    // 生成二维码 URL，用浏览器打开扫码
    const qrUrl = `https://wechaty.js.org/qrcode/${encodeURIComponent(qrcode)}`;
    log(`[Bot] 请扫码登录: ${qrUrl}`);
    // 同时输出终端二维码（部分终端支持）
    const Qrterminal = require("qrcode-terminal");
    Qrterminal.generate(qrcode, { small: true });
try { require('fs').writeFileSync('qrcode_url.txt', qrUrl); } catch(e){}
  }
});

// 就绪
bot.on("ready", () => {
  log("[Bot] 就绪，开始监听消息...");
  // 登录态恢复后主动读取群列表，确认目标群是否已同步。
  bot.Room.findAll()
    .then(async (rooms) => {
      const topics = await Promise.all(rooms.map(async (room) => {
        try {
          return await room.topic();
        } catch (_) {
          return "(群名称读取失败)";
        }
      }));
      log(`[Bot] 群同步完成，群数量=${rooms.length}，群名称=${topics.join(" | ") || "无"}`);
      if (!topics.includes(TARGET_ROOM_TOPIC)) {
        log(`[Bot] 未找到目标群：${TARGET_ROOM_TOPIC}`);
      }
      if (LIVE_PING) {
        const roomIndex = topics.indexOf(TARGET_ROOM_TOPIC);
        if (roomIndex === -1) {
          log(`[自检] 未发送真实群检测消息：找不到目标群 ${TARGET_ROOM_TOPIC}`);
        } else {
          await rooms[roomIndex].say("【销售智能体】自动化检测：机器人已上线，请 @小天 发送测试消息。");
          log(`[自检] 已向真实目标群发送上线检测消息：${TARGET_ROOM_TOPIC}`);
        }
      }
    })
    .catch((err) => log(`[Bot] 群同步失败: ${err.stack || err.message}`));

  if (SELF_TEST) {
    const testRoom = {
      topic: async () => TARGET_ROOM_TOPIC,
      alias: async () => "自动化测试用户",
      say: async (content) => log(`[自检] 模拟群回复成功: ${content.slice(0, 80)}`),
    };
    const testTalker = {
      self: () => false,
      name: () => "自动化测试用户",
      id: "self_test_user",
    };
    const testMessage = {
      id: `self_test_msg_${Date.now()}`,
      type: () => bot.Message.Type.Text,
      room: () => testRoom,
      talker: () => testTalker,
      text: () => `@${BOT_NAME || "小天"} 测试销售智能体`,
      mentionList: async () => [{ self: () => true }],
      mentionSelf: async () => true,
    };
    log("[自检] 注入模拟群消息，验证消息处理与 AI 回复链路");
    bot.emit("message", testMessage);

    log("[自检] 注入模拟新人入群事件，验证目标群欢迎语");
    const testNewcomer = {
      self: () => false,
      name: () => "虚拟测试新人",
    };
    bot.emit("room-join", testRoom, [testNewcomer], testTalker);

    const voiceFilePath = process.env.SELF_TEST_VOICE_FILE || "";
    if (voiceFilePath && fs.existsSync(voiceFilePath)) {
      const testVoiceMessage = {
        type: () => bot.Message.Type.Audio,
        room: () => testRoom,
        talker: () => testTalker,
        text: () => "",
        toFileBox: async () => ({
          name: path.basename(voiceFilePath),
          toFile: async (dest) => { fs.copyFileSync(voiceFilePath, dest); },
        }),
      };
      log(`[自检] 注入模拟语音消息，验证语音转写与回复链路: ${voiceFilePath}`);
      bot.emit("message", testVoiceMessage);
    }
  }
});

// ===== 启动 =====
log("[Bot] 启动中...");
bot.start().catch((err) => {
  log(`[Bot] 启动失败: ${err.stack || err.message}`);
  process.exit(1);
});


/**
 * Wechaty 销售客服机器人
 * 监听微信群和个人消息 → POST 到 Python AI API → 回复
 *
 * 启动：node bot.js
 * 首次需要扫二维码登录，登录态保存在 kefu-bot.memory-card.json
 */

const { WechatyBuilder } = require("wechaty");
const axios = require("axios");

// ===== 配置 =====
const AI_API_URL = process.env.AI_API_URL || "http://127.0.0.1:5002/api/v1/chat";
const BOT_NAME = process.env.BOT_NAME || "销售客服";

// ===== 创建 Bot =====
const bot = WechatyBuilder.build({
  name: "sales-bot", // 登录态文件名: kefu-bot.memory-card.json
  puppet: "wechaty-puppet-wechat4u",
});

// ===== 转发消息到 AI API =====
async function askAI(message, fromUser, room) {
  try {
    const res = await axios.post(AI_API_URL, {
      message: message,
      from_user: fromUser,
      room: room || "",
    });
    return res.data.reply;
  } catch (err) {
    console.error("[AI API Error]", err.message);
    return null;
  }
}

// ===== 事件监听 =====

// 登录成功
bot.on("login", (user) => {
  console.log(`[Bot] 登录成功: ${user.name()}`);
});

// 登出
bot.on("logout", (user) => {
  console.log(`[Bot] 已登出: ${user.name()}`);
});

// 收到消息
bot.on("message", async (msg) => {
  try {
    // 只处理文本消息
    if (msg.type() !== bot.Message.Type.Text) return;

    const talker = msg.talker();
    const room = msg.room();
    const text = msg.text();

    // 忽略自己发的消息
    if (talker.self()) return;

    // --- 群消息 ---
    if (room) {
      const topic = await room.topic();
      const alias = await room.alias(talker) || talker.name();
      console.log(`[群:${topic}] ${alias}: ${text}`);

      // 只回复 @了机器人的消息
      const isMentioned = await msg.mentionSelf();
      if (!isMentioned) return;

      const reply = await askAI(text, alias, topic);
      if (reply) {
        await room.say(`@${alias} ${reply}`);
        console.log(`[回复群:${topic}] ${reply.slice(0, 50)}...`);
      }
      return;
    }

    // --- 个人消息：不回复 ---
    const name = talker.name();
    console.log(`[个人:]  (已忽略)`);
    return;
  } catch (err) {
    console.error("[Message Error]", err);
  }
});

// 扫码
bot.on("scan", (qrcode, status) => {
  console.log(`[Bot] 扫码状态: ${status}`);
  if (status === 2) {
    // 生成二维码 URL，用浏览器打开扫码
    const qrUrl = `https://wechaty.js.org/qrcode/${encodeURIComponent(qrcode)}`;
    console.log(`[Bot] 请扫码登录: ${qrUrl}`);
    // 同时输出终端二维码（部分终端支持）
    const Qrterminal = require("qrcode-terminal");
    Qrterminal.generate(qrcode, { small: true });
  }
});

// 就绪
bot.on("ready", () => {
  console.log("[Bot] 就绪，开始监听消息...");
});

// ===== 启动 =====
console.log("[Bot] 启动中...");
bot.start().catch((err) => {
  console.error("[Bot] 启动失败:", err);
  process.exit(1);
});

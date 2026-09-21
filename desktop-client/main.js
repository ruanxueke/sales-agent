const { app, BrowserWindow, ipcMain, safeStorage, shell } = require('electron');
const { spawn, spawnSync } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const https = require('https');

const PROJECT_ROOT = path.join(__dirname, '..');
const RESOURCE_ROOT = app.isPackaged ? process.resourcesPath : PROJECT_ROOT;
const CONFIG_PATH = path.join(RESOURCE_ROOT, 'vision_agent_config.json');
const AUTH_FILE = path.join(app.getPath('userData'), 'auth.bin');
const LOG_FILE = path.join(PROJECT_ROOT, 'vision_agent_data', 'vision_agent_worker.log');
const API_BASE = 'http://127.0.0.1:5000';
const WEB_ROOT = path.join(__dirname, 'web');
const BRIDGE_AGENT_VERSION = '2026.09.15.1';
const BRIDGE_TASK_NAME = 'SalesAgentWechatBridge';
const API_AGENT = new https.Agent({ keepAlive: true, maxSockets: 8 });
const API_RETRY_STATUSES = new Set([408, 425, 429, 500, 502, 503, 504]);
let LOCAL_URL = '';

let mainWindow = null;
let visionChild = null;
let wechatBridgeChild = null;
let wechatBridgeServiceMode = false;
let wechatBridgeDesired = false;
let wechatBridgeRestartTimer = null;
let wechatBridgeRestartAttempt = 0;
let wechatBridgeNextRestartAt = 0;
let wechatBridgeLastExit = null;
let appIsQuitting = false;
let storedKey = '';
let isTokenAuth = false;
let lastBridgeError = '';

function loadConfig() {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
    }
  } catch (e) {
    console.error('load config failed', e);
  }
  return {};
}

function saveAuth(key, isToken) {
  try {
    const payload = JSON.stringify({ key, isToken: !!isToken });
    const encrypted = safeStorage.encryptString(payload);
    fs.writeFileSync(AUTH_FILE, encrypted);
  } catch (e) {
    console.error('save auth failed', e);
  }
}

function loadAuth() {
  try {
    if (fs.existsSync(AUTH_FILE) && safeStorage.isEncryptionAvailable()) {
      const buf = fs.readFileSync(AUTH_FILE);
      const raw = safeStorage.decryptString(buf);
      try {
        const parsed = JSON.parse(raw);
        return { key: parsed.key || '', isToken: !!parsed.isToken };
      } catch (e) {
        return { key: raw, isToken: false };
      }
    }
  } catch (e) {
    console.error('load auth failed', e);
  }
  return { key: '', isToken: false };
}

function clearAuth() {
  try {
    if (fs.existsSync(AUTH_FILE)) fs.unlinkSync(AUTH_FILE);
  } catch (e) {}
}

function maskKey(key) {
  if (!key) return '';
  if (key.length <= 8) return '****';
  return key.slice(0, 4) + '****' + key.slice(-4);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function apiRequestOnce(pathname, method = 'GET', body = null, timeoutMs = 12000) {
  return new Promise((resolve) => {
    const url = new URL(API_BASE + pathname);
    const req = https.request(
      url,
      {
        method,
        agent: API_AGENT,
        headers: {
          'Content-Type': 'application/json',
          ...(isTokenAuth ? { Authorization: 'Bearer ' + storedKey } : { 'X-API-Key': storedKey }),
        },
      },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          let json = {};
          try { json = JSON.parse(data); } catch (e) {}
          resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, data: json });
        });
      }
    );
    req.setTimeout(timeoutMs, () => req.destroy(new Error('request timeout')));
    req.on('error', (e) => resolve({ ok: false, status: 0, data: { error: String(e.message || e) } }));
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

async function apiRequest(pathname, method = 'GET', body = null, options = {}) {
  const normalizedMethod = String(method || 'GET').toUpperCase();
  const attempts = Math.max(
    1,
    Number(options.attempts || (normalizedMethod === 'GET' ? 3 : 1))
  );
  let lastResult = { ok: false, status: 0, data: { error: 'request failed' } };
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const result = await apiRequestOnce(pathname, normalizedMethod, body);
    lastResult = result;
    if (result.ok || (!API_RETRY_STATUSES.has(result.status) && result.status !== 0)) {
      return result;
    }
    if (attempt < attempts) {
      const base = 400 * Math.pow(2, attempt - 1);
      const jitter = Math.floor(Math.random() * 200);
      await sleep(base + jitter);
    }
  }
  return lastResult;
}

function tailLog(file, lines = 120) {
  try {
    if (!fs.existsSync(file)) return [];
    const text = fs.readFileSync(file, 'utf-8');
    const arr = text.split(/\r?\n/).filter(Boolean);
    return arr.slice(-lines);
  } catch (e) {
    return [];
  }
}

function startVision() {
  if (visionChild) return { ok: true, already: true };
  if (!storedKey) return { ok: false, error: '未登录' };
  const config = loadConfig();
  const env = Object.assign({}, process.env, config || {});
  if (isTokenAuth) {
    env.VISION_AGENT_TOKEN = storedKey;
  } else {
    env.API_KEYS = storedKey;
    env.VISION_AGENT_API_KEY = storedKey;
  }
  const python = process.env.VISION_PYTHON || 'pythonw.exe';
  visionChild = spawn(python, ['-m', 'vision_agent.worker'], {
    cwd: RESOURCE_ROOT,
    env,
    windowsHide: true,
    stdio: 'ignore',
  });
  visionChild.on('exit', () => { visionChild = null; });
  return { ok: true };
}

function stopVision() {
  if (visionChild) {
    try { visionChild.kill(); } catch (e) {}
    visionChild = null;
  }
  return { ok: true };
}

function bridgeHomeDir() {
  return path.join(app.getPath('userData'), 'wechat_bridge');
}

function bridgeLogPath() {
  return path.join(bridgeHomeDir(), 'bridge.log');
}

function bridgeSecretPath() {
  return path.join(bridgeHomeDir(), 'bridge-secret.bin');
}

function appendBridgeLog(text) {
  try {
    const file = bridgeLogPath();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.appendFileSync(file, `[${new Date().toISOString()}] ${text}\n`, 'utf-8');
  } catch (e) {}
}

// ---------------------------------------------------------------------------
// 实例身份：每台机器 / 每个安装一份唯一 instance_id。
// 云端 personal_wechat_bridge_instances.instance_id 是全局唯一的，
// 如果所有客户都用同一个默认值，多个租户的心跳会互相覆盖，控制台互相串台。
// ---------------------------------------------------------------------------
function instanceIdPath() {
  return path.join(bridgeHomeDir(), 'instance.json');
}

function loadInstanceId() {
  try {
    if (fs.existsSync(instanceIdPath())) {
      const data = JSON.parse(fs.readFileSync(instanceIdPath(), 'utf-8'));
      if (data && data.instance_id) return String(data.instance_id);
    }
  } catch (e) {}
  return '';
}

function saveInstanceId(value) {
  try {
    fs.mkdirSync(bridgeHomeDir(), { recursive: true });
    fs.writeFileSync(
      instanceIdPath(),
      JSON.stringify({ instance_id: value, created_at: new Date().toISOString() }, null, 2),
      'utf-8'
    );
  } catch (e) {
    console.error('save instance id failed', e);
  }
}

function getOrCreateInstanceId() {
  const existing = loadInstanceId();
  if (existing) return existing;
  const seed = `${os.hostname()}|${app.getPath('userData')}|${Date.now()}|${Math.random()}`;
  const digest = crypto.createHash('sha1').update(seed).digest('hex').slice(0, 10);
  const value = `desktop-${digest}`;
  saveInstanceId(value);
  return value;
}

// ---------------------------------------------------------------------------
// 客户机上的桥接配置：从随包模板生成一份独立副本，之后只认这一份。
// 这样每个客户有自己的配置，包里也不再携带任何他人的账号与客户名单。
// ---------------------------------------------------------------------------
function bridgeConfigPath() {
  return path.join(bridgeHomeDir(), 'config.json');
}

function bridgeTemplatePaths() {
  return [
    path.join(RESOURCE_ROOT, 'wechat_bridge', 'config.desktop.json'),
    path.join(RESOURCE_ROOT, 'wechat_bridge', 'config.desktop.template.json'),
    path.join(RESOURCE_ROOT, 'wechat_bridge', 'config.example.json'),
  ];
}

function ensureBridgeConfig() {
  const target = bridgeConfigPath();
  const instanceId = getOrCreateInstanceId();
  fs.mkdirSync(bridgeHomeDir(), { recursive: true });
  if (!fs.existsSync(target)) {
    const template = bridgeTemplatePaths().find((p) => fs.existsSync(p));
    if (!template) return '';
    let raw = {};
    try {
      raw = JSON.parse(fs.readFileSync(template, 'utf-8'));
    } catch (e) {
      raw = {};
    }
    raw.instance_id = instanceId;
    raw.api_key_env = raw.api_key_env || 'PERSONAL_WECHAT_API_KEY';
    raw.central_base_url = raw.central_base_url || API_BASE;
    // 账号与客户名单一律留空：由桥接在本机自动识别，不在安装包里预设任何人
    raw.account_id = '';
    raw.self_names = [];
    raw.self_usernames = [];
    raw.targets = [];
    fs.writeFileSync(target, JSON.stringify(raw, null, 2), 'utf-8');
    appendBridgeLog(`已从模板生成桥接配置: ${target}`);
  }
  try {
    const current = JSON.parse(fs.readFileSync(target, 'utf-8'));
    if (current.instance_id !== instanceId) {
      current.instance_id = instanceId;
      fs.writeFileSync(target, JSON.stringify(current, null, 2), 'utf-8');
    }
  } catch (e) {}
  return target;
}

// 定位 Python 解释器：优先环境变量，其次随包内置运行时，再找 PATH 与常见安装位置。
// 客户机没装 Python 时给出可执行的中文提示，而不是静默失败。
function resolvePython() {
  const explicit = process.env.SALES_AGENT_PYTHON || process.env.VISION_PYTHON;
  if (explicit && fs.existsSync(explicit)) return explicit;

  const bundled = [
    path.join(RESOURCE_ROOT, 'python', 'pythonw.exe'),
    path.join(RESOURCE_ROOT, 'python', 'python.exe'),
  ];
  for (const candidate of bundled) {
    if (fs.existsSync(candidate)) return candidate;
  }

  const probes = ['pythonw.exe', 'python.exe'];
  for (const name of probes) {
    try {
      const r = spawnSync('where', [name], { windowsHide: true, encoding: 'utf-8' });
      if (r.status === 0 && r.stdout) {
        const first = String(r.stdout).split(/\r?\n/).map((s) => s.trim()).filter(Boolean)[0];
        if (first && fs.existsSync(first)) return first;
      }
    } catch (e) {}
  }

  const roots = [
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python'),
    'C:\\',
    process.env.ProgramFiles || 'C:\\Program Files',
    process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)',
  ];
  for (const root of roots) {
    if (!root || !fs.existsSync(root)) continue;
    let dirs = [];
    try {
      dirs = fs.readdirSync(root).filter((n) => /^Python3/i.test(n));
    } catch (e) {
      continue;
    }
    for (const dir of dirs) {
      const exe = path.join(root, dir, 'pythonw.exe');
      if (fs.existsSync(exe)) return exe;
    }
    for (const dir of dirs) {
      const exe = path.join(root, dir, 'python.exe');
      if (fs.existsSync(exe)) return exe;
    }
  }
  return '';
}

function checkBridgeRuntime(python, env) {
  const probe = spawnSync(
    python,
    ['-m', 'wechat_bridge.run', '--version'],
    {
      cwd: RESOURCE_ROOT,
      env,
      windowsHide: true,
      encoding: 'utf-8',
      timeout: 10000,
    }
  );
  const output = String(probe.stdout || '').trim().split(/\r?\n/).filter(Boolean).pop() || '';
  if (probe.error || probe.status !== 0 || output !== BRIDGE_AGENT_VERSION) {
    return {
      ok: false,
      error:
        'Bridge runtime version mismatch. Expected ' +
        BRIDGE_AGENT_VERSION +
        ', got ' +
        (output || 'unknown') +
        '. Reinstall the desktop client.',
    };
  }
  return { ok: true, version: output };
}

function ensureBridgeSecret(python, env) {
  const secretPath = bridgeSecretPath();
  const secretEnv = Object.assign({}, env, {
    WECHAT_BRIDGE_SECRET_VALUE: storedKey,
  });
  const result = spawnSync(
    python,
    ['-m', 'wechat_bridge.secure_store', 'save', '--path', secretPath],
    {
      cwd: RESOURCE_ROOT,
      env: secretEnv,
      windowsHide: true,
      encoding: 'utf-8',
      timeout: 15000,
    }
  );
  if (result.error || result.status !== 0) {
    return {
      ok: false,
      error:
        (result.stderr || result.stdout || result.error || 'secret save failed').trim(),
    };
  }
  return { ok: true, path: secretPath };
}

function installWechatBridgeService(python, configPath, env) {
  const script = path.join(
    RESOURCE_ROOT,
    'deploy',
    'install_wechat_bridge_service.ps1'
  );
  if (!fs.existsSync(script)) {
    return { ok: false, error: 'service installer not found: ' + script };
  }
  const secret = ensureBridgeSecret(python, env);
  if (!secret.ok) return secret;
  const result = spawnSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      script,
      '-ResourceRoot',
      RESOURCE_ROOT,
      '-PythonPath',
      python,
      '-ConfigPath',
      configPath,
      '-SecretFile',
      secret.path,
      '-DataDir',
      bridgeHomeDir(),
      '-InstanceId',
      getOrCreateInstanceId(),
      '-TaskName',
      BRIDGE_TASK_NAME,
    ],
    {
      cwd: RESOURCE_ROOT,
      env,
      windowsHide: true,
      encoding: 'utf-8',
      timeout: 30000,
    }
  );
  if (result.error || result.status !== 0) {
    return {
      ok: false,
      error:
        (result.stderr || result.stdout || result.error || 'service install failed').trim(),
    };
  }
  return { ok: true };
}

function stopWechatBridgeService() {
  const command =
    "Stop-ScheduledTask -TaskName '" +
    BRIDGE_TASK_NAME.replace(/'/g, "''") +
    "' -ErrorAction SilentlyContinue";
  const result = spawnSync(
    'powershell.exe',
    ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command],
    { windowsHide: true, encoding: 'utf-8', timeout: 15000 }
  );
  return { ok: !result.error && result.status === 0 };
}

function readBridgePid() {
  for (const file of [
    path.join(bridgeHomeDir(), 'bridge.pid'),
    path.join(bridgeHomeDir(), 'bridge.lock'),
  ]) {
    try {
      const value = parseInt(fs.readFileSync(file, 'utf-8').trim(), 10);
      if (Number.isFinite(value) && value > 0) return value;
    } catch (e) {}
  }
  return null;
}

function pidAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return false;
  }
}

function clearWechatBridgeRestart() {
  if (wechatBridgeRestartTimer) {
    clearTimeout(wechatBridgeRestartTimer);
    wechatBridgeRestartTimer = null;
  }
  wechatBridgeNextRestartAt = 0;
}

function scheduleWechatBridgeRestart(reason) {
  if (!wechatBridgeDesired || appIsQuitting || wechatBridgeRestartTimer) return;
  const exponent = Math.min(wechatBridgeRestartAttempt, 5);
  const delay = Math.min(30000, 1000 * Math.pow(2, exponent)) + Math.floor(Math.random() * 300);
  wechatBridgeRestartAttempt += 1;
  wechatBridgeNextRestartAt = Date.now() + delay;
  appendBridgeLog(
    `Bridge restart scheduled in ${delay}ms; attempt=${wechatBridgeRestartAttempt}; reason=${reason}`
  );
  wechatBridgeRestartTimer = setTimeout(() => {
    wechatBridgeRestartTimer = null;
    wechatBridgeNextRestartAt = 0;
    const started = startWechatBridge();
    if (!started.ok && wechatBridgeDesired) {
      scheduleWechatBridgeRestart(started.error || 'restart failed');
    }
  }, delay);
}

function startWechatBridge() {
  wechatBridgeDesired = true;
  clearWechatBridgeRestart();
  if (wechatBridgeChild) return { ok: true, already: true };
  if (!storedKey) {
    wechatBridgeDesired = false;
    lastBridgeError = '客户端未登录，请先登录后再开启识别';
    return { ok: false, error: lastBridgeError };
  }
  const configPath = ensureBridgeConfig();
  if (!configPath) {
    wechatBridgeDesired = false;
    lastBridgeError =
      '未找到微信桥接配置模板：' + bridgeTemplatePaths().join(' 或 ');
    return { ok: false, error: lastBridgeError };
  }
  const dataDir = bridgeHomeDir();
  fs.mkdirSync(dataDir, { recursive: true });
  const python = resolvePython();
  if (!python) {
    wechatBridgeDesired = false;
    lastBridgeError =
      '未找到可用的 Python 运行环境。请安装 Python 3.9+ 并确保 pythonw.exe 在 PATH 中，' +
      '或设置环境变量 SALES_AGENT_PYTHON 指向解释器。';
    appendBridgeLog(lastBridgeError);
    return { ok: false, error: lastBridgeError };
  }
  const env = Object.assign({}, process.env, {
    PERSONAL_WECHAT_API_KEY: storedKey,
    WECHAT_BRIDGE_HOME: dataDir,
    WECHAT_BRIDGE_INSTANCE_ID: getOrCreateInstanceId(),
    PYTHONUNBUFFERED: '1',
    PYTHONIOENCODING: 'utf-8',
  });
  const runtimeCheck = checkBridgeRuntime(python, env);
  if (!runtimeCheck.ok) {
    wechatBridgeDesired = false;
    lastBridgeError = runtimeCheck.error;
    appendBridgeLog(lastBridgeError);
    return { ok: false, error: lastBridgeError };
  }
  const serviceInstall = installWechatBridgeService(python, configPath, env);
  if (serviceInstall.ok) {
    wechatBridgeServiceMode = true;
    lastBridgeError = '';
    appendBridgeLog('Bridge service task started: ' + BRIDGE_TASK_NAME);
    return {
      ok: true,
      service: true,
      pid: readBridgePid(),
      version: runtimeCheck.version,
      log: bridgeLogPath(),
    };
  }
  appendBridgeLog(
    'Service mode unavailable, falling back to managed child: ' +
      serviceInstall.error
  );
  const args = ['-m', 'wechat_bridge.run', '--config', configPath];
  appendBridgeLog(`启动桥接: ${python} ${args.join(' ')} (cwd=${RESOURCE_ROOT})`);

  let logFd = null;
  try {
    logFd = fs.openSync(bridgeLogPath(), 'a');
  } catch (e) {
    logFd = null;
  }

  let child = null;
  try {
    child = spawn(python, args, {
      cwd: RESOURCE_ROOT,
      env,
      windowsHide: true,
      stdio: logFd !== null ? ['ignore', logFd, logFd] : 'ignore',
    });
    wechatBridgeChild = child;
  } catch (e) {
    if (logFd !== null) { try { fs.closeSync(logFd); } catch (e2) {} }
    const msg = String((e && e.message) || e);
    lastBridgeError = msg;
    appendBridgeLog('启动失败: ' + msg);
    return { ok: false, error: '启动桥接失败：' + msg };
  }
  if (logFd !== null) { try { fs.closeSync(logFd); } catch (e) {} }

  lastBridgeError = '';
  const startupTimer = setTimeout(() => {
    if (wechatBridgeChild === child && !child.killed) {
      wechatBridgeRestartAttempt = 0;
    }
  }, 15000);
  child.on('error', (err) => {
    lastBridgeError = String((err && err.message) || err);
    appendBridgeLog('Bridge child error: ' + lastBridgeError);
  });
  child.on('exit', (code, signal) => {
    clearTimeout(startupTimer);
    if (wechatBridgeChild !== child) return;
    wechatBridgeChild = null;
    wechatBridgeLastExit = { code, signal, at: new Date().toISOString() };
    appendBridgeLog(`Bridge child exited: code=${code} signal=${signal}`);
    if (code !== 0 && code !== null) {
      lastBridgeError = `桥接进程异常退出（code=${code}），详见 bridge.log`;
    }
    scheduleWechatBridgeRestart(lastBridgeError || `exit:${code}`);
  });
  return {
    ok: true,
    pid: child.pid,
    version: runtimeCheck.version,
    log: bridgeLogPath(),
  };
}

async function reportBridgeOffline(reason) {
  if (!storedKey) return { ok: false };
  try {
    return await apiRequest(
      '/api/v1/personal-wechat/bridge/heartbeat',
      'POST',
      {
        instance_id: getOrCreateInstanceId(),
        account_id: '',
        status: 'offline',
        mode: 'draft',
        last_error: reason || '客户端已停止本机桥接',
      },
      { attempts: 3 }
    );
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) };
  }
}

async function stopWechatBridge() {
  wechatBridgeDesired = false;
  clearWechatBridgeRestart();
  if (wechatBridgeServiceMode) {
    stopWechatBridgeService();
    wechatBridgeServiceMode = false;
  }
  const wasRunning = !!wechatBridgeChild;
  if (wechatBridgeChild) {
    appendBridgeLog('按用户操作停止桥接');
    try { wechatBridgeChild.kill(); } catch (e) {}
    wechatBridgeChild = null;
  }
  // 主动告知中台，避免控制台在 90 秒心跳窗口内继续显示「在线」
  if (wasRunning) await reportBridgeOffline('客户端已停止本机桥接');
  return { ok: true };
}

async function restoreWechatBridgeState() {
  const saved = loadAuth();
  storedKey = saved.key || '';
  isTokenAuth = !!saved.isToken;
  if (!storedKey) return;
  const instanceId = encodeURIComponent(getOrCreateInstanceId());
  const result = await apiRequest(
    `/api/v1/personal-wechat/settings?instance_id=${instanceId}`,
    'GET',
    null,
    { attempts: 3 }
  );
  if (!result.ok) {
    appendBridgeLog(
      'Bridge auto-restore skipped because cloud settings are unavailable: ' +
        (result.data && (result.data.error || result.data.detail) || result.status)
    );
    return;
  }
  const settings = result.data && result.data.settings || {};
  if (settings.recognition_enabled === true) {
    const started = startWechatBridge();
    if (!started.ok) {
      appendBridgeLog('Bridge auto-restore failed: ' + (started.error || 'unknown error'));
    }
  }
}

function wechatBridgeStatus() {
  const configPath = bridgeConfigPath();
  const servicePid = readBridgePid();
  const running =
    (!!wechatBridgeChild && !wechatBridgeChild.killed) ||
    (wechatBridgeServiceMode && pidAlive(servicePid));
  return {
    ok: true,
    desired: wechatBridgeDesired,
    running,
    service_mode: wechatBridgeServiceMode,
    pid: wechatBridgeChild ? wechatBridgeChild.pid : servicePid,
    instance_id: getOrCreateInstanceId(),
    config_path: fs.existsSync(configPath) ? configPath : '',
    last_error: lastBridgeError || '',
    last_exit: wechatBridgeLastExit,
    restart_pending: !!wechatBridgeRestartTimer,
    restart_attempt: wechatBridgeRestartAttempt,
    next_restart_at: wechatBridgeNextRestartAt || null,
    agent_version: BRIDGE_AGENT_VERSION,
    log_path: bridgeLogPath(),
  };
}

ipcMain.handle('auth:login', async (e, key) => {
  storedKey = (key || '').trim();
  isTokenAuth = false;
  const r = await apiRequest('/api/v1/vision/status');
  if (r.ok) {
    saveAuth(storedKey, false);
    return { ok: true, mask: maskKey(storedKey) };
  }
  storedKey = '';
  return { ok: false, error: r.data && (r.data.detail || r.data.error) || 'API Key 无效' };
});

ipcMain.handle('auth:loginAccount', async (e, username, password) => {
  const r = await apiRequest('/api/v1/auth/login', 'POST', { username, password });
  if (r.ok && r.data && r.data.token) {
    storedKey = r.data.token;
    isTokenAuth = true;
    saveAuth(storedKey, true);
    return { ok: true, user: r.data.user || {}, tenant: r.data.tenant || {} };
  }
  return { ok: false, error: (r.data && (r.data.error || r.data.detail)) || '账号或密码错误' };
});

ipcMain.handle('auth:get', async () => {
  const saved = loadAuth();
  storedKey = saved.key || '';
  isTokenAuth = !!saved.isToken;
  if (!storedKey) return { loggedIn: false, mask: '', mode: 'none' };
  const r = await apiRequest('/api/v1/license/status');
  if (r.ok) return { loggedIn: true, mask: maskKey(storedKey), mode: isTokenAuth ? 'token' : 'apikey' };
  if (r.status === 401 || r.status === 403) {
    clearAuth();
    storedKey = '';
    isTokenAuth = false;
    return { loggedIn: false, mask: '', mode: 'none' };
  }
  return {
    loggedIn: true,
    offline: true,
    mask: maskKey(storedKey),
    mode: isTokenAuth ? 'token' : 'apikey',
    error: (r.data && (r.data.error || r.data.detail)) || 'Cloud temporarily unavailable',
  };
});

ipcMain.handle('auth:logout', async () => {
  stopVision();
  await stopWechatBridge();
  storedKey = '';
  clearAuth();
  return { ok: true };
});

ipcMain.handle('api:request', async (e, pathname, method, body) => {
  const saved = storedKey ? { key: storedKey, isToken: isTokenAuth } : loadAuth();
  storedKey = saved.key || '';
  isTokenAuth = !!saved.isToken;
  if (!storedKey) return { ok: false, status: 401, data: { detail: '未登录' } };
  return apiRequest(pathname, method || 'GET', body || null);
});

ipcMain.handle('vision:start', () => startVision());
ipcMain.handle('vision:stop', () => stopVision());
ipcMain.handle('vision:logs', () => tailLog(LOG_FILE));
ipcMain.handle('wechat-bridge:start', () => startWechatBridge());
ipcMain.handle('wechat-bridge:stop', () => stopWechatBridge());
ipcMain.handle('wechat-bridge:status', () => wechatBridgeStatus());
ipcMain.handle('wechat-bridge:instance-id', () => getOrCreateInstanceId());
ipcMain.handle('shell:open', (e, url) => { shell.openExternal(url); return { ok: true }; });

function startLocalServer() {
  const port = 39123;
  const server = http.createServer((req, res) => {
    let pathname = decodeURIComponent((req.url || '/').split('?')[0]);
    if (pathname === '/') pathname = '/console.html';
    const file = path.join(WEB_ROOT, pathname);
    if (!file.startsWith(WEB_ROOT)) { res.writeHead(403); return res.end(); }
    fs.readFile(file, (err, data) => {
      if (err) { res.writeHead(404); return res.end('Not Found'); }
      const ext = path.extname(file);
      const type = { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8' }[ext] || 'application/octet-stream';
      res.writeHead(200, { 'Content-Type': type });
      res.end(data);
    });
  });
  server.listen(port);
  return `http://127.0.0.1:${port}`;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    title: '销售客服智能体 - 中台桌面版',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInSubFrames: true,
      sandbox: false,
      webSecurity: false,
    },
  });
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  if (process.argv.includes('--debug')) mainWindow.webContents.openDevTools();
  mainWindow.on('closed', () => {
    mainWindow = null;
    stopVision();
    stopWechatBridge();
  });
  if (process.argv.includes('--smoke-test')) {
    mainWindow.webContents.on('did-finish-load', () => {
      console.log('SMOKE_OK');
      setTimeout(() => app.quit(), 2500);
    });
  }
}

app.whenReady().then(() => {
  createWindow();
  restoreWechatBridgeState();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  appIsQuitting = true;
  stopVision();
  stopWechatBridge();
  if (process.platform !== 'darwin') app.quit();
});

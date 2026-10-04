<script setup>
import { computed, onMounted, ref } from "vue";

const user = ref(null);
const csrf = ref("");
const username = ref("");
const password = ref("");
const loginError = ref("");
const busy = ref(false);
const page = ref("overview");
const overview = ref({});
const alerts = ref([]);
const blocks = ref([]);
const mangle = ref([]);
const logs = ref([]);
const audit = ref([]);
const settings = ref({});
const search = ref("");
const modal = ref(null);
const toast = ref("");

const pages = [
  ["overview", "Обзор", "◫"],
  ["alerts", "Alerts", "⚠"],
  ["blocks", "Блокировки", "⛔"],
  ["mangle", "Mangle", "⇄"],
  ["logs", "Логи", "≡"],
  ["audit", "Audit", "✓"],
  ["settings", "Настройки", "⚙"],
];

const routerOnline = computed(() => overview.value?.router?.connected === true);

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (csrf.value && options.method && options.method !== "GET") headers["X-CSRF-Token"] = csrf.value;
  const response = await fetch(path, { credentials: "include", ...options, headers });
  if (response.status === 401) {
    user.value = null;
    throw new Error("Требуется авторизация");
  }
  let payload = {};
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) throw new Error(payload.detail || ("HTTP " + response.status));
  return payload;
}

async function login() {
  loginError.value = "";
  busy.value = true;
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: username.value, password: password.value }),
    });
    user.value = data.user;
    csrf.value = data.csrf;
    password.value = "";
    await refreshAll();
  } catch (error) {
    loginError.value = error.message;
  } finally {
    busy.value = false;
  }
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST", body: "{}" }); }
  finally { user.value = null; csrf.value = ""; }
}

async function restoreSession() {
  try {
    const data = await api("/api/auth/me");
    user.value = data.user;
    csrf.value = data.csrf;
    await refreshAll();
  } catch { user.value = null; }
}

async function refreshAll() {
  await Promise.allSettled([loadOverview(), loadAlerts(), loadBlocks(), loadMangle(), loadLogs(), loadAudit(), loadSettings()]);
}

async function loadOverview() { overview.value = await api("/api/overview"); }
async function loadAlerts() {
  const data = await api("/api/alerts?limit=100&q=" + encodeURIComponent(search.value));
  alerts.value = data.items || [];
}
async function loadBlocks() { const data = await api("/api/router/blocks?limit=500"); blocks.value = data.items || []; }
async function loadMangle() { const data = await api("/api/router/mangle"); mangle.value = data.items || []; }
async function loadLogs() {
  const data = await api("/api/logs?limit=250&q=" + encodeURIComponent(search.value));
  logs.value = data.items || [];
}
async function loadAudit() { const data = await api("/api/audit?limit=250"); audit.value = data.items || []; }
async function loadSettings() { settings.value = await api("/api/settings"); }

async function changePage(name) {
  page.value = name;
  if (name === "alerts") await loadAlerts();
  if (name === "blocks") await loadBlocks();
  if (name === "mangle") await loadMangle();
  if (name === "logs") await loadLogs();
  if (name === "audit") await loadAudit();
  if (name === "settings") await loadSettings();
}

async function requestMangle(rule) {
  try {
    const data = await api("/api/router/mangle/" + encodeURIComponent(rule.id) + "/request", {
      method: "POST",
      body: JSON.stringify({ disabled: !rule.disabled }),
    });
    modal.value = {
      kind: "mangle",
      title: rule.disabled ? "Включить правило?" : "Отключить правило?",
      target: data.target,
      detail: rule.chain + " · " + rule.action,
      token: data.token,
      danger: !rule.disabled,
    };
  } catch (error) { showToast(error.message); }
}

async function requestUnblock(entry) {
  try {
    const data = await api("/api/router/unblock/request", {
      method: "POST",
      body: JSON.stringify({ address: entry.address }),
    });
    modal.value = {
      kind: "unblock",
      title: "Снять блокировку?",
      target: data.target,
      detail: entry.comment || "RouterOS address-list",
      token: data.token,
      danger: true,
    };
  } catch (error) { showToast(error.message); }
}

async function confirmAction() {
  const action = modal.value;
  if (!action) return;
  busy.value = true;
  try {
    const endpoint = action.kind === "mangle" ? "/api/router/mangle/confirm" : "/api/router/unblock/confirm";
    await api(endpoint, { method: "POST", body: JSON.stringify({ token: action.token }) });
    if (action.kind === "mangle") await loadMangle();
    else await Promise.all([loadBlocks(), loadOverview()]);
    modal.value = null;
    showToast("Изменение применено");
  } catch (error) { showToast(error.message); }
  finally { busy.value = false; }
}

function showToast(message) {
  toast.value = message;
  window.setTimeout(() => { if (toast.value === message) toast.value = ""; }, 3500);
}

function fmtBytes(value) {
  let n = Number(value || 0);
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return n.toFixed(i ? 1 : 0) + " " + units[i];
}

onMounted(restoreSession);
</script>

<template>
  <div v-if="!user" class="login-shell">
    <div class="login-card">
      <div class="brand-lockup">
        <div class="brand-mark">MC</div>
        <div><h1>Mikro-Clear</h1><p>Security Operations Console</p></div>
      </div>
      <div class="login-copy">
        <span class="eyebrow">CONTROL PLANE</span>
        <h2>Управление без прямого доступа к RouterOS</h2>
        <p>Авторизация, подтверждение write-actions и аудит включены по умолчанию.</p>
      </div>
      <form @submit.prevent="login" class="login-form">
        <label>Пользователь<input v-model="username" autocomplete="username" /></label>
        <label>Пароль<input v-model="password" type="password" autocomplete="current-password" /></label>
        <p v-if="loginError" class="error">{{ loginError }}</p>
        <button class="primary" :disabled="busy">{{ busy ? "Вход..." : "Войти" }}</button>
      </form>
    </div>
  </div>

  <div v-else class="app-shell">
    <aside>
      <div class="sidebar-brand">
        <div class="brand-mark small">MC</div>
        <div><strong>Mikro-Clear</strong><span>Security Console</span></div>
      </div>
      <nav>
        <button v-for="[id, label, icon] in pages" :key="id" :class="{ active: page === id }" @click="changePage(id)">
          <span>{{ icon }}</span>{{ label }}
        </button>
      </nav>
      <div class="sidebar-foot">
        <div class="status-line"><i :class="routerOnline ? 'ok-dot' : 'bad-dot'"></i>RouterOS {{ routerOnline ? "online" : "offline" }}</div>
        <button class="ghost" @click="logout">Выйти</button>
      </div>
    </aside>

    <main>
      <header>
        <div><span class="eyebrow">MIKROTIK · SURICATA · TELEGRAM</span><h1>{{ pages.find(([id]) => id === page)?.[1] }}</h1></div>
        <div class="header-actions">
          <span v-if="overview.monitor_only" class="badge warning">MONITOR ONLY</span>
          <button class="ghost" @click="refreshAll">Обновить</button>
        </div>
      </header>

      <section v-if="page === 'overview'">
        <div class="cards">
          <article class="metric"><span>RouterOS</span><strong>{{ routerOnline ? "Online" : "Offline" }}</strong><small>{{ overview.router?.board_name || "—" }} · {{ overview.router?.version || "—" }}</small></article>
          <article class="metric"><span>CPU Router</span><strong>{{ overview.router?.cpu_load ?? "—" }}%</strong><small>uptime {{ overview.router?.uptime || "—" }}</small></article>
          <article class="metric"><span>Blocked IP</span><strong>{{ overview.blocked_count ?? "—" }}</strong><small>address-list Suricata</small></article>
          <article class="metric"><span>Control plane</span><strong>{{ overview.mangle_control_enabled ? "Enabled" : "Read only" }}</strong><small>write-actions require confirmation</small></article>
        </div>
        <div class="panel-grid">
          <article class="panel">
            <div class="panel-title"><h3>Последние события IDS</h3><button class="link" @click="changePage('alerts')">Все alerts</button></div>
            <div class="event-list">
              <div v-for="item in alerts.slice(0, 8)" :key="item.timestamp + '-' + item.signature_id" class="event-row">
                <span :class="['severity', 's' + item.severity]">S{{ item.severity }}</span>
                <div><strong>{{ item.signature }}</strong><small>{{ item.src_ip }} → {{ item.dest_ip }} · SID {{ item.signature_id }}</small></div>
                <time>{{ item.timestamp?.slice(11, 19) }}</time>
              </div>
              <p v-if="!alerts.length" class="empty">Нет доступных alert-событий.</p>
            </div>
          </article>
          <article class="panel">
            <div class="panel-title"><h3>Интеграции</h3></div>
            <div class="integration-list">
              <div><span>Telegram</span><b :class="overview.telegram_enabled ? 'good' : 'muted'">{{ overview.telegram_enabled ? "ON" : "OFF" }}</b></div>
              <div><span>Mangle Control</span><b :class="overview.mangle_control_enabled ? 'good' : 'muted'">{{ overview.mangle_control_enabled ? "ON" : "OFF" }}</b></div>
              <div><span>Parental Control</span><b :class="overview.parental_control_enabled ? 'good' : 'muted'">{{ overview.parental_control_enabled ? "ON" : "OFF" }}</b></div>
              <div><span>Pi-hole</span><b :class="overview.pihole_enabled ? 'good' : 'muted'">{{ overview.pihole_enabled ? "ON" : "OFF" }}</b></div>
            </div>
          </article>
        </div>
      </section>

      <section v-else-if="page === 'alerts'" class="panel">
        <div class="toolbar"><input v-model="search" placeholder="IP, SID, signature, category..." @keyup.enter="loadAlerts" /><button @click="loadAlerts">Поиск</button></div>
        <div class="table-wrap"><table>
          <thead><tr><th>Severity</th><th>Время</th><th>Источник</th><th>Назначение</th><th>Сигнатура</th><th>SID</th></tr></thead>
          <tbody><tr v-for="item in alerts" :key="item.timestamp + '-' + item.signature_id + '-' + item.src_ip">
            <td><span :class="['severity', 's' + item.severity]">S{{ item.severity }}</span></td>
            <td class="mono">{{ item.timestamp }}</td><td class="mono">{{ item.src_ip }}:{{ item.src_port || "—" }}</td>
            <td class="mono">{{ item.dest_ip }}:{{ item.dest_port || "—" }}</td><td><strong>{{ item.signature }}</strong><small>{{ item.category }}</small></td><td class="mono">{{ item.signature_id }}</td>
          </tr></tbody>
        </table></div>
      </section>

      <section v-else-if="page === 'blocks'" class="panel">
        <div class="panel-title"><h3>RouterOS address-list</h3><span class="badge">{{ blocks.length }} entries</span></div>
        <div class="table-wrap"><table>
          <thead><tr><th>IP</th><th>Комментарий</th><th>Timeout</th><th>Тип</th><th></th></tr></thead>
          <tbody><tr v-for="item in blocks" :key="item.id">
            <td class="mono">{{ item.address }}</td><td>{{ item.comment || "—" }}</td><td class="mono">{{ item.timeout || "—" }}</td>
            <td><span class="badge subtle">{{ item.dynamic ? "dynamic" : "static" }}</span></td><td class="actions"><button class="danger-outline" @click="requestUnblock(item)">Unblock</button></td>
          </tr></tbody>
        </table></div>
      </section>

      <section v-else-if="page === 'mangle'" class="panel">
        <div class="panel-title"><div><h3>Managed Mangle</h3><p>Только правила с разрешённым comment prefix, chain и action.</p></div></div>
        <div class="rule-grid">
          <article v-for="rule in mangle" :key="rule.id" class="rule-card">
            <div><span :class="rule.disabled ? 'bad-dot' : 'ok-dot'"></span><strong>{{ rule.name }}</strong></div>
            <dl><dt>Chain</dt><dd>{{ rule.chain }}</dd><dt>Action</dt><dd>{{ rule.action }}</dd><dt>Packets</dt><dd>{{ rule.packets }}</dd><dt>Traffic</dt><dd>{{ fmtBytes(rule.bytes) }}</dd></dl>
            <button :class="rule.disabled ? 'primary' : 'danger-outline'" @click="requestMangle(rule)">{{ rule.disabled ? "Enable" : "Disable" }}</button>
          </article>
          <p v-if="!mangle.length" class="empty">Нет управляемых Mangle-правил или модуль отключён.</p>
        </div>
      </section>

      <section v-else-if="page === 'logs'" class="panel">
        <div class="toolbar"><input v-model="search" placeholder="Фильтр по тексту..." @keyup.enter="loadLogs" /><button @click="loadLogs">Фильтр</button></div>
        <pre class="log-view"><code v-for="(line, i) in logs" :key="i">{{ line }}\n</code></pre>
      </section>

      <section v-else-if="page === 'audit'" class="panel">
        <div class="table-wrap"><table>
          <thead><tr><th>Время</th><th>Action</th><th>Outcome</th><th>User</th><th>Target</th><th>Detail</th></tr></thead>
          <tbody><tr v-for="(item, i) in audit" :key="i"><td class="mono">{{ item.timestamp }}</td><td>{{ item.action }}</td><td><span class="badge subtle">{{ item.outcome }}</span></td><td>{{ item.user_id }}</td><td class="mono">{{ item.target }}</td><td>{{ item.detail }}</td></tr></tbody>
        </table></div>
      </section>

      <section v-else-if="page === 'settings'" class="settings-grid">
        <article v-for="(group, name) in settings" :key="name" class="panel">
          <div class="panel-title"><h3>{{ name }}</h3></div>
          <dl v-if="typeof group === 'object' && group !== null" class="settings-list">
            <template v-for="(value, key) in group" :key="key"><dt>{{ key }}</dt><dd>{{ Array.isArray(value) ? value.join(", ") : value }}</dd></template>
          </dl>
          <div v-else class="settings-value">{{ group }}</div>
        </article>
      </section>
    </main>

    <div v-if="modal" class="modal-backdrop" @click.self="modal = null">
      <div class="modal">
        <span class="eyebrow">CONFIRM WRITE ACTION</span><h2>{{ modal.title }}</h2>
        <div class="target-box"><strong>{{ modal.target }}</strong><small>{{ modal.detail }}</small></div>
        <p>Backend повторно проверит объект RouterOS. Токен подтверждения одноразовый и короткоживущий.</p>
        <div class="modal-actions"><button class="ghost" @click="modal = null">Отмена</button><button :class="modal.danger ? 'danger' : 'primary'" :disabled="busy" @click="confirmAction">Подтвердить</button></div>
      </div>
    </div>
    <div v-if="toast" class="toast">{{ toast }}</div>
  </div>
</template>

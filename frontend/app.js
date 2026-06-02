const API_HOST = window.location.hostname || "localhost";
const API_PROTOCOL = window.location.protocol === "https:" ? "https:" : "http:";
const IS_LOCAL_API_HOST = ["localhost", "127.0.0.1", ""].includes(API_HOST);
const API = IS_LOCAL_API_HOST
  ? {
    auth: `${API_PROTOCOL}//${API_HOST}:8001`,
    session: `${API_PROTOCOL}//${API_HOST}:8002`,
    tickets: `${API_PROTOCOL}//${API_HOST}:8003`,
    news: `${API_PROTOCOL}//${API_HOST}:8004`,
    notifications: `${API_PROTOCOL}//${API_HOST}:8005`,
  }
  : {
    auth: "/api/auth",
    session: "/api/session",
    tickets: "/api/tickets",
    news: "/api/news",
    notifications: "/api/notifications",
  };

const STORAGE_KEY = "zheu.auth";
const BROWSER_NOTIFICATION_SETTING_KEY = "zheu.browserNotifications";
const NOTIFICATION_POLL_INTERVAL_MS = 15000;
const STATUS_LABELS = {
  CREATED: "Создана",
  IN_PROGRESS: "В работе",
  DONE: "Выполнена",
  CANCELLED: "Отменена",
};
const CATEGORY_LABELS = {
  plumber: "Сантехник",
  electrician: "Электрик",
};
const ROLE_LABELS = {
  MINIMAL: "Минимум",
  RESIDENT: "Житель",
  WORKER: "Рабочий",
  ADMIN: "Админ",
};
const WORKER_STATUS_OPTIONS = {
  CREATED: ["CREATED", "IN_PROGRESS", "CANCELLED"],
  IN_PROGRESS: ["IN_PROGRESS", "DONE", "CANCELLED"],
  DONE: ["DONE"],
  CANCELLED: ["CANCELLED"],
};
const BROWSER_NOTIFICATION_FSM = {
  UNSUPPORTED: "UNSUPPORTED",
  DENIED: "DENIED",
  OFF: "OFF",
  WAITING_PERMISSION: "WAITING_PERMISSION",
  READY: "READY",
};

const state = {
  tokens: loadTokens(),
  context: null,
  activeSection: null,
  addresses: [],
  news: [],
  myTickets: [],
  workerTickets: [],
  workerTicketFilter: "CREATED",
  notifications: [],
  notificationKnownIds: new Set(),
  notificationsInitialized: false,
  browserNotificationsEnabled: loadBrowserNotificationsEnabled(),
  notificationPollId: null,
  users: [],
};

let refreshPromise = null;

const els = {
  authView: document.querySelector("#authView"),
  appView: document.querySelector("#appView"),
  userSummary: document.querySelector("#userSummary"),
  statusLine: document.querySelector("#statusLine"),
  logoutBtn: document.querySelector("#logoutBtn"),
  refreshBtn: document.querySelector("#refreshBtn"),
  sectionTabs: document.querySelector("#sectionTabs"),
  newsSection: document.querySelector("#newsSection"),
  residentSection: document.querySelector("#residentSection"),
  workerSection: document.querySelector("#workerSection"),
  adminSection: document.querySelector("#adminSection"),
  newsList: document.querySelector("#newsList"),
  myTicketsList: document.querySelector("#myTicketsList"),
  workerTicketsList: document.querySelector("#workerTicketsList"),
  workerStatusFilter: document.querySelector("#workerStatusFilter"),
  notificationsList: document.querySelector("#notificationsList"),
  browserNotificationsEnabled: document.querySelector("#browserNotificationsEnabled"),
  usersList: document.querySelector("#usersList"),
  registerAddresses: document.querySelector("#registerAddresses"),
  ticketAddress: document.querySelector("#ticketAddress"),
};

document.querySelector("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget));
  await runAction(() => login(data.login, data.password), "Вход выполнен");
});

document.querySelector("#registerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const data = Object.fromEntries(formData);
  data.address_ids = formData.getAll("address_ids").filter(Boolean);
  await runAction(async () => {
    await request("auth", "/register", { method: "POST", body: data });
    await login(data.login, data.password);
    form.reset();
  }, "Регистрация выполнена");
});

document.querySelectorAll(".quick-logins button").forEach((button) => {
  button.addEventListener("click", async () => {
    await runAction(
      () => login(button.dataset.login, button.dataset.password),
      `Вход: ${button.textContent}`,
    );
  });
});

document.querySelector("#ticketForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  await runAction(async () => {
    await request("tickets", "/tickets", { method: "POST", body: data, auth: true });
    form.reset();
    await refreshData();
  }, "Заявка создана");
});

document.querySelector("#newsForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  await runAction(async () => {
    await request("news", "/news", { method: "POST", body: data, auth: true });
    form.reset();
    await refreshData();
  }, "Новость опубликована");
});

document.querySelector("#addressForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  data.floor = data.floor ? Number(data.floor) : null;
  await runAction(async () => {
    await request("auth", "/addresses", { method: "POST", body: dropEmpty(data), auth: true });
    form.reset();
    await refreshData();
  }, "Адрес добавлен");
});

document.querySelector("#readAllBtn").addEventListener("click", async () => {
  await runAction(async () => {
    await request("notifications", "/notifications/read-all", { method: "PATCH", auth: true });
    await refreshData();
  }, "Уведомления отмечены");
});

els.browserNotificationsEnabled.addEventListener("change", async (event) => {
  const enabled = event.target.checked;
  await runAction(async () => {
    if (enabled && !(await ensureBrowserNotificationPermission())) {
      state.browserNotificationsEnabled = false;
      saveBrowserNotificationsEnabled(false);
      renderNotificationSettings();
      throw new Error("Не удалось включить браузерные уведомления");
    } else {
      state.browserNotificationsEnabled = enabled;
    }
    saveBrowserNotificationsEnabled(state.browserNotificationsEnabled);
    renderNotificationSettings();
  }, enabled ? "Браузерные уведомления включены" : "Браузерные уведомления выключены");
});

els.workerTicketsList.addEventListener("submit", async (event) => {
  if (!event.target.matches(".status-form")) return;
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  await runAction(async () => {
    await request("tickets", `/tickets/${form.dataset.ticketId}/status`, {
      method: "PATCH",
      body: { status: data.status },
      auth: true,
    });
    await refreshData();
  }, "Статус обновлен");
});

els.workerStatusFilter.addEventListener("change", async (event) => {
  state.workerTicketFilter = event.target.value;
  await runAction(refreshWorkerTickets, "Фильтр применен");
});

els.myTicketsList.addEventListener("submit", async (event) => {
  if (!event.target.matches(".rate-form")) return;
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  await runAction(async () => {
    await request("tickets", `/tickets/${form.dataset.ticketId}/rate`, {
      method: "POST",
      body: { value: Number(data.value), comment: data.comment || null },
      auth: true,
    });
    await refreshData();
  }, "Оценка сохранена");
});

els.myTicketsList.addEventListener("submit", async (event) => {
  if (!event.target.matches(".cancel-form")) return;
  event.preventDefault();
  const form = event.target;
  if (!window.confirm("Отменить заявку?")) return;
  await runAction(async () => {
    await request("tickets", `/tickets/${form.dataset.ticketId}/cancel`, {
      method: "PATCH",
      auth: true,
    });
    await refreshData();
  }, "Заявка отменена");
});

els.usersList.addEventListener("submit", async (event) => {
  if (!event.target.matches(".role-form")) return;
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  await runAction(async () => {
    await request("auth", "/assign-role", {
      method: "POST",
      body: { user_id: form.dataset.userId, role_name: data.role_name },
      auth: true,
    });
    await refreshData();
  }, "Роль назначена");
});

els.sectionTabs.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-section]");
  if (!button) return;
  state.activeSection = button.dataset.section;
  render();
});

els.logoutBtn.addEventListener("click", () => {
  clearTokens();
  state.context = null;
  state.activeSection = null;
  resetNotificationTracking();
  stopNotificationPolling();
  setStatus("Вы вышли из системы");
  render();
});

els.refreshBtn.addEventListener("click", async () => {
  await runAction(refreshData, "Данные обновлены");
});

await init();

async function init() {
  try {
    await loadAddresses();
  } catch (error) {
    setStatus(error.message, "error");
  }

  if (state.tokens?.access_token) {
    try {
      state.context = await validateSession();
      await refreshData();
      startNotificationPolling();
    } catch (error) {
      clearTokens();
      setStatus(error.message, "error");
    }
  }
  render();
}

async function login(loginValue, password) {
  const tokens = await request("auth", "/login", {
    method: "POST",
    body: { login: loginValue, password },
  });
  state.tokens = tokens;
  saveTokens(tokens);
  state.context = await validateSession();
  state.activeSection = null;
  resetNotificationTracking();
  await refreshData();
  startNotificationPolling();
}

async function validateSession() {
  return request("session", "/validate", {
    method: "POST",
    body: { access_token: state.tokens.access_token },
  });
}

async function refreshData() {
  if (!state.context) return;
  const permissions = new Set(state.context.permissions);
  const tasks = [
    request("news", "/news").then((items) => {
      state.news = items;
    }),
    loadAddresses(),
  ];

  if (permissions.has("VIEW_OWN_TICKETS")) {
    tasks.push(
      request("tickets", "/tickets/me", { auth: true }).then((items) => {
        state.myTickets = items;
      }),
    );
  } else {
    state.myTickets = [];
  }

  if (permissions.has("VIEW_TICKETS_BY_ADDRESS")) {
    tasks.push(
      request("tickets", workerTicketsPath(), { auth: true }).then((items) => {
        state.workerTickets = items;
      }),
    );
  } else {
    state.workerTickets = [];
  }

  if (permissions.has("MANAGE_PERMISSIONS")) {
    tasks.push(
      request("auth", "/users", { auth: true }).then((items) => {
        state.users = items;
      }),
    );
  } else {
    state.users = [];
  }

  tasks.push(
    request("notifications", "/notifications/me", { auth: true }).then((items) => {
      state.notifications = items;
      processFetchedNotifications(items);
    }),
  );

  await Promise.all(tasks);
  render();
}

async function request(service, path, options = {}) {
  return requestOnce(service, path, options, true);
}

async function requestOnce(service, path, options = {}, allowRefresh = true) {
  const headers = new Headers(options.headers || {});
  const init = {
    method: options.method || "GET",
    headers,
  };

  if (options.auth) {
    if (!state.tokens?.access_token) throw new Error("Нет активной сессии");
    headers.set("Authorization", `Bearer ${state.tokens.access_token}`);
  }

  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(options.body);
  }

  const response = await fetch(`${API[service]}${path}`, init);
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { detail: text };
  }

  if (!response.ok) {
    if (response.status === 401 && options.auth && allowRefresh && (await refreshTokens())) {
      return requestOnce(service, path, options, false);
    }
    throw new Error(formatApiError(payload, response.status));
  }

  return payload;
}

async function refreshTokens() {
  if (!state.tokens?.refresh_token) return false;

  refreshPromise ||= refreshTokensOnce().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

async function refreshTokensOnce() {
  const refreshToken = state.tokens?.refresh_token;
  if (!refreshToken) return false;

  try {
    const tokens = await requestOnce(
      "auth",
      "/refresh",
      {
        method: "POST",
        body: { refresh_token: refreshToken },
      },
      false,
    );
    state.tokens = tokens;
    saveTokens(tokens);
    state.context = await validateSession();
    return true;
  } catch {
    clearTokens();
    state.context = null;
    resetNotificationTracking();
    stopNotificationPolling();
    return false;
  }
}

async function loadAddresses() {
  state.addresses = await request("auth", "/addresses");
}

async function runAction(action, successMessage) {
  setBusy(true);
  setStatus("");
  try {
    await action();
    if (successMessage) setStatus(successMessage, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
    render();
  }
}

function render() {
  const isLoggedIn = Boolean(state.context);
  els.authView.hidden = isLoggedIn;
  els.appView.hidden = !isLoggedIn;
  els.logoutBtn.hidden = !isLoggedIn;
  renderRegisterAddresses();

  if (!isLoggedIn) {
    els.userSummary.textContent = "Войдите в систему";
    return;
  }

  els.userSummary.textContent = `${state.context.login} · ${formatRoles(state.context.roles)}`;

  const sections = availableSections();
  if (!state.activeSection || !sections.some((section) => section.id === state.activeSection)) {
    state.activeSection = sections[0]?.id || null;
  }

  renderTabs(sections);
  renderNews();
  renderAddresses();
  renderResident();
  renderWorker();
  renderAdmin();

  for (const section of [els.newsSection, els.residentSection, els.workerSection, els.adminSection]) {
    section.hidden = section.id !== `${state.activeSection}Section`;
  }
}

function availableSections() {
  const permissions = new Set(state.context?.permissions || []);
  const sections = [];
  if (permissions.has("VIEW_NEWS")) sections.push({ id: "news", label: "Новости" });
  if (permissions.has("CREATE_TICKET") || permissions.has("VIEW_OWN_TICKETS")) {
    sections.push({ id: "resident", label: "Житель" });
  }
  if (permissions.has("VIEW_TICKETS_BY_ADDRESS") || permissions.has("CHANGE_TICKET_STATUS")) {
    sections.push({ id: "worker", label: "Рабочий" });
  }
  if (permissions.has("CREATE_NEWS") || permissions.has("MANAGE_PERMISSIONS")) {
    sections.push({ id: "admin", label: "Админ" });
  }
  return sections;
}

function renderTabs(sections) {
  els.sectionTabs.innerHTML = sections
    .map(
      (section) => `
        <button class="${section.id === state.activeSection ? "active" : ""}" data-section="${section.id}" type="button">
          ${section.label}
        </button>
      `,
    )
    .join("");
}

function renderNews() {
  els.newsList.innerHTML = state.news.length
    ? state.news.map((item) => itemTemplate(item.title, item.content, formatDate(item.published_at))).join("")
    : emptyTemplate("Новостей нет");
}

function renderRegisterAddresses() {
  if (!els.registerAddresses) return;

  els.registerAddresses.innerHTML = state.addresses.length
    ? state.addresses.map((address) => `<option value="${address.id}">${escapeHtml(addressLabel(address))}</option>`).join("")
    : `<option value="" disabled>Адресов нет</option>`;
  els.registerAddresses.disabled = state.addresses.length === 0;
}

function renderAddresses() {
  const addresses = residentAddresses();
  els.ticketAddress.innerHTML = addresses.length
    ? addresses.map((address) => `<option value="${address.id}">${escapeHtml(addressLabel(address))}</option>`).join("")
    : `<option value="" disabled selected>Адресов нет</option>`;
  els.ticketAddress.disabled = addresses.length === 0;
}

function renderResident() {
  els.myTicketsList.innerHTML = state.myTickets.length
    ? state.myTickets.map(renderMyTicket).join("")
    : emptyTemplate("Заявок нет");

  els.notificationsList.innerHTML = state.notifications.length
    ? state.notifications.map(renderNotification).join("")
    : emptyTemplate("Уведомлений нет");

  renderNotificationSettings();
}

function renderWorker() {
  els.workerStatusFilter.value = state.workerTicketFilter;
  els.workerTicketsList.innerHTML = state.workerTickets.length
    ? state.workerTickets.map(renderWorkerTicket).join("")
    : emptyTemplate(workerEmptyMessage());
}

function renderAdmin() {
  els.usersList.innerHTML = state.users.length
    ? state.users.map(renderUser).join("")
    : emptyTemplate("Пользователей нет");
}

function renderMyTicket(ticket) {
  const rating = ticket.status === "DONE"
    ? ticket.rating_value
      ? `
      <div class="rating-result">
        Оценка: <strong>${ticket.rating_value}</strong> из 5
      </div>
    `
      : `
      <form class="rate-form" data-ticket-id="${ticket.id}">
        <label>
          Оценка
          <select name="value">
            ${[1, 2, 3, 4, 5].map((value) => `<option value="${value}" ${ticket.rating_value === value ? "selected" : ""}>${value}</option>`).join("")}
          </select>
        </label>
        <label>
          Комментарий
          <input name="comment" />
        </label>
        <button type="submit">Оценить</button>
      </form>
    `
    : "";
  const cancelAction = ["CREATED", "IN_PROGRESS"].includes(ticket.status)
    ? `
      <form class="cancel-form" data-ticket-id="${ticket.id}">
        <button class="secondary" type="submit">Отменить заявку</button>
      </form>
    `
    : "";

  return `
    <article class="item">
      <div class="item-row">
        <div>
          <div class="item-title">${escapeHtml(ticket.title)}</div>
          <div class="muted">${escapeHtml(CATEGORY_LABELS[ticket.category] || ticket.category)} · ${escapeHtml(addressById(ticket.address_id))}</div>
        </div>
        ${statusBadge(ticket.status)}
      </div>
      <p>${escapeHtml(ticket.description)}</p>
      <div class="muted">Создана: ${formatDate(ticket.created_at)}</div>
      ${cancelAction}
      ${rating}
    </article>
  `;
}

function renderWorkerTicket(ticket) {
  return `
    <article class="item">
      <div class="item-row">
        <div>
          <div class="item-title">${escapeHtml(ticket.title)}</div>
          <div class="muted">${escapeHtml(CATEGORY_LABELS[ticket.category] || ticket.category)} · ${escapeHtml(addressById(ticket.address_id))}</div>
        </div>
        ${statusBadge(ticket.status)}
      </div>
      <p>${escapeHtml(ticket.description)}</p>
      <form class="status-form inline-form" data-ticket-id="${ticket.id}">
        <label>
          Статус
          <select name="status">
            ${statusOptionsForWorker(ticket.status).map((value) => `<option value="${value}" ${ticket.status === value ? "selected" : ""}>${STATUS_LABELS[value]}</option>`).join("")}
          </select>
        </label>
        <button type="submit">Сохранить</button>
      </form>
    </article>
  `;
}

function renderNotification(notification) {
  return `
    <article class="item">
      <div class="item-row">
        <div class="item-title">${escapeHtml(notification.message)}</div>
        <span class="badge">${notification.is_read ? "Прочитано" : "Новое"}</span>
      </div>
      <div class="muted">${formatDate(notification.created_at)}</div>
    </article>
  `;
}

function renderUser(user) {
  const selectedRole = mainRole(user.roles);
  return `
    <article class="item">
      <div class="item-row">
        <div>
          <div class="item-title">${escapeHtml(user.full_name)}</div>
          <div class="muted">${escapeHtml(user.login)} · ${escapeHtml(user.email)} · ${escapeHtml(formatRoles(user.roles))}</div>
        </div>
      </div>
      <form class="role-form user-actions" data-user-id="${user.id}">
        <label>
          Роль
          <select name="role_name">
            ${Object.entries(ROLE_LABELS).map(([value, label]) => `<option value="${value}" ${value === selectedRole ? "selected" : ""}>${label}</option>`).join("")}
          </select>
        </label>
        <button type="submit">Назначить</button>
      </form>
    </article>
  `;
}

function statusOptionsForWorker(status) {
  return WORKER_STATUS_OPTIONS[status] || [status];
}

async function refreshWorkerTickets() {
  if (!state.context?.permissions.includes("VIEW_TICKETS_BY_ADDRESS")) return;
  state.workerTickets = await request("tickets", workerTicketsPath(), { auth: true });
  renderWorker();
}

function workerTicketsPath() {
  if (state.workerTicketFilter === "ALL") return "/tickets/worker";
  return `/tickets/worker?status=${encodeURIComponent(state.workerTicketFilter)}`;
}

function workerEmptyMessage() {
  if (state.workerTicketFilter === "ALL") return "Заявок нет";
  return `Заявок со статусом "${STATUS_LABELS[state.workerTicketFilter]}" нет`;
}

function mainRole(roles) {
  return roles.find((role) => role !== "MINIMAL") || "MINIMAL";
}

function formatRoles(roles) {
  const businessRoles = roles.filter((role) => role !== "MINIMAL");
  const visibleRoles = businessRoles.length ? businessRoles : roles;
  return visibleRoles.map((role) => ROLE_LABELS[role] || role).join(", ");
}

async function refreshNotificationsOnly() {
  if (!state.context || !state.tokens?.access_token) return;
  try {
    const items = await request("notifications", "/notifications/me", { auth: true });
    state.notifications = items;
    processFetchedNotifications(items);
    if (state.activeSection === "resident") renderResident();
  } catch {
    stopNotificationPolling();
  }
}

function startNotificationPolling() {
  stopNotificationPolling();
  if (!state.context) return;
  state.notificationPollId = window.setInterval(refreshNotificationsOnly, NOTIFICATION_POLL_INTERVAL_MS);
}

function stopNotificationPolling() {
  if (state.notificationPollId) {
    window.clearInterval(state.notificationPollId);
    state.notificationPollId = null;
  }
}

function resetNotificationTracking() {
  state.notificationKnownIds = new Set();
  state.notificationsInitialized = false;
}

function processFetchedNotifications(items) {
  if (!state.notificationsInitialized) {
    state.notificationKnownIds = new Set(items.map((item) => item.id));
    state.notificationsInitialized = true;
    return;
  }

  const freshItems = items.filter((item) => !state.notificationKnownIds.has(item.id));
  for (const item of freshItems) {
    state.notificationKnownIds.add(item.id);
  }

  if (
    getBrowserNotificationFsm() !== BROWSER_NOTIFICATION_FSM.READY ||
    !state.context?.roles.includes("RESIDENT")
  ) {
    return;
  }

  freshItems.reverse().forEach(showBrowserNotification);
}

function showBrowserNotification(notification) {
  const title = {
    TICKET_CREATED: "Заявка создана",
    TICKET_STATUS_CHANGED: "Статус заявки изменен",
    NEWS_CREATED: "Новая новость",
  }[notification.type] || "Уведомление ЖЭУ";

  new Notification(title, {
    body: notification.message,
    tag: notification.id,
  });
}

async function ensureBrowserNotificationPermission() {
  if (!browserNotificationsSupported()) {
    state.browserNotificationsEnabled = false;
    saveBrowserNotificationsEnabled(false);
    setStatus("Браузер не поддерживает уведомления", "error");
    return false;
  }

  if (Notification.permission === "denied") {
    state.browserNotificationsEnabled = false;
    saveBrowserNotificationsEnabled(false);
    setStatus("Уведомления заблокированы в настройках браузера", "error");
    return false;
  }

  if (Notification.permission === "default") {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      state.browserNotificationsEnabled = false;
      saveBrowserNotificationsEnabled(false);
      return false;
    }
  }

  return true;
}

function renderNotificationSettings() {
  if (!els.browserNotificationsEnabled) return;

  const fsmState = getBrowserNotificationFsm();
  els.browserNotificationsEnabled.checked = fsmState === BROWSER_NOTIFICATION_FSM.READY;
  els.browserNotificationsEnabled.disabled = [
    BROWSER_NOTIFICATION_FSM.UNSUPPORTED,
    BROWSER_NOTIFICATION_FSM.DENIED,
  ].includes(fsmState);
}

function getBrowserNotificationFsm() {
  if (!browserNotificationsSupported()) return BROWSER_NOTIFICATION_FSM.UNSUPPORTED;
  if (Notification.permission === "denied") return BROWSER_NOTIFICATION_FSM.DENIED;
  if (!state.browserNotificationsEnabled) return BROWSER_NOTIFICATION_FSM.OFF;
  if (Notification.permission !== "granted") return BROWSER_NOTIFICATION_FSM.WAITING_PERMISSION;
  return BROWSER_NOTIFICATION_FSM.READY;
}

function browserNotificationsSupported() {
  return "Notification" in window;
}

function itemTemplate(title, content, meta) {
  return `
    <article class="item">
      <div class="item-title">${escapeHtml(title)}</div>
      <p>${escapeHtml(content)}</p>
      <div class="muted">${escapeHtml(meta)}</div>
    </article>
  `;
}

function emptyTemplate(text) {
  return `<div class="empty">${escapeHtml(text)}</div>`;
}

function statusBadge(status) {
  return `<span class="badge ${status}">${escapeHtml(STATUS_LABELS[status] || status)}</span>`;
}

function residentAddresses() {
  if (!Array.isArray(state.context?.address_ids)) return state.addresses;
  const linkedAddressIds = new Set(state.context.address_ids);
  return state.addresses.filter((address) => linkedAddressIds.has(address.id));
}

function addressById(id) {
  const address = state.addresses.find((item) => item.id === id);
  return address ? addressLabel(address) : "адрес не найден";
}

function addressLabel(address) {
  const parts = [`дом ${address.building}`, `кв. ${address.apartment}`];
  if (address.entrance) parts.push(`подъезд ${address.entrance}`);
  if (address.floor) parts.push(`этаж ${address.floor}`);
  if (address.room) parts.push(address.room);
  return parts.join(", ");
}

function formatDate(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function dropEmpty(data) {
  return Object.fromEntries(Object.entries(data).filter(([, value]) => value !== ""));
}

function formatApiError(payload, status) {
  const detail = payload?.detail;
  if (Array.isArray(detail)) {
    return detail.map(formatValidationIssue).join("; ");
  }
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (detail && typeof detail === "object") {
    return JSON.stringify(detail);
  }
  return `Ошибка ${status}`;
}

function formatValidationIssue(issue) {
  if (typeof issue === "string") return issue;
  if (!issue || typeof issue !== "object") return "Ошибка валидации";

  const field = validationFieldLabel(issue.loc);
  const message = validationMessage(issue);
  return field ? `${field}: ${message}` : message;
}

function validationFieldLabel(loc) {
  const labels = {
    full_name: "ФИО",
    login: "Логин",
    email: "Email",
    password: "Пароль",
    address_ids: "Адреса",
    title: "Тема",
    description: "Описание",
    category: "Категория",
    address_id: "Адрес",
  };
  const parts = Array.isArray(loc) ? loc.filter((part) => part !== "body" && typeof part !== "number") : [];
  const key = parts.find((part) => labels[part]) || parts.at(-1);
  return labels[key] || key || "";
}

function validationMessage(issue) {
  const minLength = issue.ctx?.min_length;
  const maxLength = issue.ctx?.max_length;

  if (issue.type === "string_too_short" && minLength) {
    return `минимум ${minLength} символа`;
  }
  if (issue.type === "string_too_long" && maxLength) {
    return `максимум ${maxLength} символов`;
  }
  if (issue.type === "missing") {
    return "обязательное поле";
  }
  if (issue.type === "value_error") {
    return "некорректное значение";
  }
  return issue.msg || "ошибка валидации";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setBusy(isBusy) {
  document.querySelectorAll("button, input, select, textarea").forEach((element) => {
    element.disabled = isBusy;
  });
  els.logoutBtn.disabled = false;
  els.refreshBtn.disabled = false;
}

function setStatus(message, type = "") {
  els.statusLine.textContent = message;
  els.statusLine.className = `status ${type}`.trim();
}

function saveTokens(tokens) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens));
}

function loadTokens() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

function clearTokens() {
  localStorage.removeItem(STORAGE_KEY);
  state.tokens = null;
}

function saveBrowserNotificationsEnabled(enabled) {
  localStorage.setItem(BROWSER_NOTIFICATION_SETTING_KEY, JSON.stringify(enabled));
}

function loadBrowserNotificationsEnabled() {
  try {
    return JSON.parse(localStorage.getItem(BROWSER_NOTIFICATION_SETTING_KEY)) === true;
  } catch {
    return false;
  }
}

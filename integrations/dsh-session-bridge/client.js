// dsh-session-bridge（client 半）
//
// 运行在 DSH 页面里，读取渲染层的会话状态并 POST 给桌宠：
//   sessions.list          → running / completionUnread / retainedBy.mainView
//   uiSession.sessionStatus → pendingInteraction.kind（approval / plan-review / question）
//
// 关键契约（踩坑记录）：
// 1. cordis 只接受「函数」或「带 apply 方法的对象」作为插件；
// 2. 访问未在 `inject` 里声明的服务会直接抛错（cordis 的服务隔离），
//    而 apply 抛错会让整个 web boot 判为 "entry did not activate"，应用起不来。
//    所以必须用 `apply.inject = ["sessions"]` 声明依赖（completion-notify 的
//    依赖表是 ["slots","sessions","locale","configForms"]，我们只需要 sessions）；
// 3. `uiSession` 由它自己的行激活，可能晚于本插件，所以用 ctx.inject 拿（可选）；
// 4. apply 内所有异常一律吞掉并经 /event 上报诊断，绝不把宿主带崩。
(() => {
  const ENDPOINT = "http://127.0.0.1:8765/event";
  const HEARTBEAT_MS = 2000;

  function post(payload) {
    try {
      fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "text/plain;charset=UTF-8" },
        body: JSON.stringify(payload),
        keepalive: true,
      }).catch(() => {});
    } catch (e) {
      /* 桌宠没开：静默 */
    }
  }

  function diag(step, extra) {
    try {
      post(Object.assign({ source: "diag", step: step }, extra || {}));
    } catch (e) {}
  }

  function awayNow() {
    try {
      if (typeof document === "undefined") return false;
      if (document.hidden === true) return true;
      return typeof document.hasFocus === "function" && document.hasFocus() === false;
    } catch (e) {
      return false;
    }
  }

  let timer = null;


  // ------------------------------------------------------------------ 工资播报
  // 参数由桌宠的 /salary-config 提供（配置单一来源），本插件只负责「何时播」
  // 与「算出来是多少」，然后把一句话 POST 给桌宠，由它弹气泡。
  const SALARY_DEFAULTS = {
    enabled: true,
    monthlySalary: 10000,
    monthlyConsumption: 5000,
    workStart: "08:00",
    workEnd: "18:00",
    min_interval_minutes: 20,
    max_interval_minutes: 45,
  };
  const WORK_DAYS = 21.75;
  let salaryTimer = null;

  function hhmmToSec(value, fallback) {
    const m = /^([0-9]{1,2}):([0-9]{2})$/.exec(String(value || ""));
    if (!m) return fallback;
    const h = Number(m[1]);
    const mi = Number(m[2]);
    if (h > 23 || mi > 59) return fallback;
    return h * 3600 + mi * 60;
  }

  function salaryText(cfg) {
    const c = Object.assign({}, SALARY_DEFAULTS, cfg || {});
    if (c.enabled === false) return "";
    const start = hhmmToSec(c.workStart, 8 * 3600);
    let end = hhmmToSec(c.workEnd, 18 * 3600);
    if (end <= start) end += 24 * 3600;
    const secs = Math.max(1, end - start);
    const mwh = (secs / 3600) * WORK_DAYS;
    const gross = mwh > 0 ? Math.max(0, Number(c.monthlySalary) || 0) / mwh : 0;
    const cr = mwh > 0 ? Math.max(0, Number(c.monthlyConsumption) || 0) / mwh : 0;
    const now = new Date();
    let nowSec = now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds();
    // 跨天窗口（22:00-06:00）：凌晨那几小时属于「昨天开工、今天下班」
    if (end > 24 * 3600 && nowSec < end - 24 * 3600) nowSec += 24 * 3600;
    let elapsed = 0;
    let phase = "before";
    if (nowSec >= end) {
      elapsed = secs;
      phase = "after";
    } else if (nowSec >= start) {
      elapsed = nowSec - start;
      phase = "working";
    }
    const money = (v) => (v >= 100000 ? (v / 10000).toFixed(1) + "万" : v.toFixed(2));
    if (phase === "working") {
      return `今日已赚 ¥${money((gross * elapsed) / 3600)} · 净赚 ¥${money((Math.max(0, gross - cr) * elapsed) / 3600)}`;
    }
    if (phase === "after") {
      return `今日收工：已赚 ¥${money((gross * elapsed) / 3600)} · 净赚 ¥${money((Math.max(0, gross - cr) * elapsed) / 3600)}`;
    }
    return `还没开工～今天预计 ¥${money((gross * secs) / 3600)} · 净 ¥${money((Math.max(0, gross - cr) * secs) / 3600)}`;
  }

  async function fetchSalaryConfig() {
    try {
      const res = await fetch("http://127.0.0.1:8765/salary-config", { cache: "no-store" });
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  async function fireSalary() {
    const cfg = await fetchSalaryConfig();
    if (!cfg) return;
    const text = salaryText(cfg);
    if (text) post({ source: "salary", text: text, ts: Date.now() });
  }

  async function scheduleSalary() {
    if (salaryTimer !== null) {
      clearTimeout(salaryTimer);
      salaryTimer = null;
    }
    const cfg = await fetchSalaryConfig();
    if (cfg && cfg.enabled === false) {
      diag("salary-disabled");
      return;
    }
    const merged = Object.assign({}, SALARY_DEFAULTS, cfg || {});
    let low = Number(merged.min_interval_minutes);
    let high = Number(merged.max_interval_minutes);
    if (!isFinite(low) || low <= 0) low = SALARY_DEFAULTS.min_interval_minutes;
    if (!isFinite(high) || high < low) high = Math.max(low, SALARY_DEFAULTS.max_interval_minutes);
    const delay = Math.max(60000, (low + Math.random() * (high - low)) * 60000);
    diag("salary-scheduled", { minutes: Math.round(delay / 60000) });
    salaryTimer = setTimeout(async () => {
      salaryTimer = null;
      await fireSalary();
      scheduleSalary();
    }, delay);
  }

  function apply(ctx) {
    try {
      diag("apply-enter");
      const sessions = ctx.sessions;
      let status;
      let listDispose = null;

      const snapshot = () => {
        try {
          const list = sessions && sessions.list ? sessions.list.getSnapshot() : { byId: {} };
          const byId = (list && list.byId) || {};
          const rows = Object.keys(byId).map((id) => {
            const row = byId[id] || {};
            const entry = status ? status.get(id) : undefined;
            return {
              id,
              title: row.displayTitle || id,
              running: row.running === true,
              main: ((row.retainedBy && row.retainedBy.mainView) || 0) > 0,
              unread: !!(entry && entry.completionUnread === true),
              pending: (entry && entry.pendingInteraction && entry.pendingInteraction.kind) || null,
            };
          });
          post({ source: "dsh-session-bridge-pet", ts: Date.now(), away: awayNow(), rows });
        } catch (e) {
          diag("snapshot-error", { message: String(e) });
        }
      };

      if (sessions && sessions.list && typeof sessions.list.subscribe === "function") {
        listDispose = sessions.list.subscribe(() => snapshot());
        try {
          ctx.effect(() => listDispose, "dsh-session-bridge-pet: session list");
        } catch (e) {
          diag("effect-error", { message: String(e) });
        }
      } else {
        diag("no-sessions-list", { hasSessions: !!sessions });
      }

      // uiSession 是可选服务：它没激活时这里不会回调，但插件本身照常可用。
      try {
        ctx.inject(["uiSession"], (uiCtx) => {
          try {
            const feed = uiCtx.uiSession.sessionStatus;
            status = feed.getSnapshot();
            const dispose = feed.subscribe(() => {
              status = feed.getSnapshot();
              snapshot();
            });
            uiCtx.effect(() => dispose, "dsh-session-bridge-pet: session status");
            diag("uiSession-ready");
            snapshot();
          } catch (e) {
            diag("uiSession-error", { message: String(e) });
          }
        });
      } catch (e) {
        diag("inject-error", { message: String(e) });
      }

      timer = setInterval(snapshot, HEARTBEAT_MS);
      try {
        ctx.effect(() => () => {
          if (timer !== null) clearInterval(timer);
          timer = null;
        }, "dsh-session-bridge-pet: heartbeat");
      } catch (e) {
        diag("effect-error", { message: String(e) });
      }

      snapshot();
      scheduleSalary();
      diag("boot-ok");
    } catch (e) {
      // 绝不把异常抛回 cordis：抛了就是整机起不来。
      diag("apply-error", { message: String(e), stack: (e && e.stack) || "" });
    }
  }

  // 声明必需服务：sessions（会话列表）。写错名字只会让本插件 pending，
  // 而不是让宿主崩溃——比在 apply 里直接读安全。
  apply.inject = ["sessions"];

  window.__ModuleLoader__.load({
    id: "dsh-session-bridge-pet",
    factory: (require) => {
      var module = { exports: {} };
      module.exports = apply;
      return module.exports;
    },
  });
})();

(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];

  const state = {
    config: null,
    status: null,
    schedule: null,
    duas: [],
    audioFiles: null,
  };

  // Forms the user is editing must not be overwritten by the 30s background refresh.
  const dirty = { setup: false, advanced: false };
  let duaListSig = "";
  let methodsSig = "";
  let volTimer;
  let volPending = false;

  const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[c]);
  }

  function errorMessage(data, text, res) {
    const detail = data && data.detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => String(d.msg || d).replace(/^Value error, /, "")).join("; ");
    }
    if (typeof detail === "string") return detail;
    return text || res.statusText || `HTTP ${res.status}`;
  }

  async function api(path, opts = {}) {
    const { timeout = 20000, ...rest } = opts;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    try {
      const res = await fetch(path, {
        ...rest,
        headers: { "Content-Type": "application/json", ...(rest.headers || {}) },
        signal: ctrl.signal,
      });
      const text = await res.text();
      let data = null;
      try {
        data = text ? JSON.parse(text) : {};
      } catch (_) {
        data = null;
      }
      if (!res.ok) throw new Error(errorMessage(data, text, res));
      return data || {};
    } catch (e) {
      if (e.name === "AbortError") throw new Error("The speaker didn’t respond in time.");
      if (e instanceof TypeError) throw new Error("Can’t reach the speaker. Is it on the same Wi‑Fi?");
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  const post = (path, body = {}, opts = {}) =>
    api(path, { method: "POST", body: JSON.stringify(body), ...opts });

  let toastTimer;
  function toast(message, kind = "ok") {
    const el = $("#toast");
    el.textContent = message;
    el.className = `toast ${kind}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), kind === "err" ? 7000 : 3500);
  }

  async function run(btn, fn, okMessage) {
    if (btn) btn.disabled = true;
    try {
      const result = await fn();
      if (okMessage) toast(typeof okMessage === "function" ? okMessage(result) : okMessage);
      return result;
    } catch (e) {
      toast(e.message || "Something went wrong.", "err");
      return undefined;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function deviceTz() {
    return state.config?.timezone || undefined;
  }

  function fmtClock(hm) {
    const [h, m] = String(hm).split(":").map(Number);
    if (Number.isNaN(h) || Number.isNaN(m)) return hm;
    return new Date(Date.UTC(2000, 0, 1, h, m)).toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
      timeZone: "UTC",
    });
  }

  function fmtAt(iso, withDay = false) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    const opts = { hour: "numeric", minute: "2-digit" };
    if (withDay) opts.weekday = "short";
    try {
      return d.toLocaleString([], { ...opts, timeZone: deviceTz() });
    } catch (_) {
      return d.toLocaleString([], opts);
    }
  }

  function validTimezone(tz) {
    try {
      new Intl.DateTimeFormat("en-US", { timeZone: tz });
      return true;
    } catch (_) {
      return false;
    }
  }

  // ---------------------------------------------------------------- views

  let setupStep = 1;

  function isFirstRun() {
    return !state.config?.setup_complete;
  }

  function showSetupStep(n) {
    setupStep = n;
    $$("#view-setup .setup-step").forEach((el) => {
      el.classList.toggle("active", Number(el.dataset.step) === n);
    });
    $("#setupProgress").textContent = `Step ${n} of 4`;
    $("#setupTitle").textContent =
      n === 1 ? "Welcome" : n === 2 ? "Your location" : n === 3 ? "Prayer times" : "Sound";
    if (n === 2) setTimeout(() => $("#locationSearch").focus(), 50);
  }

  function showView(name) {
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
    if (name === "home") loadLogs();
  }

  // ---------------------------------------------------------------- forms

  function fillMethods(methods) {
    const entries = Object.entries(methods || {});
    const sig = JSON.stringify(entries);
    if (sig === methodsSig) return;
    methodsSig = sig;
    const sel = $("#method");
    const current = sel.value;
    sel.innerHTML = entries
      .map(([id, name]) => `<option value="${esc(id)}">${esc(name)} (${esc(id)})</option>`)
      .join("");
    if (current) sel.value = current;
  }

  function fillPrayers(enabled) {
    const names = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"];
    const on = enabled || names;
    $("#prayerToggles").innerHTML = names
      .map(
        (n) => `<label><input type="checkbox" value="${n}" ${on.includes(n) ? "checked" : ""}/> ${n}</label>`
      )
      .join("");
  }

  function syncRangeLabels() {
    $("#setupVolumeVal").textContent = `${$("#setupVolume").value}%`;
    $("#fajrVolumeVal").textContent = `${$("#fajrVolume").value}%`;
  }

  function fillSetupForm() {
    $("#btnSaveSetup").textContent = isFirstRun() ? "Finish setup" : "Save settings";
    if (dirty.setup) return;
    const c = state.config || {};
    $("#locationName").value = c.location_name || "";
    $("#latitude").value = c.latitude ?? "";
    $("#longitude").value = c.longitude ?? "";
    $("#timezone").value = c.timezone || BROWSER_TZ;
    $("#method").value = String(c.method ?? 2);
    $("#school").value = String(c.school ?? 0);
    $("#setupVolume").value = c.volume ?? 80;
    $("#fajrVolume").value = c.fajr_volume ?? 50;
    $("#audioOutput").value = c.audio_output || "auto";
    fillPrayers(c.enabled_prayers);
    syncRangeLabels();
  }

  function fillAdvanced() {
    const c = state.config || {};
    if (!dirty.advanced) {
      $("#deviceName").value = c.device_name || "Adhan Player";
      $("#kahfEnabled").checked = !!c.kahf_enabled;
      $("#sleepEnabled").checked = !!c.sleep_enabled;
      $("#offlineTimes").checked = c.use_offline_times !== false;
      $("#bootSound").value = c.play_on_boot === false ? "off" : c.boot_sound || "chime";
      $("#autoUpdate").checked = c.auto_update !== false;
    }
    renderKahfHint();
    const u = (state.status && state.status.update) || {};
    const local = (u.local_commit || "—").slice(0, 8);
    const remote = (u.remote_commit || "—").slice(0, 8);
    $("#updateInfo").textContent = [
      `App ${state.status?.version || ""} · git ${local}`,
      u.update_available ? `Update available (${remote})` : "Up to date with GitHub (or not checked yet)",
      u.next_midnight ? `Next midnight check: ${u.next_midnight}` : null,
      u.last_error ? `Last error: ${u.last_error}` : null,
    ]
      .filter(Boolean)
      .join("\n");
  }

  function renderKahfHint() {
    const files = state.audioFiles;
    const missing =
      files && !files.some((f) => f.path === (state.config?.kahf_audio_file || "audio/kahf.mp3"));
    $("#kahfMissing").classList.toggle("hidden", !(missing && $("#kahfEnabled").checked));
  }

  // ---------------------------------------------------------------- render

  function renderHome() {
    const st = state.status || {};
    const cfg = state.config || {};
    const sched = state.schedule || {};
    const next = st.state?.next_prayer || sched.next_prayer;
    const nextAt = st.state?.next_prayer_at || sched.next_prayer_at;

    $("#deviceSub").textContent = cfg.device_name || "Adhan Player";
    $("#nextPrayer").textContent = next || "—";
    $("#nextTime").textContent = nextAt ? fmtAt(nextAt) : "—";
    $("#locationLine").textContent = [
      cfg.location_name || "Location not set",
      cfg.timezone,
      st.state?.playing ? `Playing: ${st.state.playing_label}` : null,
      st.state?.muted ? `Muted until ${fmtAt(st.state.mute_until)}` : null,
    ]
      .filter(Boolean)
      .join(" · ");

    const warn = $("#clockWarn");
    if (st.clock_ok === false || st.clock_warning) {
      warn.textContent = st.clock_warning || "Clock sync issue";
      warn.classList.remove("hidden");
    } else {
      warn.classList.add("hidden");
    }

    $("#setupBanner").classList.toggle("hidden", !!cfg.setup_complete);

    const firstRun = isFirstRun();
    const wasFirstRun = document.body.classList.contains("first-run");
    document.body.classList.toggle("first-run", firstRun);
    if (firstRun && !wasFirstRun) {
      showView("setup");
      showSetupStep(1);
    }

    const wifi = st.wifi || {};
    const wifiBanner = $("#wifiBanner");
    if (wifi.hotspot_active || wifi.mode === "hotspot") {
      wifiBanner.innerHTML = `Setup hotspot is on: join <strong>${esc(wifi.hotspot_ssid || "Adhan-XXXX")}</strong> (open network, no password), then open <a href="/wifi">Wi‑Fi setup</a>.`;
      wifiBanner.classList.remove("hidden");
    } else if (wifi.nmcli && wifi.mode === "offline") {
      wifiBanner.innerHTML = `Not on Wi‑Fi yet. The device will start a setup hotspot shortly, or open the <a href="/wifi">Wi‑Fi setup page</a>.`;
      wifiBanner.classList.remove("hidden");
    } else {
      wifiBanner.classList.add("hidden");
    }

    renderTimes();

    const urls = st.urls || [];
    const portalUrl = "http://adhan.local";
    const others = urls.filter((u) => !u.includes("adhan.local"));
    const dua = state.duas.find((d) => d.id === cfg.dua_id);
    $("#deviceInfo").textContent = [
      `Open: ${portalUrl}`,
      others.length ? `Also: ${others.join(", ")}` : null,
      `Sleep mode: ${cfg.sleep_enabled ? "ON — portal offline while asleep" : "off (always on)"}`,
      `Dua: ${cfg.dua_enabled ? (dua ? dua.title : cfg.dua_id) : "disabled"}`,
    ]
      .filter(Boolean)
      .join("\n");

    const bookmarkHint = $("#bookmarkHint");
    const ua = navigator.userAgent || "";
    const isStandalone =
      window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
    if (isStandalone) {
      bookmarkHint.textContent = "Nice — you’re using the installed home-screen app.";
    } else if (/iPad|iPhone|iPod/.test(ua)) {
      bookmarkHint.textContent = "On iPhone/iPad: tap Share → Add to Home Screen for one-tap access later.";
    } else if (/Android/i.test(ua)) {
      bookmarkHint.textContent = "On Android: tap the browser menu → Install app / Add to Home screen.";
    } else {
      bookmarkHint.textContent = "On a laptop: bookmark http://adhan.local for quick access next time.";
    }

    const slider = $("#volume");
    if (!volPending && document.activeElement !== slider) {
      const vol = cfg.volume ?? 80;
      slider.value = vol;
      $("#volVal").textContent = vol;
    }

    const qrHost = $("#qr");
    if (window.QRCode && qrHost && qrHost.dataset.url !== portalUrl) {
      qrHost.innerHTML = "";
      qrHost.dataset.url = portalUrl;
      // eslint-disable-next-line no-new
      new QRCode(qrHost, { text: portalUrl, width: 160, height: 160 });
    }

    if ($("#view-home").classList.contains("active")) loadLogs();
  }

  function loadLogs() {
    api("/api/logs?lines=30")
      .then((data) => {
        $("#logBox").textContent = (data.lines || []).join("\n") || "No logs yet.";
      })
      .catch(() => {
        $("#logBox").textContent = "Could not load logs.";
      });
  }

  function renderTimes() {
    const st = state.status || {};
    const cfg = state.config || {};
    const sched = state.schedule || {};
    const next = st.state?.next_prayer || sched.next_prayer;
    const nextAt = st.state?.next_prayer_at || sched.next_prayer_at;
    const times = st.state?.today_times || sched.today || {};
    const enabled = cfg.enabled_prayers || Object.keys(times);

    $("#todayList").innerHTML = Object.keys(times).length
      ? Object.entries(times)
          .map(([name, t]) => {
            const off = !enabled.includes(name);
            const cls = [name === next ? "next" : "", off ? "off" : ""].join(" ");
            return `<li class="${cls}"><span>${esc(name)}${off ? " <em>(silent)</em>" : ""}</span><strong>${esc(fmtClock(t))}</strong></li>`;
          })
          .join("")
      : "<li><span>No times yet — finish Setup</span><strong>—</strong></li>";

    $("#timesLocationLine").textContent = [
      cfg.location_name || "Location not set",
      cfg.latitude != null && cfg.longitude != null
        ? `${Number(cfg.latitude).toFixed(4)}, ${Number(cfg.longitude).toFixed(4)}`
        : null,
      cfg.timezone,
      sched.methods?.[cfg.method] ? `${sched.methods[cfg.method]} method` : `Method ${cfg.method ?? 2}`,
      Number(cfg.school) === 1 ? "Hanafi Asr" : "Standard Asr",
    ]
      .filter(Boolean)
      .join(" · ");

    const clock = $("#timesClockWarn");
    if (st.clock_ok === false || st.clock_warning) {
      clock.textContent = st.clock_warning || "Clock sync issue — fix NTP before trusting these times.";
      clock.classList.remove("hidden");
    } else {
      clock.classList.add("hidden");
    }

    const now = Date.now();
    const rows = (st.state?.schedule || sched.schedule || [])
      .filter((row) => !row.at || new Date(row.at).getTime() > now)
      .slice(0, 10);
    $("#upcomingList").innerHTML = rows.length
      ? rows
          .map((row) => {
            const isNext = row.name === next && row.at === nextAt;
            return `<li class="${isNext ? "next" : ""}"><span>${esc(row.name)}</span><strong>${esc(
              row.at ? fmtAt(row.at, true) : "—"
            )}</strong></li>`;
          })
          .join("")
      : "<li><span>No upcoming prayers</span><strong>—</strong></li>";
  }

  function renderDuas() {
    const box = $("#duaList");
    const sig = JSON.stringify(state.duas.map((d) => [d.id, d.available, d.url]));
    if (sig !== duaListSig) {
      duaListSig = sig;
      box.innerHTML = state.duas
        .map((d) => {
          const unavailable = d.available ? "" : `<p class="hint">Audio file missing on device.</p>`;
          return `<article class="dua" data-id="${esc(d.id)}">
          <h3>${esc(d.title)}</h3>
          <p class="muted">${esc(d.description)}</p>
          <p class="arabic" lang="ar">${esc(d.arabic)}</p>
          <p class="hint">${esc(d.transliteration)}</p>
          <p class="muted">${esc(d.english)}</p>
          ${unavailable}
          <audio controls preload="none" src="${esc(d.url)}"></audio>
          <div class="actions">
            <button type="button" data-select="${esc(d.id)}" ${d.available ? "" : "disabled"}>Use this dua</button>
            <button type="button" class="ghost" data-speaker="${esc(d.id)}" ${d.available ? "" : "disabled"}>Play on speaker</button>
          </div>
        </article>`;
        })
        .join("");
    }
    const selected = state.config?.dua_id;
    const enabled = !!state.config?.dua_enabled;
    $("#duaEnabled").checked = enabled;
    $$("#duaList .dua").forEach((card) => {
      const isSel = card.dataset.id === selected;
      card.classList.toggle("selected", isSel);
      const btn = card.querySelector("[data-select]");
      const available = state.duas.find((d) => d.id === card.dataset.id)?.available;
      btn.textContent = isSel ? (enabled ? "✓ Selected" : "✓ Selected (dua off)") : "Use this dua";
      btn.classList.toggle("ghost", isSel);
      btn.disabled = !available || (isSel && enabled);
    });
  }

  function renderWifi() {
    const st = state.status || {};
    const cfg = state.config || {};
    const wifi = st.wifi || {};
    const modeLabel = {
      station: wifi.ssid ? `Connected to “${wifi.ssid}”` : "Connected",
      hotspot: `Setup hotspot on: ${wifi.hotspot_ssid} (open, no password)`,
      offline: "Not connected to Wi‑Fi",
    }[wifi.mode] || "Unknown";
    $("#wifiInfo").textContent = [
      modeLabel,
      wifi.nmcli === false ? "NetworkManager (nmcli) isn’t available on this device." : null,
      wifi.mode !== "hotspot" ? `Setup hotspot name: ${wifi.hotspot_ssid || "Adhan-XXXX"} (open)` : null,
      `Internet: ${wifi.online ? "yes" : "no"}`,
    ]
      .filter(Boolean)
      .join("\n");
    $("#hotspotAuto").checked = cfg.wifi_hotspot_auto !== false;
    const btn = $("#btnStartHotspot");
    btn.classList.toggle("hidden", !!wifi.hotspot_active || wifi.nmcli === false);
  }

  // ---------------------------------------------------------------- data

  async function refresh() {
    const [status, config, schedule, duas] = await Promise.all([
      api("/api/status"),
      api("/api/config"),
      api("/api/schedule"),
      api("/api/duas"),
    ]);
    state.status = status;
    state.config = config;
    state.schedule = schedule;
    state.duas = duas.duas || [];
    fillMethods(schedule.methods);
    fillSetupForm();
    fillAdvanced();
    renderHome();
    renderWifi();
    renderDuas();
  }

  async function patch(body) {
    state.config = await api("/api/config", { method: "PATCH", body: JSON.stringify(body) });
    await refresh();
    return state.config;
  }

  function trackDirty(sectionSel, key) {
    const section = $(sectionSel);
    const mark = (e) => {
      if (e.target.closest("[data-no-dirty]")) return;
      dirty[key] = true;
    };
    section.addEventListener("input", mark);
    section.addEventListener("change", mark);
  }

  // ---------------------------------------------------------------- location search

  const COORDS_RE = /^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$/;
  let searchSeq = 0;
  let searchTimer;
  let lastResults = [];

  function showPicked(place) {
    const el = $("#locationPicked");
    el.innerHTML = `Using <strong>${esc(place.label || place.name || "these coordinates")}</strong> · ${esc(
      Number(place.latitude).toFixed(4)
    )}, ${esc(Number(place.longitude).toFixed(4))} · ${esc(place.timezone)}`;
    el.classList.remove("hidden");
  }

  function applyPlace(place) {
    if (place.label || place.name) $("#locationName").value = place.label || place.name;
    $("#latitude").value = place.latitude;
    $("#longitude").value = place.longitude;
    $("#timezone").value = place.timezone;
    dirty.setup = true;
    showPicked(place);
    $("#locationResults").classList.add("hidden");
  }

  async function searchLocation() {
    const q = $("#locationSearch").value.trim();
    const box = $("#locationResults");
    clearTimeout(searchTimer);
    if (!q) {
      box.classList.add("hidden");
      return;
    }
    const m = q.match(COORDS_RE);
    if (m && Math.abs(+m[1]) <= 90 && Math.abs(+m[2]) <= 180) {
      const seq = ++searchSeq;
      try {
        const data = await api(`/api/geocode?q=${encodeURIComponent(q)}`, { timeout: 25000 });
        if (seq === searchSeq && data.results?.length) {
          applyPlace(data.results[0]);
          return;
        }
      } catch (_) {
        // Offline: fall through and use the raw coordinates.
      }
      if (seq !== searchSeq) return;
      applyPlace({
        name: `${(+m[1]).toFixed(4)}, ${(+m[2]).toFixed(4)}`,
        latitude: +m[1],
        longitude: +m[2],
        timezone: $("#timezone").value.trim() || BROWSER_TZ,
      });
      toast("Coordinates filled in. The speaker is offline, so double-check the timezone.", "err");
      return;
    }
    if (q.length < 2) return;
    const seq = ++searchSeq;
    box.classList.remove("hidden");
    box.innerHTML = `<p class="hint">Searching…</p>`;
    try {
      const data = await api(`/api/geocode?q=${encodeURIComponent(q)}`, { timeout: 25000 });
      if (seq !== searchSeq) return;
      lastResults = data.results || [];
      box.innerHTML = lastResults.length
        ? lastResults
            .map(
              (r, i) => `<button type="button" class="result" role="option" data-result="${i}">
              <strong>${esc(r.label || r.name)}</strong>
              <span class="muted">${esc(Number(r.latitude).toFixed(3))}, ${esc(Number(r.longitude).toFixed(3))} · ${esc(r.timezone)}</span>
            </button>`
            )
            .join("")
        : `<p class="hint">No matches. Try just the city name, or add the country (e.g. “Lahore, Pakistan”).</p>`;
    } catch (e) {
      if (seq !== searchSeq) return;
      box.innerHTML = `<p class="hint warn-text">${esc(e.message)} You can still type latitude, longitude and timezone below.</p>`;
    }
  }

  function validateLocation() {
    const latRaw = $("#latitude").value.trim();
    const lonRaw = $("#longitude").value.trim();
    const lat = Number(latRaw);
    const lon = Number(lonRaw);
    const tz = $("#timezone").value.trim();
    if (!latRaw || !lonRaw || Number.isNaN(lat) || Number.isNaN(lon)) {
      return "Search for your city (or enter latitude and longitude) so prayer times can be calculated.";
    }
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      return "Latitude must be between -90 and 90, longitude between -180 and 180.";
    }
    if (!tz || !validTimezone(tz)) {
      return `“${tz || "(empty)"}” isn’t a valid timezone. Pick one from the list, e.g. America/Chicago.`;
    }
    return null;
  }

  // ---------------------------------------------------------------- wiring

  $$(".tab").forEach((tab) => tab.addEventListener("click", () => showView(tab.dataset.view)));
  $$("[data-goto]").forEach((el) => el.addEventListener("click", () => showView(el.dataset.goto)));

  trackDirty("#view-setup", "setup");
  trackDirty("#view-advanced", "advanced");

  $("#btnTest").onclick = (e) =>
    run(e.currentTarget, () => post("/api/play", { kind: "test" }), "Playing adhan + dua on the speaker…").then(
      () => setTimeout(() => refresh().catch(() => {}), 800)
    );
  $("#btnStop").onclick = (e) =>
    run(e.currentTarget, () => post("/api/stop"), "Stopped.").then(() => refresh().catch(() => {}));
  $("#btnSkip").onclick = (e) =>
    run(e.currentTarget, () => post("/api/skip"), () => {
      const next = state.status?.state?.next_prayer;
      return next ? `${next} will be skipped.` : "The next adhan will be skipped.";
    });
  $("#btnMute").onclick = (e) =>
    run(e.currentTarget, () => post("/api/mute", { minutes: 60 }), "Muted for 60 minutes.").then(() =>
      refresh().catch(() => {})
    );

  $("#volume").addEventListener("input", (e) => {
    $("#volVal").textContent = e.target.value;
    volPending = true;
    clearTimeout(volTimer);
    volTimer = setTimeout(async () => {
      await run(null, () => patch({ volume: Number(e.target.value) }));
      volPending = false;
    }, 350);
  });

  ["#setupVolume", "#fajrVolume"].forEach((sel) => $(sel).addEventListener("input", syncRangeLabels));

  $("#locationSearchForm").addEventListener("submit", (e) => {
    e.preventDefault();
    searchLocation();
  });
  $("#locationSearch").addEventListener("input", () => {
    clearTimeout(searchTimer);
    const q = $("#locationSearch").value.trim();
    if (q.length >= 3) searchTimer = setTimeout(searchLocation, COORDS_RE.test(q) ? 900 : 600);
  });
  $("#locationResults").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-result]");
    if (btn) applyPlace(lastResults[Number(btn.dataset.result)]);
  });

  const tzList = $("#tzList");
  if (tzList && typeof Intl.supportedValuesOf === "function") {
    tzList.innerHTML = Intl.supportedValuesOf("timeZone")
      .map((z) => `<option value="${esc(z)}"></option>`)
      .join("");
  }

  if (window.isSecureContext && navigator.geolocation) {
    // Browsers only share location on https:// or localhost, never on http://adhan.local.
    $("#btnGeo").classList.remove("hidden");
    $("#btnGeo").onclick = () => {
      navigator.geolocation.getCurrentPosition(
        (pos) =>
          applyPlace({
            name: $("#locationName").value.trim() || "My location",
            latitude: Number(pos.coords.latitude.toFixed(5)),
            longitude: Number(pos.coords.longitude.toFixed(5)),
            timezone: BROWSER_TZ,
          }),
        (err) => toast(err.message || "Could not get location. Search for your city instead.", "err"),
        { enableHighAccuracy: false, timeout: 10000 }
      );
    };
  }

  $("#btnSetupNext1").onclick = () => showSetupStep(2);
  $("#btnSetupNext2").onclick = () => {
    const problem = validateLocation();
    if (problem) {
      toast(problem, "err");
      return;
    }
    showSetupStep(3);
  };
  $("#btnSetupNext3").onclick = () => {
    if (!$$("#prayerToggles input:checked").length) {
      toast("Pick at least one prayer to play.", "err");
      return;
    }
    showSetupStep(4);
  };
  $$("[data-setup-step]").forEach((el) => {
    el.addEventListener("click", () => showSetupStep(Number(el.dataset.setupStep)));
  });

  $("#btnSaveSetup").onclick = async (e) => {
    const problem = validateLocation();
    if (problem) {
      toast(problem, "err");
      if (isFirstRun()) showSetupStep(2);
      return;
    }
    const enabled = $$("#prayerToggles input:checked").map((el) => el.value);
    const wasFirstRun = isFirstRun();
    const body = {
      setup_complete: true,
      location_name: $("#locationName").value.trim() || "My location",
      latitude: Number($("#latitude").value),
      longitude: Number($("#longitude").value),
      timezone: $("#timezone").value.trim(),
      method: Number($("#method").value),
      school: Number($("#school").value),
      volume: Number($("#setupVolume").value),
      fajr_volume: Number($("#fajrVolume").value),
      audio_output: $("#audioOutput").value,
      enabled_prayers: enabled,
    };
    const saved = await run(
      e.currentTarget,
      async () => {
        state.config = await api("/api/config", { method: "PATCH", body: JSON.stringify(body) });
        dirty.setup = false;
        $("#locationPicked").classList.add("hidden");
        await refresh();
        return true;
      },
      wasFirstRun ? "Setup complete. Prayer times are ready." : "Settings saved."
    );
    if (saved && wasFirstRun) showView("home");
  };

  $("#btnPlayAdhan").onclick = (e) =>
    run(e.currentTarget, () => post("/api/play", { kind: "adhan" }), "Playing adhan on the speaker…");
  $("#btnPlayFajr").onclick = (e) =>
    run(e.currentTarget, () => post("/api/play", { kind: "fajr" }), "Playing Fajr adhan on the speaker…");

  $("#duaEnabled").onchange = (e) =>
    run(null, () => patch({ dua_enabled: e.target.checked }), e.target.checked ? "Dua after adhan: on" : "Dua after adhan: off");

  $("#duaList").addEventListener("click", (e) => {
    const select = e.target.closest("[data-select]");
    const speaker = e.target.closest("[data-speaker]");
    if (select) {
      const title = state.duas.find((d) => d.id === select.dataset.select)?.title || "Dua";
      run(select, () => patch({ dua_id: select.dataset.select, dua_enabled: true }), `${title} will play after each adhan.`);
    }
    if (speaker) {
      run(speaker, () => post("/api/play", { kind: "dua", dua_id: speaker.dataset.speaker }), "Playing on the speaker…");
    }
  });

  $("#hotspotAuto").onchange = (e) =>
    run(
      null,
      () => patch({ wifi_hotspot_auto: e.target.checked }),
      e.target.checked ? "Auto setup hotspot: on" : "Auto setup hotspot: off"
    );

  $("#btnStartHotspot").onclick = async (e) => {
    const wifi = state.status?.wifi || {};
    const ok = confirm(
      `Start the setup hotspot now?\n\n` +
        (wifi.ssid ? `The speaker will leave “${wifi.ssid}” and ` : "The speaker will ") +
        `this page will stop responding. To get back in, join the open Wi‑Fi “${wifi.hotspot_ssid || "Adhan-XXXX"}” ` +
        `and open http://10.42.0.1:8080/wifi.`
    );
    if (!ok) return;
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await post("/api/wifi/hotspot", {}, { timeout: 15000 });
      await refresh().catch(() => {});
      toast(`Hotspot “${wifi.hotspot_ssid || "Adhan-XXXX"}” is on. Join it, then open http://10.42.0.1:8080/wifi`);
    } catch (err) {
      if (/respond|reach/.test(err.message)) {
        toast(`The speaker switched to its hotspot. Join “${wifi.hotspot_ssid || "Adhan-XXXX"}” to continue.`);
      } else {
        toast(err.message || "Could not start hotspot (needs NetworkManager on the Pi).", "err");
      }
    } finally {
      btn.disabled = false;
    }
  };

  $("#kahfEnabled").addEventListener("change", renderKahfHint);

  $("#btnPreviewBoot").onclick = (e) => {
    const sound = $("#bootSound").value;
    if (sound === "off") {
      toast("Pick a sound to preview.", "err");
      return;
    }
    run(
      e.currentTarget,
      () =>
        post("/api/play", {
          kind: "file",
          path: `audio/boot-${sound}.mp3`,
          volume: state.config?.boot_volume ?? 45,
        }),
      "Playing on the speaker…"
    );
  };

  $("#btnSaveAdvanced").onclick = async (e) => {
    if ($("#sleepEnabled").checked && !state.config?.sleep_enabled) {
      const ok = confirm(
        "Enable sleep outside prayer times?\n\n" +
          "While asleep, the web portal at http://adhan.local will NOT be reachable " +
          "(Wi‑Fi and the Pi are suspended). The device wakes ~3 minutes before each prayer.\n\n" +
          "Leave this off if you want the portal available anytime."
      );
      if (!ok) {
        $("#sleepEnabled").checked = false;
        return;
      }
    }
    const auto = $("#autoUpdate").checked;
    await run(
      e.currentTarget,
      async () => {
        state.config = await api("/api/config", {
          method: "PATCH",
          body: JSON.stringify({
            device_name: $("#deviceName").value.trim() || "Adhan Player",
            kahf_enabled: $("#kahfEnabled").checked,
            sleep_enabled: $("#sleepEnabled").checked,
            use_offline_times: $("#offlineTimes").checked,
            boot_sound: $("#bootSound").value,
            auto_update: auto,
            update_on_boot: auto,
            update_at_midnight: auto,
          }),
        });
        dirty.advanced = false;
        await refresh();
      },
      "Advanced settings saved."
    );
  };

  $("#btnCheckUpdate").onclick = (e) =>
    run(
      e.currentTarget,
      async () => {
        const st = await post("/api/update/check", {}, { timeout: 60000 });
        state.status = state.status || {};
        state.status.update = st;
        fillAdvanced();
        return st;
      },
      (st) => (st.update_available ? "An update is available. Tap Update now." : "Already up to date.")
    );

  $("#btnApplyUpdate").onclick = (e) => {
    if (!confirm("Update from GitHub now? Settings and your adhan audio are kept. The portal may restart.")) {
      return;
    }
    run(
      e.currentTarget,
      () => post("/api/update", { apply: true }),
      (res) => res.message || "Update started."
    );
  };

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  api("/api/audio")
    .then((data) => {
      state.audioFiles = data.files || [];
      renderKahfHint();
    })
    .catch(() => {});

  refresh().catch((err) => {
    $("#deviceSub").textContent = "Could not reach the speaker";
    toast(err.message, "err");
    console.error(err);
  });
  setInterval(() => {
    if (document.visibilityState === "visible") refresh().catch(() => {});
  }, 30000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refresh().catch(() => {});
  });
})();

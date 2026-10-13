(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];

  const PRAYERS = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"];

  const state = {
    config: null,
    status: null,
    schedule: null,
    duas: [],
    audioFiles: [],
  };

  let formsHydrated = false;
  let setupStep = 1;

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || res.statusText);
    }
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return {};
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showSetupStep(n) {
    setupStep = n;
    $$("#view-setup .setup-step").forEach((el) => {
      el.classList.toggle("active", Number(el.dataset.step) === n);
    });
    const progress = $("#setupProgress");
    const title = $("#setupTitle");
    if (progress) progress.textContent = `Step ${n} of 4`;
    if (title) {
      title.textContent =
        n === 1 ? "Welcome" : n === 2 ? "Your location" : n === 3 ? "Prayer times" : "Sound";
    }
  }

  function showView(name) {
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  }

  function fillMethods(methods) {
    const sel = $("#method");
    if (!sel) return;
    sel.innerHTML = "";
    Object.entries(methods || {}).forEach(([id, name]) => {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = `${name} (${id})`;
      sel.appendChild(opt);
    });
  }

  function fillPrayers(enabled) {
    const box = $("#prayerToggles");
    if (!box) return;
    box.innerHTML = PRAYERS.map(
      (n) => `<label><input type="checkbox" value="${n}" ${
        (enabled || PRAYERS).includes(n) ? "checked" : ""
      }/> ${n}</label>`
    ).join("");
  }

  function fillFileSelect(sel, selected) {
    if (!sel) return;
    const files = state.audioFiles || [];
    const current = selected || "";
    const names = new Set(files.map((f) => f.path));
    sel.innerHTML = "";
    if (current && !names.has(current)) {
      const opt = document.createElement("option");
      opt.value = current;
      opt.textContent = `${current} (missing)`;
      sel.appendChild(opt);
    }
    files.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f.path;
      opt.textContent = f.path.replace(/^audio\//, "");
      sel.appendChild(opt);
    });
    if (current) sel.value = current;
  }

  function fillDuaSelect(sel, selected, includeDefault) {
    if (!sel) return;
    const duas = state.duas || [];
    sel.innerHTML = "";
    if (includeDefault) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Default slot";
      sel.appendChild(opt);
    }
    duas.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.id;
      opt.textContent = d.available ? d.title : `${d.title} (missing file)`;
      sel.appendChild(opt);
    });
    if (selected) sel.value = selected;
  }

  function renderHome() {
    const st = state.status || {};
    const cfg = state.config || {};
    const sched = state.schedule || {};
    const next = st.state?.next_prayer || sched.next_prayer;
    const nextAt = st.state?.next_prayer_at || sched.next_prayer_at;

    $("#deviceSub").textContent = cfg.device_name || "Adhan Player";
    $("#nextPrayer").textContent = next || "-";
    $("#nextTime").textContent = nextAt
      ? new Date(nextAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      : "-";
    $("#locationLine").textContent = [
      cfg.location_name || "Location not set",
      cfg.timezone,
      st.state?.playing ? `Playing: ${st.state.playing_label}` : null,
      st.state?.muted ? "Muted" : null,
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

    const setupBanner = $("#setupBanner");
    setupBanner.classList.toggle("hidden", !!cfg.setup_complete);

    const firstRun = !cfg.setup_complete;
    document.body.classList.toggle("first-run", firstRun);
    if (firstRun && !$("#view-setup").classList.contains("active")) {
      showView("setup");
      showSetupStep(1);
    }

    const wifi = st.wifi || {};
    const wifiBanner = $("#wifiBanner");
    if (wifi.hotspot_active || wifi.mode === "hotspot") {
      wifiBanner.innerHTML = `Setup hotspot is on: join <strong>${wifi.hotspot_ssid || "Adhan-XXXX"}</strong> (open network, no password), then open <a href="/wifi">Wi-Fi setup</a>.`;
      wifiBanner.classList.remove("hidden");
    } else if (wifi.mode === "offline") {
      wifiBanner.innerHTML = `Not on Wi-Fi yet. The device will start a setup hotspot shortly, or open the <a href="/wifi">Wi-Fi setup page</a>.`;
      wifiBanner.classList.remove("hidden");
    } else {
      wifiBanner.classList.add("hidden");
    }

    const wifiInfo = $("#wifiInfo");
    if (wifiInfo) {
      wifiInfo.textContent = [
        `Mode: ${wifi.mode || "unknown"}`,
        wifi.ssid ? `Connected: ${wifi.ssid}` : null,
        wifi.hotspot_active
          ? `Hotspot: ${wifi.hotspot_ssid} (open, no password)`
          : `Setup hotspot SSID would be: ${wifi.hotspot_ssid || "Adhan-XXXX"} (open)`,
        wifi.dhcp_ready === false ? "Hotspot IP not ready yet (need dnsmasq-base?)" : null,
        `Online: ${wifi.online ? "yes" : "no"}`,
        `Auto-hotspot when offline: ${cfg.wifi_hotspot_auto === false ? "off" : "on"}`,
      ]
        .filter(Boolean)
        .join("\n");
    }

    renderTimes();

    const urls = st.urls || [];
    const portalUrl = "http://adhan.local";
    $("#deviceInfo").textContent = [
      `Open: ${portalUrl}`,
      urls.filter((u) => !u.includes("adhan.local")).length
        ? `Also: ${urls.filter((u) => !u.includes("adhan.local")).join(", ")}`
        : null,
      `Sleep mode: ${cfg.sleep_enabled ? "ON (portal offline while asleep)" : "off (always on)"}`,
      `Dua: ${cfg.dua_enabled ? cfg.dua_id : "disabled"}`,
      cfg.fajr_dua_id ? `Fajr dua: ${cfg.fajr_dua_enabled === false ? "disabled" : cfg.fajr_dua_id}` : null,
    ]
      .filter(Boolean)
      .join("\n");

    const bookmarkHint = $("#bookmarkHint");
    if (bookmarkHint) {
      const ua = navigator.userAgent || "";
      const isIos = /iPad|iPhone|iPod/.test(ua);
      const isAndroid = /Android/i.test(ua);
      const isStandalone =
        window.matchMedia("(display-mode: standalone)").matches ||
        navigator.standalone === true;
      if (isStandalone) {
        bookmarkHint.textContent = "Nice: you’re using the installed home-screen app.";
      } else if (isIos) {
        bookmarkHint.textContent =
          "On iPhone/iPad: tap Share, then Add to Home Screen for one-tap access later.";
      } else if (isAndroid) {
        bookmarkHint.textContent =
          "On Android: tap the browser menu, then Install app / Add to Home screen.";
      } else {
        bookmarkHint.textContent =
          "On a laptop: bookmark http://adhan.local for quick access next time.";
      }
    }

    const vol = cfg.volume ?? 80;
    const volEl = $("#volume");
    if (volEl && document.activeElement !== volEl) {
      volEl.value = vol;
      $("#volVal").textContent = vol;
    }

    const qrHost = $("#qr");
    if (window.QRCode && qrHost && qrHost.dataset.url !== portalUrl) {
      qrHost.innerHTML = "";
      qrHost.dataset.url = portalUrl;
      // eslint-disable-next-line no-new
      new QRCode(qrHost, { text: portalUrl, width: 160, height: 160 });
    }

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
    const times = sched.today || st.state?.today_times || {};
    const list = $("#todayList");
    if (list) {
      list.innerHTML = Object.keys(times).length
        ? Object.entries(times)
            .map(([name, t]) => {
              const isNext = name === next;
              return `<li class="${isNext ? "next" : ""}"><span>${name}</span><strong>${t}</strong></li>`;
            })
            .join("")
        : "<li><span>No times yet: finish Setup</span><strong>-</strong></li>";
    }

    const loc = $("#timesLocationLine");
    if (loc) {
      loc.textContent = [
        cfg.location_name || "Location not set",
        cfg.latitude != null && cfg.longitude != null
          ? `${Number(cfg.latitude).toFixed(4)}, ${Number(cfg.longitude).toFixed(4)}`
          : null,
        cfg.timezone,
        `Method ${cfg.method ?? 2}`,
      ]
        .filter(Boolean)
        .join(" · ");
    }

    const clock = $("#timesClockWarn");
    if (clock) {
      if (st.clock_ok === false || st.clock_warning) {
        clock.textContent =
          st.clock_warning || "Clock sync issue: fix NTP before trusting these times.";
        clock.classList.remove("hidden");
      } else {
        clock.classList.add("hidden");
      }
    }

    const upcoming = $("#upcomingList");
    if (upcoming) {
      const rows = (sched.schedule || st.state?.schedule || []).slice(0, 10);
      upcoming.innerHTML = rows.length
        ? rows
            .map((row) => {
              const when = row.at ? new Date(row.at) : null;
              const label = when
                ? when.toLocaleString([], {
                    weekday: "short",
                    hour: "numeric",
                    minute: "2-digit",
                  })
                : "-";
              const isNext = row.name === next && row.at === (st.state?.next_prayer_at || sched.next_prayer_at);
              return `<li class="${isNext ? "next" : ""}"><span>${row.name}</span><strong>${label}</strong></li>`;
            })
            .join("")
        : "<li><span>No upcoming prayers</span><strong>-</strong></li>";
    }
  }

  function renderDuas() {
    const selected = state.config?.dua_id;
    const duaEnabled = $("#duaEnabled");
    if (duaEnabled && document.activeElement !== duaEnabled) {
      duaEnabled.checked = !!state.config?.dua_enabled;
    }
    const box = $("#duaList");
    if (!box) return;
    box.innerHTML = (state.duas || [])
      .map((d) => {
        const unavailable = d.available ? "" : `<p class="hint">Audio file missing on device.</p>`;
        return `<article class="dua ${d.id === selected ? "selected" : ""}" data-id="${d.id}">
          <h3>${escapeHtml(d.title)}</h3>
          <p class="muted">${escapeHtml(d.description || "")}</p>
          <p class="arabic">${d.arabic || ""}</p>
          <p class="hint">${escapeHtml(d.transliteration || "")}</p>
          <p class="muted">${escapeHtml(d.english || "")}</p>
          ${unavailable}
          <audio controls preload="none" src="${escapeHtml(d.url)}"></audio>
          <div class="actions">
            <button type="button" data-select="${escapeHtml(d.id)}">Use this dua</button>
            <button type="button" class="ghost" data-speaker="${escapeHtml(d.id)}">Play on speaker</button>
          </div>
        </article>`;
      })
      .join("");
  }

  function fillSetupForm() {
    const c = state.config || {};
    $("#locationName").value = c.location_name || "";
    $("#latitude").value = c.latitude ?? "";
    $("#longitude").value = c.longitude ?? "";
    $("#timezone").value = c.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
    $("#method").value = String(c.method ?? 2);
    $("#school").value = String(c.school ?? 0);
    $("#setupVolume").value = c.volume ?? 80;
    $("#fajrVolume").value = c.fajr_volume ?? 50;
    $("#audioOutput").value = c.audio_output || "auto";
    fillPrayers(c.enabled_prayers);
  }

  function fillAudioForm() {
    const c = state.config || {};
    fillFileSelect($("#regularAdhanFile"), c.audio_file || "audio/adhan.mp3");
    fillFileSelect($("#fajrAdhanFile"), c.fajr_audio_file || "audio/fajr.mp3");
    const setRange = (id, valId, value) => {
      const el = $(id);
      const lab = $(valId);
      if (el) {
        el.value = value;
        if (lab) lab.textContent = value;
      }
    };
    setRange("#regularAdhanVolume", "#regularAdhanVolVal", c.volume ?? 80);
    setRange("#fajrAdhanVolume", "#fajrAdhanVolVal", c.fajr_volume ?? 50);
    setRange("#regularDuaVolume", "#regularDuaVolVal", c.dua_volume ?? c.volume ?? 80);
    setRange("#fajrDuaVolume", "#fajrDuaVolVal", c.fajr_dua_volume ?? c.fajr_volume ?? 50);
    if ($("#duaEnabled")) $("#duaEnabled").checked = c.dua_enabled !== false;
    if ($("#fajrDuaEnabled")) {
      $("#fajrDuaEnabled").checked =
        c.fajr_dua_enabled !== undefined && c.fajr_dua_enabled !== null
          ? !!c.fajr_dua_enabled
          : c.dua_enabled !== false;
    }
    fillDuaSelect($("#fajrDuaId"), c.fajr_dua_id || c.dua_id, false);
    renderPrayerOverrides();
  }

  function renderPrayerOverrides() {
    const box = $("#prayerOverrides");
    if (!box) return;
    const c = state.config || {};
    const ov = c.prayer_overrides || {};
    const files = state.audioFiles || [];
    const fileOpts = (selected) => {
      const opts = [`<option value="">Default recording</option>`];
      files.forEach((f) => {
        const sel = f.path === selected ? "selected" : "";
        opts.push(`<option value="${escapeHtml(f.path)}" ${sel}>${escapeHtml(f.path.replace(/^audio\//, ""))}</option>`);
      });
      return opts.join("");
    };
    const duaOpts = (selected) => {
      const opts = [`<option value="">Default dua</option>`];
      (state.duas || []).forEach((d) => {
        const sel = d.id === selected ? "selected" : "";
        opts.push(`<option value="${escapeHtml(d.id)}" ${sel}>${escapeHtml(d.title)}</option>`);
      });
      return opts.join("");
    };
    box.innerHTML = PRAYERS.map((name) => {
      const slot = ov[name] || {};
      const vol = slot.volume == null ? "" : slot.volume;
      return `<div class="override-row" data-prayer="${name}">
        <strong>${name}</strong>
        <label>Adhan
          <select data-ov="adhan_file">${fileOpts(slot.adhan_file || "")}</select>
        </label>
        <label>Dua
          <select data-ov="dua_id">${duaOpts(slot.dua_id || "")}</select>
        </label>
        <label>Vol
          <input data-ov="volume" type="number" min="0" max="100" placeholder="auto" value="${escapeHtml(vol)}" />
        </label>
      </div>`;
    }).join("");
  }

  function collectPrayerOverrides() {
    const out = {};
    $$("#prayerOverrides .override-row").forEach((row) => {
      const name = row.dataset.prayer;
      const slot = {};
      const file = row.querySelector('[data-ov="adhan_file"]')?.value;
      const dua = row.querySelector('[data-ov="dua_id"]')?.value;
      const volRaw = row.querySelector('[data-ov="volume"]')?.value;
      if (file) slot.adhan_file = file;
      if (dua) slot.dua_id = dua;
      if (volRaw !== "" && volRaw != null) {
        const n = Number(volRaw);
        if (!Number.isNaN(n)) slot.volume = n;
      }
      if (Object.keys(slot).length) out[name] = slot;
    });
    return out;
  }

  function fillAdvanced() {
    const c = state.config || {};
    $("#deviceName").value = c.device_name || "Adhan Player";
    $("#kahfEnabled").checked = !!c.kahf_enabled;
    $("#sleepEnabled").checked = !!c.sleep_enabled;
    $("#offlineTimes").checked = c.use_offline_times !== false;
    $("#playOnBoot").checked = c.play_on_boot !== false;
    const autoEl = $("#autoUpdate");
    if (autoEl) autoEl.checked = c.auto_update !== false;
    const info = $("#updateInfo");
    const u = (state.status && state.status.update) || {};
    if (info) {
      const local = (u.local_commit || "-").slice(0, 8);
      const remote = (u.remote_commit || "-").slice(0, 8);
      info.textContent = [
        `App ${state.status?.version || ""} · git ${local}`,
        u.update_available ? `Update available (${remote})` : "Up to date with GitHub (or not checked yet)",
        u.next_midnight ? `Next midnight check: ${u.next_midnight}` : null,
        u.last_error ? `Last error: ${u.last_error}` : null,
      ]
        .filter(Boolean)
        .join("\n");
    }
  }

  async function refresh() {
    const [status, config, schedule, duas, audio] = await Promise.all([
      api("/api/status"),
      api("/api/config"),
      api("/api/schedule"),
      api("/api/duas"),
      api("/api/audio").catch(() => ({ files: [] })),
    ]);
    state.status = status;
    state.config = config;
    state.schedule = schedule;
    state.duas = duas.duas || [];
    state.audioFiles = audio.files || [];
    fillMethods(schedule.methods);
    if (!formsHydrated) {
      fillSetupForm();
      fillAdvanced();
      fillAudioForm();
      formsHydrated = true;
    } else {
      fillAdvanced();
      renderDuas();
    }
    renderHome();
    renderDuas();
  }

  async function patch(body) {
    state.config = await api("/api/config", {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    await refresh();
  }

  // Tabs
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => showView(tab.dataset.view));
  });
  $$("[data-goto]").forEach((el) => {
    el.addEventListener("click", () => showView(el.dataset.goto));
  });

  $("#btnTest").onclick = () => api("/api/play", { method: "POST", body: JSON.stringify({ kind: "test" }) });
  $("#btnStop").onclick = () => api("/api/stop", { method: "POST", body: "{}" });
  $("#btnSkip").onclick = () => api("/api/skip", { method: "POST", body: "{}" });
  $("#btnMute").onclick = () =>
    api("/api/mute", { method: "POST", body: JSON.stringify({ minutes: 60 }) });

  let volTimer;
  $("#volume").addEventListener("input", (e) => {
    $("#volVal").textContent = e.target.value;
    clearTimeout(volTimer);
    volTimer = setTimeout(() => patch({ volume: Number(e.target.value) }), 300);
  });

  function applyGeoResult(row, { keepTypedName } = {}) {
    if (!row) return;
    if (row.latitude != null) $("#latitude").value = Number(row.latitude).toFixed(5);
    if (row.longitude != null) $("#longitude").value = Number(row.longitude).toFixed(5);
    if (row.timezone) $("#timezone").value = row.timezone;
    if (!keepTypedName || !$("#locationName").value.trim()) {
      $("#locationName").value = row.name || row.display_name || $("#locationName").value;
    }
  }

  $("#btnGeo").onclick = () => {
    if (!navigator.geolocation) {
      alert("This browser can’t share location. Type a city and pick a suggestion, or enter coordinates.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        $("#latitude").value = lat.toFixed(5);
        $("#longitude").value = lon.toFixed(5);
        $("#timezone").value = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (!$("#locationName").value.trim()) {
          $("#locationName").value = "My location";
        }
        try {
          const tz = await api(`/api/geocode/timezone?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`);
          if (tz.timezone) $("#timezone").value = tz.timezone;
        } catch (_) {
          /* phone timezone already filled */
        }
        try {
          const rev = await api(`/api/geocode/reverse?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`);
          applyGeoResult(rev, { keepTypedName: true });
        } catch (_) {
          /* coords are enough */
        }
      },
      (err) => alert(err.message || "Could not get location. Type a city instead."),
      { enableHighAccuracy: false, timeout: 10000 }
    );
  };

  function bindLocationSearch() {
    const input = $("#locationName");
    const list = $("#locationSuggest");
    const hint = $("#locationSearchHint");
    if (!input || !list) return;

    let timer = null;
    let abort = null;
    let items = [];
    let active = -1;
    let lastQuery = "";

    function hide() {
      list.classList.add("hidden");
      list.innerHTML = "";
      input.setAttribute("aria-expanded", "false");
      active = -1;
    }

    function show(rows, message) {
      items = rows || [];
      if (hint) hint.textContent = message || "";
      if (!items.length) {
        hide();
        return;
      }
      list.innerHTML = items
        .map(
          (row, i) =>
            `<li role="option" data-i="${i}" class="${i === active ? "active" : ""}">
              ${escapeHtml(row.name || row.display_name || "")}
              <span class="meta">${escapeHtml(
                [
                  row.timezone,
                  row.latitude != null ? `${Number(row.latitude).toFixed(3)}, ${Number(row.longitude).toFixed(3)}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")
              )}</span>
            </li>`
        )
        .join("");
      list.classList.remove("hidden");
      input.setAttribute("aria-expanded", "true");
      list.querySelectorAll("li").forEach((li) => {
        li.addEventListener("mousedown", (e) => {
          e.preventDefault();
          pick(Number(li.dataset.i));
        });
      });
    }

    function pick(i) {
      const row = items[i];
      if (!row) return;
      applyGeoResult(row);
      lastQuery = $("#locationName").value;
      hide();
      if (hint) hint.textContent = "Location filled from that suggestion.";
    }

    async function search(q) {
      if (q.length < 2) {
        hide();
        if (hint) hint.textContent = "";
        return;
      }
      if (abort) abort.abort();
      abort = new AbortController();
      if (hint) hint.textContent = "Searching…";
      try {
        const data = await api(`/api/geocode/search?q=${encodeURIComponent(q)}&limit=6`, {
          signal: abort.signal,
        });
        if (input.value.trim() !== q) return;
        if (data.offline) {
          show([], data.error || "Can’t search offline. Enter coordinates and timezone manually.");
          if (hint) hint.textContent = data.error || "Can’t search offline. Enter coordinates manually.";
          return;
        }
        const rows = data.results || [];
        if (!rows.length) {
          show([], "No matches. Try a city name, or enter coordinates.");
          if (hint) hint.textContent = "No matches. Try a city name, or enter coordinates.";
          return;
        }
        show(rows, "");
      } catch (e) {
        if (e.name === "AbortError") return;
        hide();
        if (hint) {
          hint.textContent =
            "Search failed. Check that the speaker is online, or enter latitude and longitude.";
        }
      }
    }

    input.addEventListener("input", () => {
      const q = input.value.trim();
      lastQuery = q;
      clearTimeout(timer);
      timer = setTimeout(() => search(q), 350);
    });
    input.addEventListener("keydown", (e) => {
      if (list.classList.contains("hidden")) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        active = Math.min(items.length - 1, active + 1);
        show(items, hint ? hint.textContent : "");
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        active = Math.max(0, active - 1);
        show(items, hint ? hint.textContent : "");
      } else if (e.key === "Enter") {
        if (active >= 0) {
          e.preventDefault();
          pick(active);
        }
      } else if (e.key === "Escape") {
        hide();
      }
    });
    input.addEventListener("blur", () => setTimeout(hide, 150));
  }

  bindLocationSearch();

  $$("#regularAdhanVolume, #fajrAdhanVolume, #regularDuaVolume, #fajrDuaVolume").forEach((el) => {
    el.addEventListener("input", () => {
      const map = {
        regularAdhanVolume: "regularAdhanVolVal",
        fajrAdhanVolume: "fajrAdhanVolVal",
        regularDuaVolume: "regularDuaVolVal",
        fajrDuaVolume: "fajrDuaVolVal",
      };
      const lab = document.getElementById(map[el.id]);
      if (lab) lab.textContent = el.value;
    });
  });

  const btnNext1 = $("#btnSetupNext1");
  if (btnNext1) btnNext1.onclick = () => showSetupStep(2);
  const btnNext2 = $("#btnSetupNext2");
  if (btnNext2) {
    btnNext2.onclick = () => {
      if (!$("#latitude").value || !$("#longitude").value) {
        alert("Type a city and pick a suggestion, tap “Use this phone’s location”, or enter latitude and longitude.");
        return;
      }
      showSetupStep(3);
    };
  }
  const btnNext3 = $("#btnSetupNext3");
  if (btnNext3) btnNext3.onclick = () => showSetupStep(4);
  $$("[data-setup-step]").forEach((el) => {
    el.addEventListener("click", () => showSetupStep(Number(el.dataset.setupStep)));
  });

  $("#btnSaveSetup").onclick = async () => {
    const enabled = $$("#prayerToggles input:checked").map((el) => el.value);
    const lat = Number($("#latitude").value);
    const lon = Number($("#longitude").value);
    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      alert("Location is required so prayer times can be calculated.");
      showSetupStep(2);
      return;
    }
    await patch({
      setup_complete: true,
      location_name: $("#locationName").value.trim() || "My location",
      latitude: lat,
      longitude: lon,
      timezone: $("#timezone").value.trim() || Intl.DateTimeFormat().resolvedOptions().timeZone,
      method: Number($("#method").value),
      school: Number($("#school").value),
      volume: Number($("#setupVolume").value),
      fajr_volume: Number($("#fajrVolume").value),
      audio_output: $("#audioOutput").value,
      enabled_prayers: enabled,
    });
    document.body.classList.remove("first-run");
    showView("home");
  };

  $("#btnPlayAdhan").onclick = () =>
    api("/api/play", { method: "POST", body: JSON.stringify({ kind: "adhan" }) });
  $("#btnPlayFajr").onclick = () =>
    api("/api/play", { method: "POST", body: JSON.stringify({ kind: "fajr" }) });
  const btnPlayDua = $("#btnPlayDua");
  if (btnPlayDua) {
    btnPlayDua.onclick = () =>
      api("/api/play", { method: "POST", body: JSON.stringify({ kind: "dua" }) });
  }
  const btnPlayFajrDua = $("#btnPlayFajrDua");
  if (btnPlayFajrDua) {
    btnPlayFajrDua.onclick = () =>
      api("/api/play", { method: "POST", body: JSON.stringify({ kind: "fajr_dua" }) });
  }

  $("#duaEnabled").onchange = (e) => patch({ dua_enabled: e.target.checked });
  const fajrDuaEnabled = $("#fajrDuaEnabled");
  if (fajrDuaEnabled) {
    fajrDuaEnabled.onchange = (e) => patch({ fajr_dua_enabled: e.target.checked });
  }
  const fajrDuaId = $("#fajrDuaId");
  if (fajrDuaId) {
    fajrDuaId.onchange = (e) => {
      if (e.target.value) patch({ fajr_dua_id: e.target.value });
    };
  }

  const btnSaveAudio = $("#btnSaveAudio");
  if (btnSaveAudio) {
    btnSaveAudio.onclick = async () => {
      await patch({
        audio_file: $("#regularAdhanFile").value,
        fajr_audio_file: $("#fajrAdhanFile").value,
        volume: Number($("#regularAdhanVolume").value),
        fajr_volume: Number($("#fajrAdhanVolume").value),
        dua_enabled: $("#duaEnabled").checked,
        dua_volume: Number($("#regularDuaVolume").value),
        fajr_dua_enabled: $("#fajrDuaEnabled").checked,
        fajr_dua_id: $("#fajrDuaId").value || undefined,
        fajr_dua_volume: Number($("#fajrDuaVolume").value),
        prayer_overrides: collectPrayerOverrides(),
      });
      alert("Audio settings saved.");
    };
  }

  $("#duaList").addEventListener("click", async (e) => {
    const select = e.target.closest("[data-select]");
    const speaker = e.target.closest("[data-speaker]");
    if (select) {
      await patch({ dua_id: select.dataset.select, dua_enabled: true });
    }
    if (speaker) {
      await api("/api/play", {
        method: "POST",
        body: JSON.stringify({ kind: "dua", dua_id: speaker.dataset.speaker }),
      });
    }
  });

  const btnHotspot = $("#btnStartHotspot");
  if (btnHotspot) {
    btnHotspot.onclick = async () => {
      try {
        await api("/api/wifi/hotspot", { method: "POST", body: "{}" });
        await refresh();
        alert("Setup hotspot started. Join it from your phone, then open the Wi-Fi setup page.");
      } catch (e) {
        alert(e.message || "Could not start hotspot (needs NetworkManager on the Pi).");
      }
    };
  }

  $("#btnSaveAdvanced").onclick = async () => {
    if ($("#sleepEnabled").checked) {
      const ok = confirm(
        "Enable sleep outside prayer times?\n\n" +
          "While asleep, the web portal at http://adhan.local will NOT be reachable " +
          "(Wi-Fi and the Pi are suspended). The device wakes ~3 minutes before each prayer.\n\n" +
          "Leave this off if you want the portal available anytime."
      );
      if (!ok) {
        $("#sleepEnabled").checked = false;
        return;
      }
    }
    await patch({
      device_name: $("#deviceName").value.trim() || "Adhan Player",
      kahf_enabled: $("#kahfEnabled").checked,
      sleep_enabled: $("#sleepEnabled").checked,
      use_offline_times: $("#offlineTimes").checked,
      play_on_boot: $("#playOnBoot").checked,
      boot_sound: $("#playOnBoot").checked ? "chime" : "off",
      auto_update: $("#autoUpdate") ? $("#autoUpdate").checked : true,
      update_on_boot: $("#autoUpdate") ? $("#autoUpdate").checked : true,
      update_at_midnight: $("#autoUpdate") ? $("#autoUpdate").checked : true,
    });
    alert("Advanced settings saved.");
  };

  const btnCheck = $("#btnCheckUpdate");
  if (btnCheck) {
    btnCheck.onclick = async () => {
      try {
        const st = await api("/api/update/check", { method: "POST", body: "{}" });
        state.status = state.status || {};
        state.status.update = st;
        fillAdvanced();
        alert(st.update_available ? "An update is available. Tap Update now." : "Already up to date.");
      } catch (e) {
        alert(e.message || "Check failed (needs internet + git).");
      }
    };
  }
  const btnApply = $("#btnApplyUpdate");
  if (btnApply) {
    btnApply.onclick = async () => {
      if (!confirm("Update from GitHub now? Settings and your adhan audio are kept. The portal may restart.")) {
        return;
      }
      try {
        const res = await api("/api/update", { method: "POST", body: JSON.stringify({ apply: true }) });
        alert(res.message || "Update started.");
      } catch (e) {
        alert(e.message || "Update failed.");
      }
    };
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  refresh().catch((err) => {
    $("#deviceSub").textContent = "Could not reach API";
    console.error(err);
  });
  setInterval(() => refresh().catch(() => {}), 30000);
})();

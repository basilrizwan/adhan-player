(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];

  const state = {
    config: null,
    status: null,
    schedule: null,
    duas: [],
  };

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || res.statusText);
    }
    return res.json();
  }

  function showView(name) {
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  }

  function fillMethods(methods) {
    const sel = $("#method");
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
    const names = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"];
    box.innerHTML = names
      .map(
        (n) => `<label><input type="checkbox" value="${n}" ${
          (enabled || names).includes(n) ? "checked" : ""
        }/> ${n}</label>`
      )
      .join("");
  }

  function renderHome() {
    const st = state.status || {};
    const cfg = state.config || {};
    const sched = state.schedule || {};
    const next = st.state?.next_prayer || sched.next_prayer;
    const nextAt = st.state?.next_prayer_at || sched.next_prayer_at;

    $("#deviceSub").textContent = cfg.device_name || "Adhan Player";
    $("#nextPrayer").textContent = next || "—";
    $("#nextTime").textContent = nextAt
      ? new Date(nextAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      : "—";
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

    const wifi = st.wifi || {};
    const wifiBanner = $("#wifiBanner");
    if (wifi.hotspot_active || wifi.mode === "hotspot") {
      wifiBanner.innerHTML = `Setup hotspot is on: join <strong>${wifi.hotspot_ssid || "Adhan-XXXX"}</strong> / <strong>${wifi.hotspot_password || "adhan-setup"}</strong>, then open <a href="/wifi">Wi‑Fi setup</a>.`;
      wifiBanner.classList.remove("hidden");
    } else if (wifi.mode === "offline") {
      wifiBanner.innerHTML = `Not on Wi‑Fi yet. The device will start a setup hotspot shortly, or open the <a href="/wifi">Wi‑Fi setup page</a>.`;
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
          ? `Hotspot: ${wifi.hotspot_ssid} / ${wifi.hotspot_password}`
          : `Setup hotspot SSID would be: ${wifi.hotspot_ssid || "Adhan-XXXX"}`,
        `Online: ${wifi.online ? "yes" : "no"}`,
        `Auto-hotspot when offline: ${cfg.wifi_hotspot_auto === false ? "off" : "on"}`,
      ]
        .filter(Boolean)
        .join("\n");
    }

    const times = sched.today || st.state?.today_times || {};
    const list = $("#todayList");
    list.innerHTML = Object.keys(times).length
      ? Object.entries(times)
          .map(([name, t]) => {
            const isNext = name === next;
            return `<li class="${isNext ? "next" : ""}"><span>${name}</span><strong>${t}</strong></li>`;
          })
          .join("")
      : "<li><span>No times yet</span><strong>—</strong></li>";

    const urls = st.urls || [];
    $("#deviceInfo").textContent = [
      `Open: ${urls[0] || "http://adhan.local:8080"}`,
      urls.length > 1 ? `Also: ${urls.slice(1).join(", ")}` : null,
      `Sleep mode: ${cfg.sleep_enabled ? "ON (portal may be offline)" : "off"}`,
      `Dua: ${cfg.dua_enabled ? cfg.dua_id : "disabled"}`,
    ]
      .filter(Boolean)
      .join("\n");

    const vol = cfg.volume ?? 80;
    $("#volume").value = vol;
    $("#volVal").textContent = vol;

    const primary = urls[0] || window.location.origin;
    const qrHost = $("#qr");
    if (window.QRCode && qrHost && qrHost.dataset.url !== primary) {
      qrHost.innerHTML = "";
      qrHost.dataset.url = primary;
      // eslint-disable-next-line no-new
      new QRCode(qrHost, { text: primary, width: 160, height: 160 });
    }

    api("/api/logs?lines=30")
      .then((data) => {
        $("#logBox").textContent = (data.lines || []).join("\n") || "No logs yet.";
      })
      .catch(() => {
        $("#logBox").textContent = "Could not load logs.";
      });
  }

  function renderDuas() {
    const selected = state.config?.dua_id;
    $("#duaEnabled").checked = !!state.config?.dua_enabled;
    const box = $("#duaList");
    box.innerHTML = (state.duas || [])
      .map((d) => {
        const unavailable = d.available ? "" : `<p class="hint">Audio file missing on device.</p>`;
        return `<article class="dua ${d.id === selected ? "selected" : ""}" data-id="${d.id}">
          <h3>${d.title}</h3>
          <p class="muted">${d.description}</p>
          <p class="arabic">${d.arabic}</p>
          <p class="hint">${d.transliteration}</p>
          <p class="muted">${d.english}</p>
          ${unavailable}
          <audio controls preload="none" src="${d.url}"></audio>
          <div class="actions">
            <button type="button" data-select="${d.id}">Use this dua</button>
            <button type="button" class="ghost" data-speaker="${d.id}">Play on speaker</button>
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
      const local = (u.local_commit || "—").slice(0, 8);
      const remote = (u.remote_commit || "—").slice(0, 8);
      info.textContent = [
        `App ${state.status?.version || ""} · git ${local}`,
        u.update_available ? `Update available (${remote})` : "Up to date with GitHub (or not checked yet)",
        u.next_midnight ? `Next midnight check: ${u.next_midnight}` : null,
        u.last_error ? `Last error: ${u.last_error}` : null,
      ]
        .filter(Boolean)
        .join("\n");
    }

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

  $("#btnGeo").onclick = () => {
    if (!navigator.geolocation) {
      alert("Geolocation not available in this browser.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        $("#latitude").value = pos.coords.latitude.toFixed(5);
        $("#longitude").value = pos.coords.longitude.toFixed(5);
        if (!$("#timezone").value) {
          $("#timezone").value = Intl.DateTimeFormat().resolvedOptions().timeZone;
        }
      },
      (err) => alert(err.message),
      { enableHighAccuracy: false, timeout: 10000 }
    );
  };

  $("#btnSaveSetup").onclick = async () => {
    const enabled = $$("#prayerToggles input:checked").map((el) => el.value);
    await patch({
      setup_complete: true,
      location_name: $("#locationName").value.trim(),
      latitude: Number($("#latitude").value),
      longitude: Number($("#longitude").value),
      timezone: $("#timezone").value.trim(),
      method: Number($("#method").value),
      school: Number($("#school").value),
      volume: Number($("#setupVolume").value),
      fajr_volume: Number($("#fajrVolume").value),
      audio_output: $("#audioOutput").value,
      enabled_prayers: enabled,
    });
    showView("home");
    alert("Setup saved.");
  };

  $("#btnPlayAdhan").onclick = () =>
    api("/api/play", { method: "POST", body: JSON.stringify({ kind: "adhan" }) });
  $("#btnPlayFajr").onclick = () =>
    api("/api/play", { method: "POST", body: JSON.stringify({ kind: "fajr" }) });

  $("#duaEnabled").onchange = (e) => patch({ dua_enabled: e.target.checked });

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
        alert("Setup hotspot started. Join it from your phone, then open the Wi‑Fi setup page.");
      } catch (e) {
        alert(e.message || "Could not start hotspot (needs NetworkManager on the Pi).");
      }
    };
  }

  $("#btnSaveAdvanced").onclick = async () => {
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

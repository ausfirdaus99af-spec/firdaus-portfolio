/* EcoFlow dashboard
   Consumes data/dashboard_data.json (precomputed by the Python pipeline).
   All data is synthetic; see docs/METHODOLOGY.md. */
(function () {
  "use strict";

  var COLORS = {
    lime: "#D9FF8B",
    text: "#F3F5EF",
    text2: "#B5C6BF",
    green: "#28634D",
    teal: "#7FD6C2",
    amber: "#F5C878",
    red: "#F08A6C",
    grid: "rgba(243, 245, 239, 0.08)"
  };

  var state = {
    data: null,
    scenario: "baseline",
    param: "cod",
    from: null, // "YYYY-MM-DD"
    to: null
  };

  var charts = {};

  // ---------- helpers ----------

  function $(id) { return document.getElementById(id); }

  function fmt(value, dp, suffix) {
    if (value === null || value === undefined || !isFinite(value)) { return "–"; }
    var n = Number(value).toLocaleString("en-GB", {
      minimumFractionDigits: dp,
      maximumFractionDigits: dp
    });
    return suffix ? n + suffix : n;
  }

  function dailyInRange(scenarioName) {
    var all = state.data.scenarios[scenarioName].daily;
    return all.filter(function (d) {
      return (!state.from || d.date >= state.from) && (!state.to || d.date <= state.to);
    });
  }

  function sum(rows, key) {
    var total = 0, seen = false;
    rows.forEach(function (r) {
      if (r[key] !== null && r[key] !== undefined && isFinite(r[key])) {
        total += r[key];
        seen = true;
      }
    });
    return seen ? total : null;
  }

  // Volume-weighted removal over a range:
  // 1 - (sum(out_conc x volume) / sum(in_conc x volume)), as %.
  function rangeRemoval(rows, inKey, outKey) {
    var massIn = 0, massOut = 0;
    rows.forEach(function (r) {
      var v = r.volume_m3;
      if (v && isFinite(v) && r[inKey] != null && r[outKey] != null &&
          isFinite(r[inKey]) && isFinite(r[outKey]) && r[inKey] > 0) {
        massIn += r[inKey] * v;
        massOut += r[outKey] * v;
      }
    });
    if (massIn <= 0) { return null; }
    return (1 - massOut / massIn) * 100;
  }

  function safeDiv(a, b) {
    if (a === null || b === null || !isFinite(a) || !isFinite(b) || b === 0) { return null; }
    return a / b;
  }

  // ---------- KPIs ----------

  function renderKpis() {
    var rows = dailyInRange(state.scenario);
    var volume = sum(rows, "volume_m3");
    var energy = sum(rows, "energy_kwh");
    var chem = sum(rows, "chemical_kg");

    $("kpi-cod").textContent = fmt(rangeRemoval(rows, "cod_in_mgl", "cod_out_mgl"), 1, "%");
    $("kpi-bod").textContent = fmt(rangeRemoval(rows, "bod_in_mgl", "bod_out_mgl"), 1, "%");
    $("kpi-tss").textContent = fmt(rangeRemoval(rows, "tss_in_mgl", "tss_out_mgl"), 1, "%");
    $("kpi-volume").textContent = fmt(volume, 0);
    $("kpi-energy").textContent = fmt(safeDiv(energy, volume), 2);
    $("kpi-chem").textContent = fmt(safeDiv(chem === null ? null : chem * 1000, volume), 1);
    $("kpi-anom").textContent = fmt(sum(rows, "anomaly_count"), 0);
    $("kpi-upset").textContent = fmt(rows.filter(function (r) { return r.upset_hours > 0; }).length, 0);

    var scenarioNames = { baseline: "normal running", optimised: "improved settings" };
    $("kpi-range").textContent = rows.length
      ? rows[0].date + " to " + rows[rows.length - 1].date + " · " + rows.length + " days · " + (scenarioNames[state.scenario] || state.scenario)
      : "no days in selected range";
  }

  // ---------- sustainability (always full period, both scenarios) ----------

  function renderSustainability() {
    var base = state.data.scenarios.baseline.daily;
    var opt = state.data.scenarios.optimised.daily;

    var eBase = sum(base, "energy_kwh"), eOpt = sum(opt, "energy_kwh");
    var cBase = sum(base, "chemical_kg"), cOpt = sum(opt, "chemical_kg");
    var vBase = sum(base, "volume_m3"), vOpt = sum(opt, "volume_m3");

    function delta(a, b) {
      if (a === null || b === null || a === 0) { return null; }
      return ((b - a) / a) * 100;
    }
    function signed(value) {
      if (value === null) { return "–"; }
      return (value > 0 ? "+" : "") + fmt(value, 1, "%");
    }

    $("sust-energy").textContent = signed(delta(eBase, eOpt));
    $("sust-energy-abs").textContent = fmt(eBase, 0) + " → " + fmt(eOpt, 0) + " kWh, full period";
    $("sust-chem").textContent = signed(delta(cBase, cOpt));
    $("sust-chem-abs").textContent = fmt(cBase, 0) + " → " + fmt(cOpt, 0) + " kg, full period";
    $("sust-senergy").textContent = fmt(safeDiv(eBase, vBase), 2) + " → " + fmt(safeDiv(eOpt, vOpt), 2);
    $("sust-schem").textContent =
      fmt(safeDiv(cBase === null ? null : cBase * 1000, vBase), 1) + " → " +
      fmt(safeDiv(cOpt === null ? null : cOpt * 1000, vOpt), 1);

    var list = $("assumptions-list");
    list.innerHTML = "";
    (state.data.meta.assumptions || []).forEach(function (text) {
      var li = document.createElement("li");
      li.textContent = text;
      list.appendChild(li);
    });
  }

  // ---------- charts ----------

  function baseOptions(yTitle, y1Title) {
    var opts = {
      responsive: true,
      maintainAspectRatio: false,
      animation: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 350 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: COLORS.text2, boxWidth: 14, boxHeight: 14, usePointStyle: true } },
        tooltip: {
          backgroundColor: "#0c2a26",
          borderColor: "rgba(217,255,139,0.3)",
          borderWidth: 1,
          titleColor: COLORS.text,
          bodyColor: COLORS.text2
        }
      },
      scales: {
        x: {
          ticks: { color: COLORS.text2, maxTicksLimit: 10, maxRotation: 0 },
          grid: { color: COLORS.grid }
        },
        y: {
          ticks: { color: COLORS.text2 },
          grid: { color: COLORS.grid },
          title: { display: !!yTitle, text: yTitle || "", color: COLORS.text2 }
        }
      }
    };
    if (y1Title) {
      opts.scales.y1 = {
        position: "right",
        ticks: { color: COLORS.text2 },
        grid: { drawOnChartArea: false },
        title: { display: true, text: y1Title, color: COLORS.text2 },
        beginAtZero: true
      };
    }
    return opts;
  }

  function line(label, data, color, extra) {
    return Object.assign({
      type: "line",
      label: label,
      data: data,
      borderColor: color,
      backgroundColor: color,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: 0.25,
      spanGaps: false
    }, extra || {});
  }

  function bars(label, data, color, extra) {
    return Object.assign({
      type: "bar",
      label: label,
      data: data,
      backgroundColor: color,
      borderWidth: 0,
      maxBarThickness: 14
    }, extra || {});
  }

  function destroy(name) {
    if (charts[name]) { charts[name].destroy(); charts[name] = null; }
  }

  function renderCharts() {
    var rows = dailyInRange(state.scenario);
    var labels = rows.map(function (r) { return r.date; });
    var p = state.param; // cod | bod | tss

    destroy("inout");
    charts.inout = new Chart($("chart-inout"), {
      data: {
        labels: labels,
        datasets: [
          line("Influent " + p.toUpperCase() + " (mg/L)", rows.map(function (r) { return r[p + "_in_mgl"]; }), COLORS.teal),
          line("Effluent " + p.toUpperCase() + " (mg/L)", rows.map(function (r) { return r[p + "_out_mgl"]; }), COLORS.lime)
        ]
      },
      options: baseOptions("mg/L")
    });

    destroy("removal");
    charts.removal = new Chart($("chart-removal"), {
      data: {
        labels: labels,
        datasets: [
          line("COD removal (%)", rows.map(function (r) { return r.removal_cod_pct; }), COLORS.lime),
          line("BOD removal (%)", rows.map(function (r) { return r.removal_bod_pct; }), COLORS.teal),
          line("TSS removal (%)", rows.map(function (r) { return r.removal_tss_pct; }), COLORS.amber)
        ]
      },
      options: baseOptions("% removal")
    });

    destroy("quality");
    charts.quality = new Chart($("chart-quality"), {
      data: {
        labels: labels,
        datasets: [
          line("Effluent pH (avg)", rows.map(function (r) { return r.ph_out_avg; }), COLORS.lime),
          line("Influent pH (avg)", rows.map(function (r) { return r.ph_in_avg; }), COLORS.teal, { borderDash: [5, 4] }),
          bars("Anomalies/day", rows.map(function (r) { return r.anomaly_count; }), "rgba(240,138,108,0.75)", { yAxisID: "y1" })
        ]
      },
      options: (function () {
        var o = baseOptions("pH", "anomalies");
        o.scales.y.suggestedMin = 5;
        o.scales.y.suggestedMax = 10;
        return o;
      })()
    });

    destroy("energy");
    charts.energy = new Chart($("chart-energy"), {
      data: {
        labels: labels,
        datasets: [
          bars("Energy (kWh/day)", rows.map(function (r) { return r.energy_kwh; }), "rgba(40,99,77,0.85)"),
          line("Specific energy (kWh/m³)", rows.map(function (r) { return r.specific_energy_kwh_m3; }), COLORS.lime, { yAxisID: "y1" })
        ]
      },
      options: baseOptions("kWh/day", "kWh/m³")
    });

    destroy("chemical");
    charts.chemical = new Chart($("chart-chemical"), {
      data: {
        labels: labels,
        datasets: [
          bars("Coagulant (kg/day)", rows.map(function (r) { return r.chemical_kg; }), "rgba(127,214,194,0.55)"),
          line("Dose (g/m³)", rows.map(function (r) { return r.chemical_g_m3; }), COLORS.lime, { yAxisID: "y1" })
        ]
      },
      options: baseOptions("kg/day", "g/m³")
    });
  }

  function renderAll() {
    renderKpis();
    renderCharts();
  }

  // ---------- controls ----------

  function wireControls() {
    var range = state.data.meta.date_range;

    var from = $("date-from"), to = $("date-to");
    from.min = range.start; from.max = range.end; from.value = range.start;
    to.min = range.start; to.max = range.end; to.value = range.end;
    state.from = range.start;
    state.to = range.end;

    function clearPresets() {
      document.querySelectorAll(".preset-btn").forEach(function (b) { b.classList.remove("is-active"); });
    }

    from.addEventListener("change", function () {
      if (from.value && to.value && from.value > to.value) { to.value = from.value; }
      state.from = from.value || range.start;
      state.to = to.value || range.end;
      clearPresets();
      renderAll();
    });
    to.addEventListener("change", function () {
      if (from.value && to.value && to.value < from.value) { from.value = to.value; }
      state.from = from.value || range.start;
      state.to = to.value || range.end;
      clearPresets();
      renderAll();
    });

    document.querySelectorAll(".preset-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        clearPresets();
        btn.classList.add("is-active");
        var days = btn.getAttribute("data-days");
        if (days === "all") {
          state.from = range.start;
          state.to = range.end;
        } else {
          var end = new Date(range.end + "T00:00:00");
          var start = new Date(end);
          start.setDate(end.getDate() - (parseInt(days, 10) - 1));
          var iso = start.toISOString().slice(0, 10);
          state.from = iso < range.start ? range.start : iso;
          state.to = range.end;
        }
        from.value = state.from;
        to.value = state.to;
        renderAll();
      });
    });

    $("scenario-select").addEventListener("change", function (event) {
      state.scenario = event.target.value;
      renderAll();
    });

    document.querySelectorAll(".param-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll(".param-btn").forEach(function (b) { b.classList.remove("is-active"); });
        btn.classList.add("is-active");
        state.param = btn.getAttribute("data-param");
        renderCharts();
      });
    });
  }

  // ---------- boot ----------

  function showError(detail) {
    $("load-error").hidden = false;
    if (detail) { $("load-error-detail").textContent = detail; }
  }

  if (typeof Chart === "undefined") {
    showError("The charting library could not be loaded. Please check the network connection and reload.");
    return;
  }

  Chart.defaults.font.family = '"Archivo", "Segoe UI", system-ui, sans-serif';
  Chart.defaults.color = COLORS.text2;

  fetch("data/dashboard_data.json")
    .then(function (response) {
      if (!response.ok) { throw new Error("HTTP " + response.status); }
      return response.json();
    })
    .then(function (json) {
      if (!json || !json.scenarios || !json.scenarios.baseline || !json.scenarios.optimised) {
        throw new Error("Unexpected data format");
      }
      state.data = json;
      wireControls();
      renderSustainability();
      renderAll();
    })
    .catch(function (err) {
      if (window.location.protocol === "file:") {
        showError(null); // keep the default local-server hint
      } else {
        showError("The dataset could not be loaded (" + err.message + "). Please try reloading the page.");
      }
    });
})();

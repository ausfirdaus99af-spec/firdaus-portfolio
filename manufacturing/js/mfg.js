/* Manufacturing Performance Analytics dashboard.
   Consumes data/mfg_data.json (precomputed by the Python + SQLite pipeline).
   KPI aggregation mirrors scripts/kpis.py: time-weighted sums, never averaged
   percentages. The full-range result is checked against the precomputed
   kpis_overall from Python on load. */
(function () {
  "use strict";

  var COLORS = {
    lime: "#D9FF8B", text: "#F3F5EF", text2: "#B5C6BF",
    teal: "#7FD6C2", amber: "#F5C878", red: "#F08A6C",
    green: "#28634D", grid: "rgba(243, 245, 239, 0.08)"
  };

  var state = { data: null, line: "all", shift: "all", from: null, to: null };
  var charts = {};

  function $(id) { return document.getElementById(id); }
  function fmt(v, dp, suffix) {
    if (v === null || v === undefined || !isFinite(v)) { return "–"; }
    var n = Number(v).toLocaleString("en-GB", { minimumFractionDigits: dp, maximumFractionDigits: dp });
    return suffix ? n + suffix : n;
  }

  function idealRate(row) {
    var rates = state.data.meta.ideal_rates_uph || {};
    return (rates[row.line] || {})[row.cat] || null;
  }

  function filteredRows() {
    return state.data.rows.filter(function (r) {
      return (state.line === "all" || r.line === state.line) &&
             (state.shift === "all" || r.shift === state.shift) &&
             (!state.from || r.d >= state.from) &&
             (!state.to || r.d <= state.to);
    });
  }

  // Weighted KPI aggregation over a set of rows (mirrors kpis.py).
  function computeKpis(rows) {
    var plan = 0, act = 0, good = 0, rej = 0, pt = 0, rt = 0, dt = 0, kwh = 0, idealRun = 0, idealPlan = 0;
    rows.forEach(function (r) {
      var rate = idealRate(r);
      plan += r.plan; act += r.act; good += r.good; rej += r.rej;
      pt += r.pt; rt += r.rt; dt += r.dt; kwh += r.kwh;
      if (rate) { idealRun += rate * r.rt; idealPlan += rate * r.pt; }
    });
    function pct(a, b) { return b > 0 ? (a / b) * 100 : null; }
    var availability = pct(rt, pt);
    var performance = pct(act, idealRun);
    var quality = pct(good, act);
    var oee = (availability !== null && performance !== null && quality !== null)
      ? availability * performance * quality / 10000 : null;
    return {
      production_achievement_pct: pct(act, plan),
      capacity_utilisation_pct: pct(act, idealPlan),
      yield_pct: quality,
      rejection_rate_pct: pct(rej, act),
      availability_pct: availability,
      performance_pct: performance,
      quality_pct: quality,
      oee_pct: oee,
      energy_intensity_kwh_per_good_unit: good > 0 ? kwh / good : null,
      downtime_h: dt,
      energy_kwh: kwh
    };
  }

  function paretoFrom(rows) {
    var byReason = {};
    rows.forEach(function (r) {
      if (r.reason && r.reason !== "None" && r.dt > 0) {
        byReason[r.reason] = (byReason[r.reason] || 0) + r.dt;
      }
    });
    var entries = Object.keys(byReason).map(function (k) { return { reason: k, hours: byReason[k] }; });
    entries.sort(function (a, b) { return b.hours - a.hours; });
    var total = entries.reduce(function (s, e) { return s + e.hours; }, 0);
    var cum = 0;
    entries.forEach(function (e) {
      e.pct = total > 0 ? e.hours / total * 100 : 0;
      cum += e.pct;
      e.cum_pct = cum;
    });
    return entries;
  }

  function monthKey(d) { return d.slice(0, 7); }
  function monthsIn(rows) {
    var set = {};
    rows.forEach(function (r) { set[monthKey(r.d)] = true; });
    return Object.keys(set).sort();
  }

  // ---------- rendering ----------
  function renderKpis(rows) {
    var k = computeKpis(rows);
    $("kpi-oee").textContent = fmt(k.oee_pct, 1, "%");
    $("kpi-avail").textContent = fmt(k.availability_pct, 1, "%");
    $("kpi-perf").textContent = fmt(k.performance_pct, 1, "%");
    $("kpi-qual").textContent = fmt(k.quality_pct, 1, "%");
    $("kpi-ach").textContent = fmt(k.production_achievement_pct, 1, "%");
    $("kpi-cap").textContent = fmt(k.capacity_utilisation_pct, 1, "%");
    $("kpi-energy").textContent = fmt(k.energy_intensity_kwh_per_good_unit, 3);
    $("kpi-dt").textContent = fmt(k.downtime_h, 0);

    var bits = [];
    if (rows.length) { bits.push(rows[0].d.slice(0, 7) + " to " + rows[rows.length - 1].d.slice(0, 7)); }
    bits.push(state.line === "all" ? "all lines" : state.line);
    bits.push(state.shift === "all" ? "both shifts" : state.shift + " shift");
    $("kpi-range").textContent = bits.join(" · ");
  }

  function baseOptions(yTitle, y1Title) {
    var opts = {
      responsive: true,
      maintainAspectRatio: false,
      animation: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 300 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: COLORS.text2, boxWidth: 14, usePointStyle: true } },
        tooltip: {
          backgroundColor: "#0c2a26", borderColor: "rgba(217,255,139,0.3)", borderWidth: 1,
          titleColor: COLORS.text, bodyColor: COLORS.text2
        }
      },
      scales: {
        x: { ticks: { color: COLORS.text2, maxRotation: 0, maxTicksLimit: 12 }, grid: { color: COLORS.grid } },
        y: { ticks: { color: COLORS.text2 }, grid: { color: COLORS.grid },
             title: { display: !!yTitle, text: yTitle || "", color: COLORS.text2 } }
      }
    };
    if (y1Title) {
      opts.scales.y1 = {
        position: "right", ticks: { color: COLORS.text2 }, grid: { drawOnChartArea: false },
        title: { display: true, text: y1Title, color: COLORS.text2 }, beginAtZero: true
      };
    }
    return opts;
  }
  function destroy(name) { if (charts[name]) { charts[name].destroy(); charts[name] = null; } }
  function line(label, data, color, extra) {
    return Object.assign({ type: "line", label: label, data: data, borderColor: color, backgroundColor: color,
      borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25 }, extra || {});
  }
  function bars(label, data, color, extra) {
    return Object.assign({ type: "bar", label: label, data: data, backgroundColor: color, maxBarThickness: 26 }, extra || {});
  }

  function renderCharts(rows) {
    var months = monthsIn(rows);
    var byMonth = months.map(function (m) {
      return computeKpis(rows.filter(function (r) { return monthKey(r.d) === m; }));
    });

    destroy("trend");
    charts.trend = new Chart($("chart-oee-trend"), {
      data: {
        labels: months,
        datasets: [
          line("OEE (%)", byMonth.map(function (k) { return k.oee_pct; }), COLORS.lime, { borderWidth: 3 }),
          line("Availability (%)", byMonth.map(function (k) { return k.availability_pct; }), COLORS.teal, { borderDash: [6, 4] }),
          line("Performance (%)", byMonth.map(function (k) { return k.performance_pct; }), COLORS.amber, { borderDash: [6, 4] }),
          line("Quality (%)", byMonth.map(function (k) { return k.quality_pct; }), COLORS.red, { borderDash: [6, 4] })
        ]
      },
      options: baseOptions("%")
    });

    var pareto = paretoFrom(rows);
    destroy("pareto");
    charts.pareto = new Chart($("chart-pareto"), {
      data: {
        labels: pareto.map(function (e) { return e.reason; }),
        datasets: [
          bars("Hours lost", pareto.map(function (e) { return e.hours; }), "rgba(240,138,108,0.75)"),
          line("Cumulative (%)", pareto.map(function (e) { return e.cum_pct; }), COLORS.lime, { yAxisID: "y1" })
        ]
      },
      options: (function () {
        var o = baseOptions("hours", "cumulative %");
        o.scales.y1.max = 100;
        return o;
      })()
    });

    // line comparison uses the date/shift filters but always shows all lines
    var lines = state.data.meta.lines;
    var lineKpis = lines.map(function (ln) {
      return computeKpis(state.data.rows.filter(function (r) {
        return r.line === ln &&
               (state.shift === "all" || r.shift === state.shift) &&
               (!state.from || r.d >= state.from) && (!state.to || r.d <= state.to);
      }));
    });
    destroy("lines");
    charts.lines = new Chart($("chart-lines"), {
      data: {
        labels: lines,
        datasets: [
          bars("Availability (%)", lineKpis.map(function (k) { return k.availability_pct; }), "rgba(127,214,194,0.8)"),
          bars("Performance (%)", lineKpis.map(function (k) { return k.performance_pct; }), "rgba(245,200,120,0.8)"),
          bars("Quality (%)", lineKpis.map(function (k) { return k.quality_pct; }), "rgba(181,198,191,0.8)"),
          bars("OEE (%)", lineKpis.map(function (k) { return k.oee_pct; }), COLORS.lime)
        ]
      },
      options: baseOptions("%")
    });

    // shift comparison uses date/line filters but always shows both shifts
    var shifts = state.data.meta.shifts;
    var shiftKpis = shifts.map(function (sh) {
      return computeKpis(state.data.rows.filter(function (r) {
        return r.shift === sh &&
               (state.line === "all" || r.line === state.line) &&
               (!state.from || r.d >= state.from) && (!state.to || r.d <= state.to);
      }));
    });
    destroy("shifts");
    charts.shifts = new Chart($("chart-shifts"), {
      data: {
        labels: shifts,
        datasets: [
          bars("Availability (%)", shiftKpis.map(function (k) { return k.availability_pct; }), "rgba(127,214,194,0.8)"),
          bars("Performance (%)", shiftKpis.map(function (k) { return k.performance_pct; }), "rgba(245,200,120,0.8)"),
          bars("OEE (%)", shiftKpis.map(function (k) { return k.oee_pct; }), COLORS.lime)
        ]
      },
      options: baseOptions("%")
    });

    destroy("energy");
    charts.energy = new Chart($("chart-energy-trend"), {
      data: {
        labels: months,
        datasets: [
          bars("Electricity (kWh)", byMonth.map(function (k) { return k.energy_kwh; }), "rgba(40,99,77,0.85)"),
          line("kWh per good unit", byMonth.map(function (k) { return k.energy_intensity_kwh_per_good_unit; }), COLORS.lime, { yAxisID: "y1" })
        ]
      },
      options: baseOptions("kWh", "kWh/unit")
    });

    var cats = state.data.meta.categories;
    destroy("reject");
    charts.reject = new Chart($("chart-reject"), {
      data: {
        labels: months,
        datasets: cats.map(function (cat, i) {
          var catColor = [COLORS.teal, COLORS.amber][i % 2];
          return line(cat + " rejection (%)", months.map(function (m) {
            var k = computeKpis(rows.filter(function (r) { return monthKey(r.d) === m && r.cat === cat; }));
            return k.rejection_rate_pct;
          }), catColor);
        })
      },
      options: baseOptions("% rejected")
    });
  }

  function renderScenario() {
    var sc = state.data.scenario;
    if (!sc) { return; }
    $("scenario-desc").textContent = sc.description || "";
    var list = $("scenario-assumptions");
    list.innerHTML = "";
    (sc.assumptions || []).forEach(function (t) {
      var li = document.createElement("li");
      li.textContent = t;
      list.appendChild(li);
    });

    var grid = $("scenario-grid");
    grid.innerHTML = "";
    [
      { label: "OEE", key: "oee_pct", dp: 1, suffix: "%" },
      { label: "Availability", key: "availability_pct", dp: 1, suffix: "%" },
      { label: "Downtime", key: "downtime_h", dp: 0, suffix: " h" },
      { label: "Energy intensity", key: "energy_intensity_kwh_per_good_unit", dp: 3, suffix: "" }
    ].forEach(function (item) {
      var baseV = sc.kpis_baseline ? sc.kpis_baseline[item.key] : null;
      var impV = sc.kpis_improved ? sc.kpis_improved[item.key] : null;
      var card = document.createElement("div");
      card.className = "sust-card";
      card.innerHTML = '<span class="kpi-label">' + item.label + '</span>' +
        '<span class="kpi-value">' + fmt(baseV, item.dp) + ' → ' + fmt(impV, item.dp) + (item.suffix || "") + '</span>' +
        '<span class="kpi-unit">baseline → modelled improvement</span>';
      grid.appendChild(card);
    });
  }

  function renderDefinitions() {
    var defs = state.data.meta.definitions || {};
    var grid = $("def-grid");
    grid.innerHTML = "";
    Object.keys(defs).forEach(function (key) {
      var card = document.createElement("div");
      card.className = "def-card";
      var h = document.createElement("h3");
      h.textContent = key.replace(/_pct$/, " (%)").replace(/_/g, " ");
      var p = document.createElement("p");
      p.textContent = defs[key];
      card.appendChild(h);
      card.appendChild(p);
      grid.appendChild(card);
    });
  }

  function renderAll() {
    var rows = filteredRows();
    renderKpis(rows);
    renderCharts(rows);
  }

  // ---------- controls ----------
  function wireControls() {
    var range = state.data.meta.date_range;
    var from = $("date-from"), to = $("date-to");
    from.min = range.start; from.max = range.end; from.value = range.start;
    to.min = range.start; to.max = range.end; to.value = range.end;
    state.from = range.start; state.to = range.end;

    function clearPresets() {
      document.querySelectorAll(".preset-btn").forEach(function (b) { b.classList.remove("is-active"); });
    }
    from.addEventListener("change", function () {
      if (from.value > to.value) { to.value = from.value; }
      state.from = from.value || range.start; state.to = to.value || range.end;
      clearPresets(); renderAll();
    });
    to.addEventListener("change", function () {
      if (to.value < from.value) { from.value = to.value; }
      state.from = from.value || range.start; state.to = to.value || range.end;
      clearPresets(); renderAll();
    });
    document.querySelectorAll(".preset-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        clearPresets(); btn.classList.add("is-active");
        var months = btn.getAttribute("data-months");
        if (months === "all") {
          state.from = range.start; state.to = range.end;
        } else {
          var end = new Date(range.end + "T00:00:00");
          var start = new Date(end);
          start.setMonth(end.getMonth() - parseInt(months, 10));
          start.setDate(start.getDate() + 1);
          var iso = start.toISOString().slice(0, 10);
          state.from = iso < range.start ? range.start : iso;
          state.to = range.end;
        }
        from.value = state.from; to.value = state.to;
        renderAll();
      });
    });
    $("line-select").addEventListener("change", function (e) { state.line = e.target.value; renderAll(); });
    $("shift-select").addEventListener("change", function (e) { state.shift = e.target.value; renderAll(); });
  }

  // Parity check against the Python pipeline (full range, all lines/shifts).
  function selfCheck() {
    var ref = state.data.kpis_overall;
    if (!ref) { return; }
    var mine = computeKpis(state.data.rows);
    ["oee_pct", "availability_pct", "performance_pct", "quality_pct"].forEach(function (key) {
      if (ref[key] !== undefined && mine[key] !== null && Math.abs(ref[key] - mine[key]) > 0.05) {
        console.warn("KPI parity mismatch for " + key + ": js=" + mine[key].toFixed(3) + " python=" + ref[key]);
      }
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

  fetch("data/mfg_data.json")
    .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
    .then(function (json) {
      if (!json || !json.rows || !json.meta) { throw new Error("Unexpected data format"); }
      state.data = json;
      wireControls();
      selfCheck();
      renderScenario();
      renderDefinitions();
      renderAll();
    })
    .catch(function (err) {
      if (window.location.protocol !== "file:") {
        showError("The dataset could not be loaded (" + err.message + "). Please try reloading the page.");
      } else {
        showError(null);
      }
    });
})();

/* SNG Plant Design dashboard.
   Consumes data/sng_data.json (precomputed by the Python model). */
(function () {
  "use strict";

  var COLORS = {
    lime: "#D9FF8B", text: "#F3F5EF", text2: "#B5C6BF",
    teal: "#7FD6C2", amber: "#F5C878", red: "#F08A6C",
    green: "#28634D", grid: "rgba(243, 245, 239, 0.08)"
  };
  var SPECIES = ["H2", "CO", "CO2", "CH4", "N2", "H2O"];
  var SPECIES_LABELS = ["H₂", "CO", "CO₂", "CH₄", "N₂", "H₂O"];
  var SPECIES_COLORS = ["#7FD6C2", "#F5C878", "#B5C6BF", "#D9FF8B", "#8AA69B", "#6FA8DC"];

  var state = { data: null, scenario: "base", activeUnit: null };
  var charts = {};

  function $(id) { return document.getElementById(id); }
  function fmt(v, dp, suffix) {
    if (v === null || v === undefined || !isFinite(v)) { return "–"; }
    var n = Number(v).toLocaleString("en-GB", { minimumFractionDigits: dp, maximumFractionDigits: dp });
    return suffix ? n + suffix : n;
  }
  function scn() { return state.data.scenarios[state.scenario]; }

  // ---------- KPIs ----------
  function renderKpis() {
    var s = scn();
    $("kpi-sng").textContent = fmt(s.kpis.sng_kg_h, 0);
    $("kpi-annual").textContent = fmt(s.kpis.annual_mt, 0);
    $("kpi-purity").textContent = fmt(s.kpis.ch4_purity_dry_molpct, 1, "%");
    $("kpi-conv").textContent = fmt(s.kpis.co_conversion_pct, 1, "%");
    $("kpi-yield").textContent = fmt(s.kpis.ch4_yield_pct, 1, "%");
    $("kpi-cge").textContent = fmt(s.kpis.cold_gas_efficiency_pct, 1, "%");
    $("kpi-closure").textContent = fmt(s.mass_balance.closure_pct, 2, "%");
    $("kpi-cool").textContent = fmt(s.kpis.specific_cooling_kwh_kg, 2);
    $("kpi-scenario").textContent = s.label;
    $("scenario-note").textContent = s.description || "";
  }

  // ---------- PFD panel ----------
  function unitOutletStream(unitId) {
    var streams = scn().streams || [];
    for (var i = 0; i < streams.length; i++) {
      if (streams[i].after_unit === unitId) { return streams[i]; }
    }
    return null;
  }

  function renderUnitPanel(unitId) {
    var units = state.data.process.units || [];
    var unit = null;
    units.forEach(function (u) { if (u.id === unitId) { unit = u; } });
    if (!unit) { return; }

    document.querySelectorAll(".pfd-unit").forEach(function (g) {
      g.classList.toggle("is-active", g.getAttribute("data-unit") === unitId);
    });
    state.activeUnit = unitId;

    $("pfd-panel-title").textContent = unit.id + " · " + unit.name;
    $("pfd-panel-desc").textContent = unit.description || "";

    var duties = (scn().energy.duties || []).filter(function (d) { return d.unit === unitId; });
    var dutyText = duties.length
      ? duties.map(function (d) { return fmt(Math.abs(d.duty_kw), 0) + " kW " + d.kind; }).join(", ")
      : "no significant duty in this model";

    var out = unitOutletStream(unitId);
    $("pfd-duty").textContent = dutyText;
    $("pfd-outflow").textContent = out ? fmt(out.flow_kg_h, 0) + " kg/h (" + fmt(out.flow_kmol_h, 0) + " kmol/h)" : "–";
    if (out && out.composition_molpct) {
      $("pfd-outcomp").textContent = SPECIES.map(function (sp, i) {
        var v = out.composition_molpct[sp];
        return (v !== undefined && v !== null && v >= 0.05) ? SPECIES_LABELS[i] + " " + fmt(v, 1) : null;
      }).filter(Boolean).join(" · ");
    } else {
      $("pfd-outcomp").textContent = "–";
    }
    $("pfd-facts").hidden = false;
  }

  function wirePfd() {
    document.querySelectorAll(".pfd-unit").forEach(function (g) {
      var id = g.getAttribute("data-unit");
      g.addEventListener("click", function () { renderUnitPanel(id); });
      g.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          renderUnitPanel(id);
        }
      });
    });
  }

  // ---------- mass balance ----------
  function renderStreams() {
    var s = scn();
    var tbody = $("stream-tbody");
    tbody.innerHTML = "";
    (s.streams || []).forEach(function (st) {
      var tr = document.createElement("tr");
      if ((st.id || "").indexOf("BP") === 0) { tr.className = "row-byproduct"; }
      var cells = [st.name, fmt(st.flow_kmol_h, 0), fmt(st.flow_kg_h, 0)];
      SPECIES.forEach(function (sp) {
        var c = st.composition_molpct || {};
        cells.push(c[sp] === undefined || c[sp] === null ? "–" : fmt(c[sp], 1));
      });
      cells.forEach(function (text, i) {
        var td = document.createElement(i === 0 ? "th" : "td");
        if (i === 0) { td.setAttribute("scope", "row"); }
        td.textContent = text;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });

    var mb = s.mass_balance;
    var summary = $("balance-summary");
    summary.innerHTML = "";
    [
      "Mass in (feed + steam): <strong>" + fmt(mb.in_kg_h, 0) + " kg/h</strong>",
      "Mass out (product + by-products): <strong>" + fmt(mb.out_kg_h, 0) + " kg/h</strong>",
      "Closure: <strong>" + fmt(mb.closure_pct, 2) + "%</strong>"
    ].forEach(function (html) {
      var chip = document.createElement("span");
      chip.className = "balance-chip";
      chip.innerHTML = html;
      summary.appendChild(chip);
    });
  }

  // ---------- charts ----------
  function baseOptions(yTitle, y1Title) {
    var opts = {
      responsive: true,
      maintainAspectRatio: false,
      animation: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 300 },
      plugins: {
        legend: { labels: { color: COLORS.text2, boxWidth: 14, usePointStyle: true } },
        tooltip: {
          backgroundColor: "#0c2a26", borderColor: "rgba(217,255,139,0.3)", borderWidth: 1,
          titleColor: COLORS.text, bodyColor: COLORS.text2
        }
      },
      scales: {
        x: { ticks: { color: COLORS.text2, maxRotation: 0 }, grid: { color: COLORS.grid } },
        y: { ticks: { color: COLORS.text2 }, grid: { color: COLORS.grid },
             title: { display: !!yTitle, text: yTitle || "", color: COLORS.text2 } }
      }
    };
    if (y1Title) {
      opts.scales.y1 = {
        position: "right", ticks: { color: COLORS.text2 }, grid: { drawOnChartArea: false },
        title: { display: true, text: y1Title, color: COLORS.text2 }
      };
    }
    return opts;
  }
  function destroy(name) { if (charts[name]) { charts[name].destroy(); charts[name] = null; } }

  function renderCompChart() {
    var s = scn();
    var feed = s.feed.composition_molpct || {};
    var product = null;
    (s.streams || []).forEach(function (st) { if (st.after_unit === "U6") { product = st.composition_molpct || {}; } });
    destroy("comp");
    charts.comp = new Chart($("chart-comp"), {
      type: "bar",
      data: {
        labels: SPECIES_LABELS,
        datasets: [
          { label: "Feed (mol%)", data: SPECIES.map(function (sp) { return feed[sp]; }), backgroundColor: "rgba(127,214,194,0.7)" },
          { label: "Product (mol%)", data: SPECIES.map(function (sp) { return product ? product[sp] : null; }), backgroundColor: COLORS.lime }
        ]
      },
      options: baseOptions("mol%")
    });
  }

  function renderEnergyChart() {
    var s = scn();
    var duties = s.energy.duties || [];
    destroy("energy");
    charts.energy = new Chart($("chart-energy"), {
      type: "bar",
      data: {
        labels: duties.map(function (d) { return d.label; }),
        datasets: [{
          label: "Duty (kW, cooling negative)",
          data: duties.map(function (d) { return d.kind === "cooling" ? -Math.abs(d.duty_kw) : Math.abs(d.duty_kw); }),
          backgroundColor: duties.map(function (d) {
            return d.kind === "cooling" ? "rgba(127,214,194,0.75)" : d.kind === "electrical" ? "rgba(245,200,120,0.8)" : "rgba(217,255,139,0.85)";
          })
        }]
      },
      options: (function () {
        var o = baseOptions("kW");
        o.indexAxis = "y";
        o.plugins.legend.display = false;
        return o;
      })()
    });
  }

  function renderSensitivity() {
    var sens = state.data.sensitivity;
    destroy("sconv");
    charts.sconv = new Chart($("chart-sens-conv"), {
      data: {
        labels: sens.co_conversion.map(function (p) { return p.x; }),
        datasets: [
          { type: "line", label: "CH₄ purity, dry (%)", data: sens.co_conversion.map(function (p) { return p.ch4_purity_dry_pct; }), borderColor: COLORS.lime, backgroundColor: COLORS.lime, pointRadius: 0, borderWidth: 2, tension: 0.2 },
          { type: "line", label: "CO in product (mol%)", data: sens.co_conversion.map(function (p) { return p.co_in_product_molpct; }), borderColor: COLORS.red, backgroundColor: COLORS.red, pointRadius: 0, borderWidth: 2, tension: 0.2, yAxisID: "y1" }
        ]
      },
      options: (function () {
        var o = baseOptions("CH₄ purity (%)", "CO in product (mol%)");
        o.scales.x.title = { display: true, text: "CO conversion (%)", color: COLORS.text2 };
        return o;
      })()
    });

    destroy("sco2");
    charts.sco2 = new Chart($("chart-sens-co2"), {
      data: {
        labels: sens.co2_removal.map(function (p) { return p.x; }),
        datasets: [
          { type: "line", label: "CH₄ purity, dry (%)", data: sens.co2_removal.map(function (p) { return p.ch4_purity_dry_pct; }), borderColor: COLORS.lime, backgroundColor: COLORS.lime, pointRadius: 0, borderWidth: 2, tension: 0.2 },
          { type: "line", label: "SNG production (kg/h)", data: sens.co2_removal.map(function (p) { return p.sng_kg_h; }), borderColor: COLORS.teal, backgroundColor: COLORS.teal, pointRadius: 0, borderWidth: 2, tension: 0.2, yAxisID: "y1" }
        ]
      },
      options: (function () {
        var o = baseOptions("CH₄ purity (%)", "SNG (kg/h)");
        o.scales.x.title = { display: true, text: "CO₂ removed upstream (%)", color: COLORS.text2 };
        return o;
      })()
    });
  }

  function renderAssumptions() {
    var list = $("assumptions-list");
    list.innerHTML = "";
    (state.data.meta.assumptions || []).forEach(function (text) {
      var li = document.createElement("li");
      li.textContent = text;
      list.appendChild(li);
    });
  }

  function renderAll() {
    renderKpis();
    renderStreams();
    renderCompChart();
    renderEnergyChart();
    if (state.activeUnit) { renderUnitPanel(state.activeUnit); }
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

  fetch("data/sng_data.json")
    .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
    .then(function (json) {
      if (!json || !json.scenarios || !json.scenarios.base) { throw new Error("Unexpected data format"); }
      state.data = json;
      wirePfd();
      $("scenario-select").addEventListener("change", function (event) {
        state.scenario = event.target.value;
        renderAll();
      });
      renderAll();
      renderSensitivity();
      renderAssumptions();
    })
    .catch(function (err) {
      if (window.location.protocol !== "file:") {
        showError("The dataset could not be loaded (" + err.message + "). Please try reloading the page.");
      } else {
        showError(null);
      }
    });
})();

/* KL Mobility Lab dashboard.
   Observed data comes precomputed in data/mobility_data.json (each block
   carries its source). The simulator is a transparent what-if model whose
   outputs are always labelled as modelled. */
(function () {
  "use strict";

  var COLORS = {
    lime: "#D9FF8B", text: "#F3F5EF", text2: "#B5C6BF",
    teal: "#7FD6C2", amber: "#F5C878", red: "#F08A6C",
    green: "#28634D", grid: "rgba(243, 245, 239, 0.08)"
  };
  var charts = {};
  var data = null;

  function $(id) { return document.getElementById(id); }
  function fmt(v, dp, suffix) {
    if (v === null || v === undefined || !isFinite(v)) { return "–"; }
    var n = Number(v).toLocaleString("en-GB", { minimumFractionDigits: dp, maximumFractionDigits: dp });
    return suffix ? n + suffix : n;
  }
  function compact(v) {
    if (v === null || !isFinite(v)) { return "–"; }
    var abs = Math.abs(v);
    if (abs >= 1e9) { return (v / 1e9).toFixed(2) + " bn"; }
    if (abs >= 1e6) { return (v / 1e6).toFixed(2) + " m"; }
    if (abs >= 1e3) { return (v / 1e3).toFixed(1) + " k"; }
    return String(Math.round(v));
  }

  function baseOptions(yTitle, y1Title) {
    var opts = {
      responsive: true, maintainAspectRatio: false,
      animation: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 300 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: COLORS.text2, boxWidth: 14, usePointStyle: true } },
        tooltip: { backgroundColor: "#0c2a26", borderColor: "rgba(217,255,139,0.3)", borderWidth: 1, titleColor: COLORS.text, bodyColor: COLORS.text2 }
      },
      scales: {
        x: { ticks: { color: COLORS.text2, maxRotation: 0, maxTicksLimit: 12 }, grid: { color: COLORS.grid } },
        y: { ticks: { color: COLORS.text2, callback: function (v) { return compact(v); } }, grid: { color: COLORS.grid },
             title: { display: !!yTitle, text: yTitle || "", color: COLORS.text2 } }
      }
    };
    if (y1Title) {
      opts.scales.y1 = { position: "right", ticks: { color: COLORS.text2, callback: function (v) { return compact(v); } },
        grid: { drawOnChartArea: false }, title: { display: true, text: y1Title, color: COLORS.text2 } };
    }
    return opts;
  }
  function line(label, values, color, extra) {
    return Object.assign({ type: "line", label: label, data: values, borderColor: color, backgroundColor: color,
      borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25, spanGaps: true }, extra || {});
  }
  function bars(label, values, color, extra) {
    return Object.assign({ type: "bar", label: label, data: values, backgroundColor: color, maxBarThickness: 22 }, extra || {});
  }

  // ---------- findings ----------
  function renderFindings() {
    var c = data.citations || {};
    var grid = $("finding-grid");
    grid.innerHTML = "";
    var cards = [];
    var tt = c.tomtom && c.tomtom.figures;
    if (tt) {
      cards.push({ value: fmt(tt.avg_congestion_level_pct, 1, "%"), label: "average congestion level in KL, 2025", src: c.tomtom.attribution_required || c.tomtom.source });
      cards.push({ value: fmt(tt.hours_lost_in_rush_hour_per_year, 0) + " h", label: "lost to rush hour per driver per year", src: "TomTom Traffic Index 2025" });
    }
    var mg = c.migration && c.migration.figures;
    if (mg) {
      cards.push({ value: fmt(mg.selangor_in_migrants_thousand, 1) + "k", label: "people moved into Selangor in 2024, the top destination state", src: "DOSM Migration Survey 2024" });
      cards.push({ value: fmt(mg.career_reason_share_pct, 1, "%"), label: "of moves were for career reasons; most were family-related", src: "DOSM Migration Survey 2024" });
    }
    var wb = c.worldbank_2015 && c.worldbank_2015.figures;
    if (wb) {
      cards.push({ value: fmt(wb.kl_public_transport_commuter_share_pct, 0, "%"), label: "of KL commuters used public transport in 2015 (Singapore: 62%)", src: "World Bank Malaysia Economic Monitor 2015, CC BY 3.0 IGO" });
    }
    if (data.od && data.od.total_avg_daily_trips) {
      cards.push({ value: compact(data.od.total_avg_daily_trips), label: "rail trips on an average day in 2026", src: data.od.source });
    }
    cards.forEach(function (card) {
      var el = document.createElement("div");
      el.className = "finding-card";
      el.innerHTML = '<span class="finding-value">' + card.value + '</span>' +
        '<span class="finding-label">' + card.label + '</span>' +
        '<span class="finding-src">' + card.src + '</span>';
      grid.appendChild(el);
    });
  }

  // ---------- observed charts ----------
  function renderCharts() {
    var r = data.ridership;
    charts.ridership = new Chart($("chart-ridership"), {
      data: {
        labels: r.monthly.map(function (x) { return x.m; }),
        datasets: [
          line("Rail (trips/month)", r.monthly.map(function (x) { return x.rail; }), COLORS.lime),
          line("Bus (trips/month)", r.monthly.map(function (x) { return x.bus; }), COLORS.teal),
          line("KTMB (trips/month)", r.monthly.map(function (x) { return x.ktmb; }), COLORS.amber)
        ]
      },
      options: baseOptions("trips per month")
    });

    charts.weekday = new Chart($("chart-weekday"), {
      data: {
        labels: r.weekday_profile_2026.map(function (x) { return x.dow; }),
        datasets: [bars("Average daily rail trips", r.weekday_profile_2026.map(function (x) { return x.rail_avg; }), COLORS.lime)]
      },
      options: (function () { var o = baseOptions("trips per day"); o.plugins.legend.display = false; return o; })()
    });

    var od = data.od;
    charts.od = new Chart($("chart-od"), {
      data: {
        labels: od.top_pairs.slice(0, 12).map(function (p) { return p.o + " → " + p.d; }),
        datasets: [bars("Average daily trips", od.top_pairs.slice(0, 12).map(function (p) { return p.avg_daily; }), "rgba(127,214,194,0.8)")]
      },
      options: (function () {
        var o = baseOptions("trips per day");
        o.indexAxis = "y";
        o.plugins.legend.display = false;
        o.scales.x.ticks.callback = function (v) { return compact(v); };
        return o;
      })()
    });

    var reg = data.registrations;
    charts.reg = new Chart($("chart-reg"), {
      data: {
        labels: reg.monthly.map(function (x) { return x.m; }),
        datasets: [
          bars("Selangor", reg.monthly.map(function (x) { return x.selangor; }), "rgba(217,255,139,0.85)", { stack: "s" }),
          bars("Kuala Lumpur", reg.monthly.map(function (x) { return x.kl; }), "rgba(127,214,194,0.8)", { stack: "s" }),
          bars("Other states", reg.monthly.map(function (x) { return x.other; }), "rgba(181,198,191,0.6)", { stack: "s" }),
          bars("Partner channel (no geography)", reg.monthly.map(function (x) { return x.rakan_niaga; }), "rgba(245,200,120,0.6)", { stack: "s" })
        ]
      },
      options: (function () { var o = baseOptions("registrations per month"); o.scales.x.stacked = true; o.scales.y.stacked = true; return o; })()
    });

    var pop = data.population, emp = data.employment;
    charts.popemp = new Chart($("chart-popemp"), {
      data: {
        labels: pop.annual.map(function (x) { return String(x.y); }),
        datasets: [
          line("Selangor population (k)", pop.annual.map(function (x) { return x.selangor_k; }), COLORS.lime),
          line("KL population (k)", pop.annual.map(function (x) { return x.kl_k; }), COLORS.teal),
          line("Selangor employed (k)", pop.annual.map(function (x) {
            var match = emp.quarterly.filter(function (q) { return q.q.indexOf(String(x.y)) === 0; });
            return match.length ? match[match.length - 1].selangor_k : null;
          }), COLORS.amber, { borderDash: [6, 4], yAxisID: "y1" }),
          line("KL employed (k)", pop.annual.map(function (x) {
            var match = emp.quarterly.filter(function (q) { return q.q.indexOf(String(x.y)) === 0; });
            return match.length ? match[match.length - 1].kl_k : null;
          }), COLORS.red, { borderDash: [6, 4], yAxisID: "y1" })
        ]
      },
      options: baseOptions("population (thousands)", "employed (thousands)")
    });
  }

  // ---------- stops map ----------
  function renderMap(stops) {
    var box = $("stops-map");
    if (!stops || !stops.length) { box.textContent = "Station data unavailable."; return; }
    var lats = stops.map(function (s) { return s.lat; });
    var lons = stops.map(function (s) { return s.lon; });
    var minLat = Math.min.apply(null, lats), maxLat = Math.max.apply(null, lats);
    var minLon = Math.min.apply(null, lons), maxLon = Math.max.apply(null, lons);
    var pad = 0.03;
    minLat -= pad; maxLat += pad; minLon -= pad; maxLon += pad;
    var W = 600, H = 320;
    var svgNS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    stops.forEach(function (s) {
      var x = (s.lon - minLon) / (maxLon - minLon) * W;
      var y = H - (s.lat - minLat) / (maxLat - minLat) * H;
      var dot = document.createElementNS(svgNS, "circle");
      dot.setAttribute("cx", x.toFixed(1));
      dot.setAttribute("cy", y.toFixed(1));
      dot.setAttribute("r", "3");
      dot.setAttribute("class", "map-dot");
      var title = document.createElementNS(svgNS, "title");
      title.textContent = s.name;
      dot.appendChild(title);
      svg.appendChild(dot);
    });
    box.appendChild(svg);
  }

  // ---------- sources ----------
  function renderSources() {
    var list = $("sources-list");
    list.innerHTML = "";
    (data.meta.licences || []).forEach(function (item) {
      var li = document.createElement("li");
      li.textContent = item.source + " - " + item.licence + (item.attribution ? " - " + item.attribution : "");
      list.appendChild(li);
    });
    (data.meta.gaps || []).forEach(function (gap) {
      var li = document.createElement("li");
      li.textContent = "Data gap: " + gap;
      list.appendChild(li);
    });
  }

  // ---------- simulator ----------
  var SLIDERS = {
    commuters: { input: "in-commuters", out: "out-commuters", fmt: function (v) { return compact(v) + " people"; } },
    share: { input: "in-share", out: "out-share", fmt: function (v) { return v + "%"; } },
    basekm: { input: "in-basekm", out: "out-basekm", fmt: function (v) { return v + " km"; } },
    newkm: { input: "in-newkm", out: "out-newkm", fmt: function (v) { return v + " km"; } },
    days: { input: "in-days", out: "out-days", fmt: function (v) { return v + " days"; } },
    remote: { input: "in-remote", out: "out-remote", fmt: function (v) { return v + " days"; } },
    pt: { input: "in-pt", out: "out-pt", fmt: function (v) { return v + "%"; } },
    occ: { input: "in-occ", out: "out-occ", fmt: function (v) { return v + " people/car"; } },
    fuel: { input: "in-fuel", out: "out-fuel", fmt: function (v) { return v + " L/100 km"; } },
    ef: { input: "in-ef", out: "out-ef", fmt: function (v) { return v + " kg/L"; } }
  };

  var PRESETS = {
    A: { desc: "Today's pattern: nothing changes. The reference point every other scenario is compared against.",
         values: { share: 0, newkm: 25, remote: 0, pt: 0 } },
    B: { desc: "More localised employment: a fifth of these commuters find work much closer to home (25 km becomes 10 km one way). Jobs move; people do not.",
         values: { share: 20, newkm: 10, remote: 0, pt: 0 } },
    C: { desc: "Transit shift: a fifth of these commuters switch fully to public transport. Assumes the capacity exists to carry them.",
         values: { share: 20, newkm: 25, remote: 0, pt: 100 } },
    D: { desc: "Hybrid work: a fifth of these commuters work from home two days a week. Non-work travel on those days is not modelled.",
         values: { share: 20, newkm: 25, remote: 2, pt: 0 } },
    E: { desc: "Combined strategy: a fifth of commuters get all three changes at once - closer work (15 km), one remote day, and a quarter switching to transit.",
         values: { share: 20, newkm: 15, remote: 1, pt: 25 } }
  };

  function sliderValue(key) { return parseFloat($(SLIDERS[key].input).value); }

  function runSimulator() {
    Object.keys(SLIDERS).forEach(function (key) {
      $(SLIDERS[key].out).textContent = SLIDERS[key].fmt(sliderValue(key));
    });

    var N = sliderValue("commuters");
    var A = N * sliderValue("share") / 100;
    var baseKm = sliderValue("basekm");
    var newKm = Math.min(sliderValue("newkm"), baseKm);
    var days = sliderValue("days");
    var remote = Math.min(sliderValue("remote"), days);
    var ptShare = sliderValue("pt") / 100;
    var occ = sliderValue("occ");
    var WEEKS = 46; // working weeks per year, allowing for leave and holidays

    // Baseline for the affected group: car trips at today's distance.
    var trips0 = A * 2 * days / occ;
    var vkt0 = trips0 * baseKm;
    // After the change: fewer commute days, fewer car users, shorter distance.
    var trips1 = A * (1 - ptShare) * 2 * (days - remote) / occ;
    var vkt1 = trips1 * newKm;

    var tripsAvoided = trips0 - trips1;
    var vktYear = (vkt0 - vkt1) * WEEKS;
    var fuelYear = vktYear * sliderValue("fuel") / 100;
    var co2Year = fuelYear * sliderValue("ef") / 1000; // tonnes

    $("sim-trips").textContent = compact(tripsAvoided);
    $("sim-vkt").textContent = compact(vktYear);
    $("sim-fuel").textContent = compact(fuelYear);
    $("sim-co2").textContent = compact(co2Year);
    $("sim-uncertainty").textContent = co2Year > 0
      ? "With ±30% on the assumptions, the CO₂ range is roughly " + compact(co2Year * 0.7) + " to " + compact(co2Year * 1.3) + " tonnes per year."
      : "Adjust the sliders or pick a scenario to model a change.";
  }

  function applyPreset(key) {
    var preset = PRESETS[key];
    if (!preset) { return; }
    document.querySelectorAll(".sim-presets .preset-btn").forEach(function (b) {
      b.classList.toggle("is-active", b.getAttribute("data-preset") === key);
    });
    $("sim-preset-desc").textContent = preset.desc;
    Object.keys(preset.values).forEach(function (k) {
      $(SLIDERS[k].input).value = preset.values[k];
    });
    runSimulator();
  }

  function wireSimulator() {
    var d = data.simulator_defaults || {};
    $(SLIDERS.commuters.input).value = d.car_commuters || 1500000;
    $(SLIDERS.basekm.input).value = d.one_way_km || 25;
    $(SLIDERS.newkm.input).value = d.one_way_km || 25;
    $(SLIDERS.days.input).value = d.workdays_per_week || 5;
    $(SLIDERS.occ.input).value = d.car_occupancy || 1.2;
    $(SLIDERS.fuel.input).value = d.fuel_l_per_100km || 7.5;
    $(SLIDERS.ef.input).value = d.co2_kg_per_l || 2.31;
    $(SLIDERS.share.input).value = 0;
    $(SLIDERS.remote.input).value = 0;
    $(SLIDERS.pt.input).value = 0;

    Object.keys(SLIDERS).forEach(function (key) {
      $(SLIDERS[key].input).addEventListener("input", function () {
        document.querySelectorAll(".sim-presets .preset-btn").forEach(function (b) { b.classList.remove("is-active"); });
        $("sim-preset-desc").textContent = "Custom scenario: your own assumptions.";
        runSimulator();
      });
    });
    document.querySelectorAll(".sim-presets .preset-btn").forEach(function (btn) {
      btn.addEventListener("click", function () { applyPreset(btn.getAttribute("data-preset")); });
    });
    applyPreset("A");
  }

  function renderSrcTags() {
    document.querySelectorAll(".src-tag[data-src]").forEach(function (el) {
      var block = data[el.getAttribute("data-src")];
      if (block && block.source) { el.textContent = block.source; }
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

  Promise.all([
    fetch("data/mobility_data.json").then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); }),
    fetch("data/stops.json").then(function (r) { return r.ok ? r.json() : null; })
  ]).then(function (results) {
    data = results[0];
    if (!data || !data.ridership || !data.od) { throw new Error("Unexpected data format"); }
    renderFindings();
    renderCharts();
    renderMap(results[1]);
    renderSources();
    renderSrcTags();
    wireSimulator();
  }).catch(function (err) {
    if (window.location.protocol !== "file:") {
      showError("The dataset could not be loaded (" + err.message + "). Please try reloading the page.");
    } else {
      showError(null);
    }
  });
})();

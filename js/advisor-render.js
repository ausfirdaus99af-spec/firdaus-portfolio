/* Shared advisor renderer.
   Reads data/advisor_findings.json relative to the page and draws finding cards.
   All analysis happens in each project's Python rule engine; this file only displays. */
(function () {
  "use strict";

  var STATUS_LABELS = {
    action_recommended: "Action recommended",
    conditional: "Needs a trial or more data first",
    no_action_justified: "Checked, no action needed",
    informational: "For awareness"
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function fmt(v) {
    if (v === null || v === undefined || !isFinite(v)) { return "–"; }
    return Number(v).toLocaleString("en-GB", { maximumFractionDigits: 2 });
  }

  function block(label, parent) {
    var wrap = el("div", "adv-block");
    wrap.appendChild(el("h4", "adv-block-label", label));
    parent.appendChild(wrap);
    return wrap;
  }

  function renderFinding(f) {
    var card = el("article", "adv-card adv-" + (f.status || "informational"));

    var head = el("header", "adv-head");
    var chips = el("div", "adv-chips");
    chips.appendChild(el("span", "adv-chip adv-chip-status", STATUS_LABELS[f.status] || f.status));
    if (f.severity) { chips.appendChild(el("span", "adv-chip adv-chip-" + f.severity, f.severity + " severity")); }
    head.appendChild(chips);
    head.appendChild(el("h3", "adv-title", f.id + " · " + f.title));
    card.appendChild(head);

    if (f.problem) { block("What we looked at", card).appendChild(el("p", null, f.problem)); }

    if (f.evidence) {
      var evid = block("Evidence", card);
      if (f.evidence.summary) { evid.appendChild(el("p", null, f.evidence.summary)); }
      if (f.evidence.details && f.evidence.details.length) {
        var more = el("details", "adv-more");
        more.appendChild(el("summary", null, "Full evidence (" + f.evidence.details.length + " items)"));
        var ul = el("ul", "adv-list");
        f.evidence.details.forEach(function (d) { ul.appendChild(el("li", null, d)); });
        more.appendChild(ul);
        evid.appendChild(more);
      }
    }

    if (f.possible_causes && f.possible_causes.length) {
      var causes = block("Possible cause", card);
      var cl = el("ul", "adv-list");
      f.possible_causes.forEach(function (c) {
        var li = el("li", null, c.cause + " ");
        li.appendChild(el("span", "adv-basis adv-basis-" + c.basis, c.basis === "observed" ? "seen in the data" : "hypothesis, needs measurement"));
        cl.appendChild(li);
      });
      causes.appendChild(cl);
    }

    if (f.recommendation) { block("Recommended action", card).appendChild(el("p", null, f.recommendation)); }

    if (f.expected_impact) {
      var imp = block("Expected impact", card);
      if (f.expected_impact.summary) { imp.appendChild(el("p", null, f.expected_impact.summary)); }
      var impMore = el("details", "adv-more");
      impMore.appendChild(el("summary", null, "Calculations, assumptions and sensitivity"));
      var inner = el("div", null);
      (f.expected_impact.calculations || []).forEach(function (c) {
        inner.appendChild(el("p", "adv-calc", c.label + ": " + fmt(c.value) + " " + (c.unit || "")));
      });
      var s = f.expected_impact.sensitivity;
      if (s) { inner.appendChild(el("p", "adv-calc", "Sensitivity: " + fmt(s.low) + " to " + fmt(s.high) + " " + (s.unit || "") + " (" + (s.description || "") + ")")); }
      if (f.expected_impact.assumptions && f.expected_impact.assumptions.length) {
        var al = el("ul", "adv-list");
        f.expected_impact.assumptions.forEach(function (a) { al.appendChild(el("li", null, "Assumption: " + a)); });
        inner.appendChild(al);
      }
      impMore.appendChild(inner);
      imp.appendChild(impMore);
    }

    if (f.tradeoffs) { block("Trade-offs", card).appendChild(el("p", null, f.tradeoffs)); }

    if (f.quality_gate) {
      var gate = block("Quality gate", card);
      var gp = el("p", "adv-gate adv-gate-" + f.quality_gate.outcome,
        (f.quality_gate.outcome === "passes" ? "Passes: " : f.quality_gate.outcome === "fails" ? "Fails: " : "Conditional: ") + f.quality_gate.check);
      gate.appendChild(gp);
      if (f.quality_gate.note) { gate.appendChild(el("p", "adv-gate-note", f.quality_gate.note)); }
    }

    if (f.validation_required && f.validation_required.length) {
      var val = block("Check before acting", card);
      var vl = el("ul", "adv-list");
      f.validation_required.forEach(function (v) { vl.appendChild(el("li", null, v)); });
      val.appendChild(vl);
    }

    return card;
  }

  fetch("data/advisor_findings.json")
    .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
    .then(function (json) {
      var list = document.getElementById("advisor-list");
      if (!list) { return; }
      list.innerHTML = "";
      (json.findings || []).forEach(function (f) { list.appendChild(renderFinding(f)); });
      if (!list.children.length) {
        list.appendChild(el("p", "chart-note", "No findings were produced for this dataset."));
      }
    })
    .catch(function () {
      var loading = document.getElementById("advisor-loading");
      if (loading) { loading.textContent = "Findings could not be loaded. Serve the site over HTTP and rebuild the project data."; }
    });
})();

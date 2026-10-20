// Admin panel enhancements. Everything works without JS; this only adds comfort.
(function () {
  "use strict";
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];

  // Confirm dialog for destructive forms: <form data-confirm="Сигурни ли сте?">
  const dialog = $("#confirmDialog");
  let pendingForm = null;
  document.addEventListener("submit", (e) => {
    const form = e.target;
    const text = form.dataset.confirm || (e.submitter && e.submitter.dataset.confirm);
    if (!text || form.dataset.confirmed) return;
    e.preventDefault();
    if (!dialog || typeof dialog.showModal !== "function") {
      if (window.confirm(text)) { form.dataset.confirmed = "1"; form.requestSubmit(e.submitter); }
      return;
    }
    pendingForm = { form, submitter: e.submitter };
    $("#confirmText", dialog).textContent = text;
    dialog.showModal();
  });
  if (dialog) {
    $("#confirmYes", dialog).addEventListener("click", () => {
      dialog.close();
      if (pendingForm) {
        pendingForm.form.dataset.confirmed = "1";
        pendingForm.form.requestSubmit(pendingForm.submitter);
      }
    });
    $("#confirmNo", dialog).addEventListener("click", () => { pendingForm = null; dialog.close(); });
  }

  // Auto-submit filter selects: <select data-autosubmit>
  $$("[data-autosubmit]").forEach((el) => el.addEventListener("change", () => el.form.submit()));

  // Bulk selection on list pages
  const all = $("[data-select-all]");
  if (all) {
    all.addEventListener("change", () => $$("[data-select-row]").forEach((cb) => (cb.checked = all.checked)));
  }

  // Variant formset: add rows from the empty-form template, mark rows deleted
  const formset = $("[data-formset]");
  if (formset) {
    const prefix = formset.dataset.formset;
    const total = $(`#id_${prefix}-TOTAL_FORMS`);
    const tpl = $("#variantTemplate");
    const body = $("tbody", formset);
    $("[data-add-row]")?.addEventListener("click", () => {
      const index = Number(total.value);
      const html = tpl.innerHTML.replace(/__prefix__/g, index);
      body.insertAdjacentHTML("beforeend", html);
      total.value = index + 1;
      body.lastElementChild.querySelector("input")?.focus();
    });
    formset.addEventListener("change", (e) => {
      if (e.target.name && e.target.name.endsWith("-DELETE")) {
        e.target.closest("tr").classList.toggle("deleted", e.target.checked);
      }
    });
  }

  // Live margin hint on the product form
  const hint = $("[data-margin-hint]");
  if (hint) {
    const price = $("[data-margin=price]");
    const cost = $("[data-margin=cost_price]");
    const update = () => {
      const p = parseFloat((price.value || "").replace(",", "."));
      const c = parseFloat((cost.value || "").replace(",", "."));
      if (!p || isNaN(c)) { hint.textContent = "Въведете цена и доставна цена, за да видите печалбата."; hint.classList.remove("bad"); return; }
      const m = p - c;
      hint.textContent = `Печалба на брой: ${m.toFixed(2).replace(".", ",")} · марж ${((m / p) * 100).toFixed(1).replace(".", ",")}%`;
      hint.classList.toggle("bad", m <= 0);
    };
    [price, cost].forEach((el) => el && el.addEventListener("input", update));
    update();
  }

  // Chart tooltip: <g class="col" data-tip-date data-tip-value>
  $$(".d-chart-wrap").forEach((wrap) => {
    const tip = $(".d-tip", wrap);
    const svg = $("svg", wrap);
    const show = (g) => {
      const box = svg.getBoundingClientRect();
      const scale = box.width / svg.viewBox.baseVal.width;
      tip.innerHTML = `<b>${g.dataset.tipValue}</b>${g.dataset.tipDate}`;
      tip.style.left = Number(g.dataset.cx) * scale + "px";
      tip.style.top = Number(g.dataset.cy) * scale + "px";
      tip.classList.add("on");
    };
    $$("g.col", wrap).forEach((g) => {
      g.addEventListener("mouseenter", () => show(g));
      g.addEventListener("focus", () => show(g));
      g.addEventListener("mouseleave", () => tip.classList.remove("on"));
      g.addEventListener("blur", () => tip.classList.remove("on"));
    });
  });
})();

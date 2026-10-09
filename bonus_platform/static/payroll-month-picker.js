(() => {
  "use strict";
  const pickers = new Map();
  const currentMonth = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit" }).format(new Date());
  let calendarMonth = currentMonth();
  document.querySelectorAll("[data-payroll-month]").forEach((input) => {
    const wrapper = document.createElement("div"); wrapper.className = "payroll-month-control";
    input.before(wrapper); wrapper.append(input);
    input.classList.add("payroll-month-native"); input.tabIndex = -1; input.setAttribute("aria-hidden", "true");
    const label = input.closest(".payroll-month-field").querySelector("label"); label.removeAttribute("for"); label.id = `${input.id}Label`;
    const panel = document.createElement("div"); panel.id = `${input.id}Panel`; panel.className = "payroll-month-panel";
    panel.setAttribute("role", "group"); panel.setAttribute("aria-labelledby", label.id);
    panel.innerHTML = '<div class="payroll-month-year"><button type="button" data-year="-1" aria-label="上一年">‹</button><strong aria-live="polite"></strong><button type="button" data-year="1" aria-label="下一年">›</button></div><div class="payroll-month-grid" role="group" aria-label="月份"></div>';
    wrapper.append(panel);
    const note = document.createElement("p"); note.className = "payroll-month-note";
    note.id = `${input.id}Note`; note.setAttribute("aria-live", "polite");
    panel.setAttribute("aria-describedby", note.id); panel.append(note);
    let year = Number((input.value || input.max).slice(0, 4)), lastValue = input.value;
    function render() {
      if (input.value !== lastValue) { year = Number((input.value || input.max).slice(0, 4)); lastValue = input.value; }
      panel.setAttribute("aria-disabled", String(input.disabled));
      panel.querySelector(".payroll-month-year strong").textContent = `${year} 年`;
      panel.querySelector('[data-year="-1"]').disabled = input.disabled || year <= Number(input.min.slice(0, 4));
      panel.querySelector('[data-year="1"]').disabled = input.disabled || year >= Number(input.max.slice(0, 4));
      panel.querySelector(".payroll-month-grid").innerHTML = Array.from({ length: 12 }, (_, i) => {
        const month = `${year}-${String(i + 1).padStart(2, "0")}`, disabled = input.disabled || month < input.min || month > input.max;
        const future = month > calendarMonth, current = month === calendarMonth;
        const state = future ? "未到核算月" : current ? "当月未结束" : "历史月";
        return `<button type="button" data-month="${month}" data-period="${future ? "future" : current ? "current" : "past"}" aria-label="${year}年${i + 1}月，${state}" aria-pressed="${month === input.value}" ${disabled ? "disabled" : ""}><span>${i + 1} 月</span><small>${state}</small></button>`;
      }).join("");
      const futureSelected = input.value > calendarMonth;
      note.dataset.future = String(futureSelected);
      note.textContent = futureSelected ? "所选月份尚未到达，可提前选择；核算时若北森尚未生成月报，将提示暂无数据。" : input.value === calendarMonth ? "当月尚未结束，考勤月报可能不完整。" : "默认选择上个月，核算以该月已生成的考勤月报为准。";
    }
    panel.addEventListener("click", (event) => {
      const button = event.target.closest("button"); if (!button || button.disabled || input.disabled) return;
      if (button.dataset.year) {
        year += Number(button.dataset.year); const direction = button.dataset.year; render();
        const next = panel.querySelector(`[data-year="${direction}"]`);
        (next.disabled ? panel.querySelector('[data-month]:not(:disabled)') : next)?.focus(); return;
      }
      if (button.dataset.month) {
        input.value = button.dataset.month; input.dispatchEvent(new Event("input", { bubbles: true })); input.dispatchEvent(new Event("change", { bubbles: true })); render();
        panel.querySelector(`[data-month="${input.value}"]`)?.focus();
      }
    });
    panel.addEventListener("keydown", (event) => {
      const button = event.target.closest("[data-month]"); if (!button) return;
      const columns = getComputedStyle(panel.querySelector(".payroll-month-grid")).gridTemplateColumns.split(" ").length;
      const steps = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -columns, ArrowDown: columns };
      if (steps[event.key] !== undefined) {
        event.preventDefault(); const items = [...panel.querySelectorAll("[data-month]")]; let index = items.indexOf(button) + steps[event.key];
        while (index >= 0 && index < items.length && items[index].disabled) index += steps[event.key];
        if (items[index]) items[index].focus();
      }
    });
    input.addEventListener("input", render); input.addEventListener("change", render);
    input.addEventListener("invalid", (event) => { event.preventDefault(); panel.querySelector('[data-month]:not(:disabled)')?.focus(); });
    new MutationObserver(render).observe(input, { attributes: true, attributeFilter: ["disabled", "min", "max"] });
    pickers.set(input, { sync: render }); render();
  });
  window.PayrollMonthPicker = { sync: (input) => pickers.get(input)?.sync() };
  function refreshCalendar() {
    const next = currentMonth(); if (next === calendarMonth) return;
    calendarMonth = next; pickers.forEach((picker) => picker.sync());
  }
  window.addEventListener("focus", refreshCalendar);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshCalendar(); });
  setInterval(refreshCalendar, 60000);
})();

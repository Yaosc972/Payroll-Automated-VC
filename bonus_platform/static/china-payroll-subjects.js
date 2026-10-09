(() => {
  "use strict";
  const subjects = {
    "meal-allowance": { title: "集团技术部餐补", description: "自动读取所选月份的北森日考勤，按集团技术部餐补规则核算。", source: "北森考勤接口", hint: "符合餐补规则且末打卡达到 21:00 的考勤日，按 20 元/天计算。确认后自动读取并核算，无需上传考勤表。" },
    "wx-meal-allowance": { title: "WX 技术部餐补", description: "上传 WX 系统的日考勤，单独核算并保存本月餐补。", source: "WX 考勤 Excel", hint: "请准备所选月份的 WX 技术部日考勤，支持多个分片文件。符合规则且末打卡达到 21:00 的工作日，按 20 元/天计算。" },
    "relocation-allowance": { title: "职场搬迁补贴", description: "自动读取所选月份的北森考勤，并按职场搬迁补贴规则试算。", source: "北森考勤接口", hint: "50 元/天，上限 1,000 元/月。点击开始核算后自动读取考勤并核算，无需上传考勤表；数据异常会在结果中提示。" },
  };
  const form = document.getElementById("payrollSubjectForm"), month = document.getElementById("payrollSelectedMonth"), status = document.getElementById("payrollSelectionStatus");
  const current = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit" }).format(new Date());
  const previous = new Date(`${current}-01T00:00:00Z`); previous.setUTCMonth(previous.getUTCMonth() - 1);
  month.max = "2099-12"; month.value = previous.toISOString().slice(0, 7);
  let selected = "";
  const confirmation = document.getElementById("payrollStartConfirmation");
  let pendingStart = null;
  document.querySelectorAll("[data-subject]").forEach((button) => button.addEventListener("click", () => {
    selected = button.dataset.subject;
    const subject = subjects[selected];
    document.querySelectorAll("[data-subject]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    document.getElementById("payrollSubjectEmpty").hidden = true; form.hidden = false;
    document.getElementById("payrollSelectedTitle").textContent = subject.title;
    document.getElementById("payrollSelectedScope").hidden = selected !== "relocation-allowance";
    document.getElementById("payrollSelectedDescription").textContent = subject.description;
    document.getElementById("payrollSelectedSource").textContent = subject.source;
    document.getElementById("payrollSelectedHint").textContent = subject.hint;
    form.querySelector(".payroll-enter").innerHTML = `${selected === "wx-meal-allowance" ? "上传考勤" : "开始核算"} <span aria-hidden="true">→</span>`;
    status.textContent = "";
  }));
  let creating = false, creationRequest = null;
  async function enter(start) {
    if (creating) return;
    creating = true; const button = form.querySelector(".payroll-enter"); button.disabled = true; status.textContent = "正在创建核算活动…";
    try {
      const activity = await window.PayrollActivities.create(start);
      creationRequest = null; status.textContent = "";
      window.PayrollActivities.open(activity, start.subject !== "wx-meal-allowance");
    } catch (error) { status.textContent = error.message || "活动创建失败，请重试。"; }
    finally { creating = false; button.disabled = false; }
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!selected || !form.reportValidity()) return;
    if (creating) return;
    const payload = { subject: selected, month: month.value, name: document.getElementById("payrollActivityName").value.trim() };
    if (!creationRequest || ["subject", "month", "name"].some(key => creationRequest[key] !== payload[key])) creationRequest = { ...payload, requestId: crypto.randomUUID().replaceAll("-", "") };
    if (selected !== "wx-meal-allowance") {
      if (confirmation.open) return;
      pendingStart = { ...creationRequest };
      document.getElementById("payrollConfirmSubject").textContent = subjects[selected].title;
      document.getElementById("payrollConfirmMonth").textContent = `${month.value.slice(0, 4)} 年 ${Number(month.value.slice(5))} 月`;
      confirmation.returnValue = "";
      confirmation.showModal();
      return;
    }
    enter(creationRequest);
  });
  confirmation.addEventListener("close", () => {
    const start = pendingStart; pendingStart = null;
    if (confirmation.returnValue === "start" && start) enter(start);
  });
})();

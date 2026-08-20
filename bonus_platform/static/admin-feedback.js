(() => {
  const root = document.getElementById("feedbackCenter");
  if (!root) return;

  const feedbackList = document.getElementById("adminFeedbackList");
  const feedbackDetail = document.getElementById("adminFeedbackDetail");
  const announcementForm = document.getElementById("adminAnnouncementForm");
  const announcementContent = document.getElementById("adminAnnouncementContent");
  const announcementStatus = document.getElementById("adminAnnouncementStatus");
  const announcementList = document.getElementById("adminAnnouncementList");
  let feedbackItems = [];
  let selectedFeedbackId = new URLSearchParams(window.location.search).get("feedback") || "";

  const apiRequest = async (url, options = {}) => {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
      ...options,
    });
    if (response.status === 401) {
      window.location.href = `login.html?next=${encodeURIComponent(window.location.pathname + window.location.search + window.location.hash)}`;
      throw new Error("登录已失效。");
    }
    if (!response.ok) {
      let message = `请求失败（${response.status}）`;
      try {
        const data = await response.json();
        message = data.detail || message;
      } catch {
        // Keep the HTTP status fallback.
      }
      throw new Error(message);
    }
    return response.json();
  };

  const formatTime = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value || "刚刚";
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  };

  const emptyState = (text) => {
    const empty = document.createElement("div");
    empty.className = "admin-feedback-empty";
    empty.textContent = text;
    return empty;
  };

  const feedbackRow = (item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "admin-feedback-row";
    button.classList.toggle("active", item.id === selectedFeedbackId);
    const header = document.createElement("header");
    const name = document.createElement("strong");
    name.textContent = item.userName;
    const time = document.createElement("span");
    time.textContent = formatTime(item.createdAt);
    header.append(name, time);
    const description = document.createElement("p");
    description.textContent = item.description;
    const footer = document.createElement("footer");
    const category = document.createElement("span");
    category.textContent = item.moduleShortName || item.moduleName;
    const attachments = document.createElement("span");
    attachments.textContent = item.attachmentCount ? `${item.attachmentCount} 张截图` : item.id;
    footer.append(category, attachments);
    button.append(header, description, footer);
    button.addEventListener("click", () => showFeedbackDetail(item.id));
    return button;
  };

  const renderFeedbackList = () => {
    feedbackList.replaceChildren();
    if (!feedbackItems.length) {
      feedbackList.append(emptyState("还没有用户反馈。"));
      return;
    }
    feedbackItems.forEach((item) => feedbackList.append(feedbackRow(item)));
  };

  const detailPair = (label, value) => {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value || "—";
    wrapper.append(term, detail);
    return wrapper;
  };

  const showFeedbackDetail = async (feedbackId) => {
    selectedFeedbackId = feedbackId;
    renderFeedbackList();
    feedbackDetail.hidden = false;
    feedbackDetail.replaceChildren(emptyState("正在读取反馈详情…"));
    try {
      const data = await apiRequest(`/api/workbench/feedback/${encodeURIComponent(feedbackId)}`);
      const item = data.feedback;
      feedbackDetail.replaceChildren();
      const title = document.createElement("h4");
      title.textContent = `${item.moduleShortName || item.moduleName} · ${item.userName}`;
      const description = document.createElement("p");
      description.textContent = item.description;
      const metadata = document.createElement("dl");
      metadata.append(
        detailPair("反馈编号", item.id),
        detailPair("所属模块", item.moduleName),
        detailPair("提交时间", formatTime(item.createdAt)),
        detailPair("来源页面", item.pagePath || "平台首页"),
      );
      feedbackDetail.append(title, description, metadata);
      if (item.attachments?.length) {
        const gallery = document.createElement("div");
        gallery.className = "admin-feedback-attachments";
        item.attachments.forEach((attachment, index) => {
          const link = document.createElement("a");
          link.href = `/api/workbench/feedback/${encodeURIComponent(item.id)}/attachments/${encodeURIComponent(attachment.id)}`;
          link.target = "_blank";
          link.rel = "noopener";
          const image = document.createElement("img");
          image.src = link.href;
          image.alt = `反馈截图 ${index + 1}`;
          link.append(image);
          gallery.append(link);
        });
        feedbackDetail.append(gallery);
      }
    } catch (error) {
      feedbackDetail.replaceChildren(emptyState(error.message || "反馈详情加载失败。"));
    }
  };

  const loadFeedback = async () => {
    feedbackList.replaceChildren(emptyState("正在读取用户反馈…"));
    try {
      const data = await apiRequest("/api/admin/feedback?limit=100");
      feedbackItems = data.feedback || [];
      renderFeedbackList();
      if (selectedFeedbackId) {
        await showFeedbackDetail(selectedFeedbackId);
        root.scrollIntoView({ block: "start" });
      }
    } catch (error) {
      feedbackList.replaceChildren(emptyState(error.message || "反馈列表加载失败。"));
    }
  };

  const announcementRow = (item) => {
    const row = document.createElement("div");
    row.className = "admin-announcement-row";
    const title = document.createElement("strong");
    title.textContent = item.title;
    const meta = document.createElement("span");
    meta.textContent = `${item.kindLabel} · ${item.moduleName} · ${formatTime(item.publishedAt)}`;
    row.append(title, meta);
    return row;
  };

  const loadAnnouncements = async () => {
    announcementList.replaceChildren(emptyState("正在读取公告…"));
    try {
      const data = await apiRequest("/api/admin/announcements?limit=8");
      announcementList.replaceChildren();
      if (!data.announcements?.length) {
        announcementList.append(emptyState("还没有发布公告。"));
        return;
      }
      data.announcements.forEach((item) => announcementList.append(announcementRow(item)));
    } catch (error) {
      announcementList.replaceChildren(emptyState(error.message || "公告加载失败。"));
    }
  };

  const replaceSelection = (prefix, suffix = prefix) => {
    const start = announcementContent.selectionStart;
    const end = announcementContent.selectionEnd;
    const selected = announcementContent.value.slice(start, end) || "文字";
    announcementContent.setRangeText(`${prefix}${selected}${suffix}`, start, end, "end");
    announcementContent.focus();
  };

  const prefixSelectedLines = (prefix) => {
    const start = announcementContent.selectionStart;
    const end = announcementContent.selectionEnd;
    const selected = announcementContent.value.slice(start, end) || "内容";
    const next = selected.split(/\r?\n/).map((line) => `${prefix}${line}`).join("\n");
    announcementContent.setRangeText(next, start, end, "end");
    announcementContent.focus();
  };

  document.querySelectorAll("[data-rich-wrap]").forEach((button) => {
    button.addEventListener("click", () => replaceSelection(button.dataset.richWrap));
  });
  document.querySelectorAll("[data-rich-prefix]").forEach((button) => {
    button.addEventListener("click", () => prefixSelectedLines(button.dataset.richPrefix));
  });
  document.querySelector("[data-rich-link]")?.addEventListener("click", () => {
    const url = window.prompt("输入以 https:// 开头的链接");
    if (!url || !url.startsWith("https://")) return;
    const start = announcementContent.selectionStart;
    const end = announcementContent.selectionEnd;
    const text = announcementContent.value.slice(start, end) || "查看详情";
    announcementContent.setRangeText(`[${text}](${url})`, start, end, "end");
    announcementContent.focus();
  });

  announcementForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = announcementForm.querySelector("button[type='submit']");
    const formData = new FormData(announcementForm);
    button.disabled = true;
    button.textContent = "发布中…";
    announcementStatus.textContent = "正在保存公告并生成飞书推送…";
    announcementStatus.classList.remove("error");
    try {
      const data = await apiRequest("/api/admin/announcements", {
        method: "POST",
        body: JSON.stringify({
          kind: formData.get("kind"),
          moduleId: formData.get("moduleId"),
          title: formData.get("title"),
          content: formData.get("content"),
          pushToFeishu: formData.get("pushToFeishu") === "on",
        }),
      });
      announcementStatus.textContent = `已发布 · 飞书排队 ${data.queuedRecipients} 人`;
      announcementForm.reset();
      await loadAnnouncements();
    } catch (error) {
      announcementStatus.textContent = error.message || "公告发布失败。";
      announcementStatus.classList.add("error");
    } finally {
      button.disabled = false;
      button.textContent = "发布公告";
    }
  });

  document.getElementById("adminFeedbackRefresh")?.addEventListener("click", loadFeedback);
  loadFeedback();
  loadAnnouncements();
})();

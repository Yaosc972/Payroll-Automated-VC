(() => {
  // Shared mount contract: set <html data-module-id="...">, then include this script and feedback-widget.css.
  const widgetMarkup = `
    <div class="feedback-widget" id="feedbackWidget">
      <button
        class="feedback-launcher"
        id="feedbackLauncher"
        type="button"
        aria-controls="feedbackDrawer"
        aria-expanded="false"
      >
        <span class="feedback-launcher-icon" aria-hidden="true"></span>
        <span>反馈与更新</span>
        <i id="feedbackUnreadDot" aria-label="有新公告" hidden></i>
      </button>
      <div class="feedback-scrim" id="feedbackScrim" hidden></div>
      <aside class="feedback-drawer" id="feedbackDrawer" aria-labelledby="feedbackDrawerTitle" aria-hidden="true">
        <header class="feedback-drawer-header">
          <div>
            <p>HRAS LISTENING DESK</p>
            <h2 id="feedbackDrawerTitle">反馈与更新</h2>
          </div>
          <button id="feedbackDrawerClose" type="button" aria-label="关闭反馈与更新">×</button>
        </header>
        <nav class="feedback-tabs" role="tablist" aria-label="反馈与更新栏目">
          <button type="button" role="tab" aria-selected="true" data-feedback-tab="submit">我要反馈</button>
          <button type="button" role="tab" aria-selected="false" data-feedback-tab="mine">我的反馈</button>
          <button type="button" role="tab" aria-selected="false" data-feedback-tab="updates">
            更新公告 <i id="feedbackTabDot" aria-hidden="true" hidden></i>
          </button>
        </nav>

        <section class="feedback-pane active" data-feedback-pane="submit" role="tabpanel">
          <form id="feedbackSubmitForm">
            <input type="hidden" name="category" value="general" />
            <fieldset class="feedback-module-picker">
              <legend>所属模块（必选）</legend>
              <label><input type="radio" name="moduleId" value="home" required /><span>首页</span></label>
              <label><input type="radio" name="moduleId" value="recruitment" required /><span>招聘奖金</span></label>
              <label><input type="radio" name="moduleId" value="employee" required /><span>正式工</span></label>
              <label><input type="radio" name="moduleId" value="domestic" required /><span>外包工</span></label>
              <label><input type="radio" name="moduleId" value="fbu" required /><span>FBU绩效</span></label>
              <label><input type="radio" name="moduleId" value="overseas" required /><span>海外报账</span></label>
            </fieldset>
            <label class="feedback-description-field">
              <span>问题描述</span>
              <textarea name="description" rows="7" minlength="4" maxlength="4000" required placeholder="请描述发生了什么、你原本希望看到什么。可直接粘贴截图。"></textarea>
            </label>
            <div class="feedback-dropzone" id="feedbackDropzone" tabindex="0" role="button" aria-controls="feedbackFileInput">
              <strong>粘贴、拖入或选择截图</strong>
              <span>PNG / JPG / WebP，最多 3 张，单张不超过 5MB</span>
              <button type="button" id="feedbackChooseFiles">选择图片</button>
              <input id="feedbackFileInput" type="file" accept="image/png,image/jpeg,image/webp" multiple hidden />
            </div>
            <div class="feedback-file-previews" id="feedbackFilePreviews" aria-live="polite"></div>
            <p class="feedback-privacy-note">提交前请检查截图，避免包含工资金额、身份证号等无关敏感信息。</p>
            <div class="feedback-submit-row">
              <span id="feedbackSubmitStatus" role="status" aria-live="polite"></span>
              <button type="submit">提交反馈</button>
            </div>
          </form>
        </section>

        <section class="feedback-pane" data-feedback-pane="mine" role="tabpanel" hidden>
          <div class="feedback-pane-heading">
            <div><p>SUBMISSION HISTORY</p><h3>我的反馈</h3></div>
            <button type="button" id="feedbackRefreshMine">刷新</button>
          </div>
          <div class="feedback-history" id="feedbackMineList"></div>
        </section>

        <section
          class="feedback-image-preview"
          id="feedbackImagePreview"
          role="dialog"
          aria-modal="true"
          aria-label="截图预览"
          hidden
        >
          <button class="feedback-image-preview-close" id="feedbackImagePreviewClose" type="button" aria-label="关闭截图预览">×</button>
          <figure>
            <img id="feedbackImagePreviewImage" alt="" />
          </figure>
        </section>

        <section class="feedback-pane updates-pane" data-feedback-pane="updates" role="tabpanel" hidden>
          <div class="feedback-pane-heading">
            <div><p>WHAT'S NEW</p><h3>最新更新</h3></div>
            <span>简短浏览 · 点击看详情</span>
          </div>
          <div class="announcement-board" id="feedbackAnnouncementBoard"></div>
        </section>

        <section
          class="announcement-detail-overlay"
          id="feedbackAnnouncementDetail"
          role="dialog"
          aria-modal="true"
          aria-labelledby="feedbackAnnouncementDetailTitle"
          hidden
        >
          <header>
            <div><p>RELEASE NOTE</p><strong>更新详情</strong></div>
            <button id="feedbackAnnouncementDetailClose" type="button" aria-label="关闭更新详情">×</button>
          </header>
          <div class="announcement-detail-scroll">
            <article class="announcement-detail-paper">
              <div class="announcement-detail-meta">
                <span id="feedbackAnnouncementDetailKind"></span>
                <time id="feedbackAnnouncementDetailTime"></time>
              </div>
              <h3 id="feedbackAnnouncementDetailTitle"></h3>
              <figure class="announcement-detail-media" id="feedbackAnnouncementDetailMedia" hidden>
                <button id="feedbackAnnouncementDetailImageOpen" type="button" aria-label="放大预览公告界面图片">
                  <img id="feedbackAnnouncementDetailImage" alt="" loading="lazy" decoding="async" />
                </button>
                <figcaption id="feedbackAnnouncementDetailCaption"></figcaption>
              </figure>
              <div class="announcement-richtext" id="feedbackAnnouncementDetailContent"></div>
              <footer id="feedbackAnnouncementDetailModule"></footer>
            </article>
          </div>
        </section>
      </aside>
    </div>
  `;

  const ensureFeedbackWidget = () => {
    const existing = document.getElementById("feedbackWidget");
    if (existing) return existing;
    const container = document.createElement("div");
    container.innerHTML = widgetMarkup.trim();
    const created = container.firstElementChild;
    document.body.append(created);
    return created;
  };

  const widget = ensureFeedbackWidget();

  const launcher = document.getElementById("feedbackLauncher");
  const drawer = document.getElementById("feedbackDrawer");
  const scrim = document.getElementById("feedbackScrim");
  const closeButton = document.getElementById("feedbackDrawerClose");
  const form = document.getElementById("feedbackSubmitForm");
  const fileInput = document.getElementById("feedbackFileInput");
  const chooseFiles = document.getElementById("feedbackChooseFiles");
  const dropzone = document.getElementById("feedbackDropzone");
  const previews = document.getElementById("feedbackFilePreviews");
  const status = document.getElementById("feedbackSubmitStatus");
  const mineList = document.getElementById("feedbackMineList");
  const imagePreview = document.getElementById("feedbackImagePreview");
  const imagePreviewImage = document.getElementById("feedbackImagePreviewImage");
  const imagePreviewClose = document.getElementById("feedbackImagePreviewClose");
  const announcementBoard = document.getElementById("feedbackAnnouncementBoard");
  const announcementDetail = document.getElementById("feedbackAnnouncementDetail");
  const announcementDetailClose = document.getElementById("feedbackAnnouncementDetailClose");
  const announcementDetailKind = document.getElementById("feedbackAnnouncementDetailKind");
  const announcementDetailTitle = document.getElementById("feedbackAnnouncementDetailTitle");
  const announcementDetailContent = document.getElementById("feedbackAnnouncementDetailContent");
  const announcementDetailModule = document.getElementById("feedbackAnnouncementDetailModule");
  const announcementDetailTime = document.getElementById("feedbackAnnouncementDetailTime");
  const announcementDetailMedia = document.getElementById("feedbackAnnouncementDetailMedia");
  const announcementDetailImageOpen = document.getElementById("feedbackAnnouncementDetailImageOpen");
  const announcementDetailImage = document.getElementById("feedbackAnnouncementDetailImage");
  const announcementDetailCaption = document.getElementById("feedbackAnnouncementDetailCaption");
  const unreadDot = document.getElementById("feedbackUnreadDot");
  const tabDot = document.getElementById("feedbackTabDot");
  document.body.append(imagePreview);
  const lastSeenKey = "hras-announcement-last-seen-v1";
  const readAnnouncementsKey = "hras-announcement-read-v1";
  const allowedImageTypes = new Set(["image/png", "image/jpeg", "image/webp"]);
  let selectedFiles = [];
  let announcements = [];
  let activeTab = "submit";
  let imagePreviewTrigger = null;
  let readAnnouncementIds = new Set();

  try {
    const savedReadIds = JSON.parse(localStorage.getItem(readAnnouncementsKey) || "[]");
    if (Array.isArray(savedReadIds)) readAnnouncementIds = new Set(savedReadIds.map(String));
  } catch {
    readAnnouncementIds = new Set();
  }

  const apiRequest = async (url, options = {}) => {
    const response = await fetch(url, { credentials: "same-origin", ...options });
    if (response.status === 401) {
      window.location.href = `login.html?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
      throw new Error("登录已失效，请重新登录。");
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
    if (!value) return "刚刚";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  };

  const setUnread = (visible) => {
    unreadDot.hidden = !visible;
    tabDot.hidden = !visible;
  };

  const openDrawer = (tab = activeTab) => {
    widget.classList.add("open");
    launcher.setAttribute("aria-expanded", "true");
    drawer.setAttribute("aria-hidden", "false");
    scrim.hidden = false;
    activateTab(tab);
    closeButton.focus({ preventScroll: true });
  };

  const closeDrawer = () => {
    closeImagePreview();
    closeAnnouncementDetail();
    widget.classList.remove("open");
    launcher.setAttribute("aria-expanded", "false");
    drawer.setAttribute("aria-hidden", "true");
    scrim.hidden = true;
    launcher.focus({ preventScroll: true });
  };

  const activateTab = (tab) => {
    closeImagePreview();
    if (tab !== "updates") closeAnnouncementDetail();
    activeTab = tab;
    document.querySelectorAll("[data-feedback-tab]").forEach((button) => {
      button.setAttribute("aria-selected", button.dataset.feedbackTab === tab ? "true" : "false");
    });
    document.querySelectorAll("[data-feedback-pane]").forEach((pane) => {
      const active = pane.dataset.feedbackPane === tab;
      pane.hidden = !active;
      pane.classList.toggle("active", active);
    });
    if (tab === "mine") loadMyFeedback();
    if (tab === "updates") {
      renderAnnouncements();
    }
  };

  const addFiles = (files) => {
    const next = Array.from(files || []);
    for (const file of next) {
      if (!allowedImageTypes.has(file.type)) {
        status.textContent = "截图仅支持 PNG、JPG 或 WebP。";
        status.classList.add("error");
        continue;
      }
      if (file.size > 5 * 1024 * 1024) {
        status.textContent = `${file.name || "截图"} 超过 5MB。`;
        status.classList.add("error");
        continue;
      }
      if (selectedFiles.length >= 3) {
        status.textContent = "每次最多添加 3 张截图。";
        status.classList.add("error");
        break;
      }
      selectedFiles.push({ file, previewUrl: URL.createObjectURL(file) });
    }
    renderFilePreviews();
  };

  const clearFiles = () => {
    selectedFiles.forEach((item) => URL.revokeObjectURL(item.previewUrl));
    selectedFiles = [];
    fileInput.value = "";
    renderFilePreviews();
  };

  const renderFilePreviews = () => {
    previews.replaceChildren();
    selectedFiles.forEach((item, index) => {
      const wrapper = document.createElement("div");
      wrapper.className = "feedback-file-preview";
      const image = document.createElement("img");
      image.src = item.previewUrl;
      image.alt = `待提交截图 ${index + 1}`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `移除截图 ${index + 1}`);
      remove.addEventListener("click", () => {
        URL.revokeObjectURL(item.previewUrl);
        selectedFiles.splice(index, 1);
        renderFilePreviews();
      });
      wrapper.append(image, remove);
      previews.append(wrapper);
    });
  };

  const historyItem = (item) => {
    const article = document.createElement("article");
    article.className = "feedback-history-item";
    const header = document.createElement("header");
    const tag = document.createElement("span");
    tag.textContent = item.moduleShortName || item.moduleName;
    const time = document.createElement("time");
    time.dateTime = item.createdAt;
    time.textContent = formatTime(item.createdAt);
    header.append(tag, time);
    const description = document.createElement("p");
    description.textContent = item.description;
    const attachments = document.createElement("div");
    attachments.className = "feedback-history-attachments";
    (item.attachments || []).slice(0, 3).forEach((attachment, index) => {
      const previewUrl = `/api/workbench/feedback/${encodeURIComponent(item.id)}/attachments/${encodeURIComponent(attachment.id)}`;
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-label", `在当前页预览反馈截图 ${index + 1}`);
      const image = document.createElement("img");
      image.src = previewUrl;
      image.alt = `反馈截图 ${index + 1}`;
      image.loading = "lazy";
      button.append(image);
      button.addEventListener("click", () => openImagePreview(previewUrl, image.alt, button));
      attachments.append(button);
    });
    const footer = document.createElement("footer");
    footer.textContent = `${item.id}${item.attachmentCount ? ` · ${item.attachmentCount} 张截图` : " · 无截图"}`;
    article.append(header, description);
    if (attachments.childElementCount) article.append(attachments);
    article.append(footer);
    return article;
  };

  const openImagePreview = (source, alt, trigger, title = "截图预览") => {
    imagePreviewTrigger = trigger || null;
    imagePreview.setAttribute("aria-label", title);
    imagePreviewImage.src = source;
    imagePreviewImage.alt = alt || "反馈截图";
    imagePreview.hidden = false;
    imagePreviewClose.focus({ preventScroll: true });
  };

  const closeImagePreview = () => {
    if (!imagePreview || imagePreview.hidden) return;
    imagePreview.hidden = true;
    imagePreviewImage.removeAttribute("src");
    imagePreviewImage.alt = "";
    imagePreviewTrigger?.focus({ preventScroll: true });
    imagePreviewTrigger = null;
  };

  const loadMyFeedback = async () => {
    mineList.replaceChildren();
    const loading = document.createElement("div");
    loading.className = "feedback-empty";
    loading.textContent = "正在读取提交记录…";
    mineList.append(loading);
    try {
      const data = await apiRequest("/api/workbench/feedback/mine?limit=50");
      mineList.replaceChildren();
      if (!data.feedback?.length) {
        const empty = document.createElement("div");
        empty.className = "feedback-empty";
        empty.textContent = "还没有提交过反馈。";
        mineList.append(empty);
        return;
      }
      data.feedback.forEach((item) => mineList.append(historyItem(item)));
    } catch (error) {
      mineList.replaceChildren();
      const failed = document.createElement("div");
      failed.className = "feedback-empty";
      failed.textContent = error.message || "反馈记录加载失败。";
      mineList.append(failed);
    }
  };

  const appendInlineRichText = (container, text) => {
    const tokenPattern = /(\*\*[^*]+\*\*|==[^=]+==|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
    let cursor = 0;
    for (const match of text.matchAll(tokenPattern)) {
      if (match.index > cursor) container.append(document.createTextNode(text.slice(cursor, match.index)));
      const token = match[0];
      if (token.startsWith("**")) {
        const strong = document.createElement("strong");
        strong.textContent = token.slice(2, -2);
        container.append(strong);
      } else if (token.startsWith("==")) {
        const mark = document.createElement("mark");
        mark.textContent = token.slice(2, -2);
        container.append(mark);
      } else {
        const parts = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
        const link = document.createElement("a");
        link.textContent = parts?.[1] || "查看详情";
        link.href = parts?.[2] || "#";
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        container.append(link);
      }
      cursor = match.index + token.length;
    }
    if (cursor < text.length) container.append(document.createTextNode(text.slice(cursor)));
  };

  const renderRichText = (container, source) => {
    container.replaceChildren();
    const lines = String(source || "").split(/\r?\n/);
    let list = null;
    const flushList = () => {
      if (list) container.append(list);
      list = null;
    };
    lines.forEach((rawLine) => {
      const line = rawLine.trim();
      if (!line) {
        flushList();
        return;
      }
      if (line.startsWith("- ")) {
        list ||= document.createElement("ul");
        const item = document.createElement("li");
        appendInlineRichText(item, line.slice(2));
        list.append(item);
        return;
      }
      flushList();
      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      const block = document.createElement(
        line.startsWith("> ") ? "blockquote" : heading ? `h${Math.min(heading[1].length + 2, 5)}` : "p",
      );
      appendInlineRichText(block, line.startsWith("> ") ? line.slice(2) : heading ? heading[2] : line);
      container.append(block);
    });
    flushList();
  };

  const announcementExcerpt = (source) => {
    const firstBlock = String(source || "")
      .trim()
      .split(/\r?\n\s*\r?\n/)
      .find((block) => block.trim()) || "";
    const plain = firstBlock
      .replace(/\[([^\]]+)\]\(https?:\/\/[^\s)]+\)/g, "$1")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/==([^=]+)==/g, "$1")
      .replace(/^\s*[-#>]\s*/gm, "")
      .replace(/\s+/g, " ")
      .trim();
    return plain.length > 82 ? `${plain.slice(0, 82).trim()}…` : plain;
  };

  const closeAnnouncementDetail = () => {
    if (!announcementDetail || announcementDetail.hidden) return;
    announcementDetail.hidden = true;
  };

  const syncUnreadState = () => {
    setUnread(announcements.some((item) => !readAnnouncementIds.has(item.id)));
  };

  const persistReadAnnouncements = () => {
    const savedIds = Array.from(readAnnouncementIds).slice(-200);
    readAnnouncementIds = new Set(savedIds);
    localStorage.setItem(readAnnouncementsKey, JSON.stringify(savedIds));
  };

  const markAnnouncementRead = (announcementId) => {
    if (!announcementId || readAnnouncementIds.has(announcementId)) return;
    readAnnouncementIds.add(announcementId);
    persistReadAnnouncements();
    Array.from(announcementBoard.children)
      .find((element) => element.dataset.announcementId === announcementId)
      ?.classList.remove("unread");
    syncUnreadState();
  };

  const openAnnouncementDetail = (item) => {
    markAnnouncementRead(item.id);
    announcementDetailKind.textContent = item.kindLabel;
    announcementDetailTitle.textContent = item.title;
    announcementDetailModule.textContent = `${item.moduleName} · ${item.createdByName || "HRAS 工作台"}`;
    announcementDetailTime.dateTime = item.publishedAt;
    announcementDetailTime.textContent = formatTime(item.publishedAt);
    const hasImage = Boolean(item.imageUrl);
    announcementDetailMedia.hidden = !hasImage;
    if (hasImage) {
      announcementDetailImage.src = item.imageUrl;
      announcementDetailImage.alt = item.imageAlt || `${item.moduleName}页面界面`;
      announcementDetailCaption.textContent = `界面预览 · ${item.moduleName}`;
      announcementDetailImageOpen.onclick = () => openImagePreview(
        item.imageUrl,
        announcementDetailImage.alt,
        announcementDetailImageOpen,
        "界面预览",
      );
    } else {
      announcementDetailImage.removeAttribute("src");
      announcementDetailImage.alt = "";
      announcementDetailCaption.textContent = "";
      announcementDetailImageOpen.onclick = null;
    }
    renderRichText(announcementDetailContent, item.content);
    announcementDetail.hidden = false;
    announcementDetailClose.focus({ preventScroll: true });
  };

  const announcementNote = (item) => {
    const article = document.createElement("article");
    article.className = "announcement-note";
    article.dataset.announcementId = item.id;
    article.classList.toggle("unread", !readAnnouncementIds.has(item.id));
    const open = document.createElement("button");
    open.type = "button";
    open.className = "announcement-note-open";
    open.setAttribute("aria-label", `查看更新：${item.title}`);
    const body = document.createElement("div");
    body.className = "announcement-note-body";
    const meta = document.createElement("div");
    meta.className = "note-meta";
    const stamp = document.createElement("span");
    stamp.className = "note-stamp";
    stamp.textContent = item.kindLabel;
    const module = document.createElement("span");
    module.textContent = item.moduleName;
    const time = document.createElement("time");
    time.dateTime = item.publishedAt;
    time.textContent = formatTime(item.publishedAt);
    meta.append(stamp, module, time);
    const title = document.createElement("h4");
    title.textContent = item.title;
    const preview = document.createElement("p");
    preview.className = "note-preview";
    preview.textContent = announcementExcerpt(item.content);
    const arrow = document.createElement("span");
    arrow.className = "note-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "→";
    body.append(meta, title, preview);
    open.append(body);
    if (item.imageUrl) {
      const image = document.createElement("img");
      image.className = "announcement-note-image";
      image.src = item.imageUrl;
      image.alt = "";
      image.loading = "lazy";
      image.decoding = "async";
      open.append(image);
    }
    open.append(arrow);
    open.addEventListener("click", () => openAnnouncementDetail(item));
    article.append(open);
    return article;
  };

  const renderAnnouncements = () => {
    announcementBoard.replaceChildren();
    if (!announcements.length) {
      const empty = document.createElement("div");
      empty.className = "feedback-empty";
      empty.textContent = "公告墙还是空的，新内容会出现在这里。";
      announcementBoard.append(empty);
      return;
    }
    announcements.forEach((item) => announcementBoard.append(announcementNote(item)));
  };

  const loadAnnouncements = async () => {
    try {
      const data = await apiRequest("/api/workbench/announcements?limit=50");
      announcements = data.announcements || [];
      if (!localStorage.getItem(readAnnouncementsKey) && localStorage.getItem(lastSeenKey)) {
        announcements.forEach((item) => readAnnouncementIds.add(item.id));
        persistReadAnnouncements();
      }
      renderAnnouncements();
      syncUnreadState();
      const requested = new URLSearchParams(window.location.search).get("announcement");
      if (requested) {
        openDrawer("updates");
        const requestedAnnouncement = announcements.find((item) => item.id === requested);
        if (requestedAnnouncement) openAnnouncementDetail(requestedAnnouncement);
      }
    } catch {
      announcements = [];
      renderAnnouncements();
    }
  };

  launcher.addEventListener("click", () => openDrawer());
  closeButton.addEventListener("click", closeDrawer);
  announcementDetailClose?.addEventListener("click", closeAnnouncementDetail);
  imagePreviewClose?.addEventListener("click", closeImagePreview);
  imagePreview?.addEventListener("click", (event) => {
    if (event.target === imagePreview) closeImagePreview();
  });
  scrim.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !widget.classList.contains("open")) return;
    if (!imagePreview.hidden) closeImagePreview();
    else if (!announcementDetail.hidden) closeAnnouncementDetail();
    else closeDrawer();
  });
  document.querySelectorAll("[data-feedback-tab]").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.feedbackTab));
  });
  document.getElementById("feedbackRefreshMine")?.addEventListener("click", loadMyFeedback);

  chooseFiles.addEventListener("click", (event) => {
    event.stopPropagation();
    fileInput.click();
  });
  dropzone.addEventListener("click", (event) => {
    if (event.target === chooseFiles) return;
    fileInput.click();
  });
  dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", () => addFiles(fileInput.files));
  ["dragenter", "dragover"].forEach((type) => dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragover");
  }));
  ["dragleave", "drop"].forEach((type) => dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragover");
  }));
  dropzone.addEventListener("drop", (event) => addFiles(event.dataTransfer?.files));
  drawer.addEventListener("paste", (event) => {
    const images = Array.from(event.clipboardData?.files || []).filter((file) => allowedImageTypes.has(file.type));
    if (!images.length) return;
    event.preventDefault();
    addFiles(images);
    status.textContent = `已粘贴 ${images.length} 张截图。`;
    status.classList.remove("error");
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitButton = form.querySelector("button[type='submit']");
    submitButton.disabled = true;
    submitButton.textContent = "提交中…";
    status.textContent = "正在保存反馈并通知管理员…";
    status.classList.remove("error");
    const payload = new FormData(form);
    payload.set("pagePath", window.location.pathname);
    selectedFiles.forEach((item) => payload.append("attachments", item.file, item.file.name || "screenshot.png"));
    try {
      const data = await apiRequest("/api/workbench/feedback", { method: "POST", body: payload });
      status.textContent = `已收到 · ${data.feedback.id}`;
      form.reset();
      clearFiles();
    } catch (error) {
      status.textContent = error.message || "反馈提交失败，请稍后重试。";
      status.classList.add("error");
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "提交反馈";
    }
  });

  loadAnnouncements();
})();

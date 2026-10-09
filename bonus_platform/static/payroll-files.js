/* Private direct uploads/downloads keep large Excel files outside Vercel bodies. */
(() => {
  "use strict";
  const base = "/api/china-employee-payroll/activities";
  async function json(url, options = {}) {
    const response = await fetch(url, { ...options, signal: AbortSignal.timeout(60000) });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "文件服务暂不可用，请重试。");
    return data;
  }
  async function digest(buffer) {
    return [...new Uint8Array(await crypto.subtle.digest("SHA-256", buffer))].map(v => v.toString(16).padStart(2, "0")).join("");
  }
  window.PayrollFiles = {
    async upload(activityId, files) {
      if (!(await json(`${base}/config/upload`)).directUpload) return null;
      const descriptors = [];
      if (files.some(file => file.size > 50 * 1024 * 1024) || files.reduce((n, f) => n + f.size, 0) > 100 * 1024 * 1024) throw new Error("单文件上限 50 MB，一次核算总大小上限 100 MB。");
      for (const file of files) descriptors.push({ name: file.name, size: file.size, sha256: await digest(await file.arrayBuffer()) });
      const signed = await json(`${base}/${activityId}/uploads`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ files: descriptors }) });
      for (let index = 0; index < files.length; index++) {
        const target = signed.files[index];
        const response = await fetch(target.signedUrl, { method: target.method, headers: target.headers, body: files[index], credentials: "omit", signal: AbortSignal.timeout(180000) });
        if (!response.ok) throw new Error("考勤文件上传失败，请检查文件存储后重试。");
      }
      return json(`${base}/${activityId}/start`, { method: "POST" });
    },
    async download(response) {
      if (!(response.headers.get("content-type") || "").includes("application/json")) return { blob: await response.blob(), filename: "" };
      const manifest = await response.json();
      const downloaded = await fetch(manifest.downloadUrl, { credentials: "omit", signal: AbortSignal.timeout(180000) });
      if (!downloaded.ok) throw new Error("导出文件读取失败，请重试。");
      const buffer = await downloaded.arrayBuffer();
      if (buffer.byteLength !== manifest.size || await digest(buffer) !== manifest.sha256) throw new Error("导出文件校验失败，请重新下载。");
      return { blob: new Blob([buffer], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), filename: manifest.filename };
    }
  };
})();

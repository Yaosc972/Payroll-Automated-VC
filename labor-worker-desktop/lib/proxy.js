function proxyUrl(scheme, authority) {
  const value = String(authority || "").trim();
  if (!value || /[\\/@\s]/.test(value)) return "";
  try {
    const parsed = new URL(`${scheme}://${value}`);
    const port = Number(parsed.port || 0);
    if (!parsed.hostname || !port || port > 65535) return "";
    return parsed.toString().replace(/\/$/, "");
  } catch (_error) {
    return "";
  }
}

function proxyEnvironment(proxyRules) {
  const cleared = {
    HTTP_PROXY: "",
    HTTPS_PROXY: "",
    ALL_PROXY: "",
    http_proxy: "",
    https_proxy: "",
    all_proxy: ""
  };
  const rules = String(proxyRules || "")
    .split(";")
    .map((rule) => rule.trim())
    .filter(Boolean);
  for (const rule of rules) {
    const [kind, authority = ""] = rule.split(/\s+/, 2);
    const normalizedKind = String(kind || "").toUpperCase();
    if (normalizedKind === "DIRECT") {
      return { ...cleared, SIGMA_WORKER_PROXY_MODE: "direct" };
    }
    if (["PROXY", "HTTP", "HTTPS"].includes(normalizedKind)) {
      const url = proxyUrl("http", authority);
      if (url) {
        return {
          ...cleared,
          HTTP_PROXY: url,
          HTTPS_PROXY: url,
          SIGMA_WORKER_PROXY_MODE: "system"
        };
      }
    }
    if (["SOCKS", "SOCKS5"].includes(normalizedKind)) {
      const url = proxyUrl("socks5", authority);
      if (url) {
        return {
          ...cleared,
          ALL_PROXY: url,
          SIGMA_WORKER_PROXY_MODE: "system"
        };
      }
    }
  }
  return { ...cleared, SIGMA_WORKER_PROXY_MODE: "unresolved" };
}

module.exports = { proxyEnvironment };

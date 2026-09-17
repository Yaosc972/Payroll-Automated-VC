(async function bootHrasShell() {
  const sdk = window.__HRAS__;
  if (!sdk || typeof sdk.ready !== "function") return;

  try {
    await sdk.ready();
  } catch {
    return;
  }

  const key = window.__HRAS_MODULE_KEY || "hras-payroll";
  if (typeof sdk.setModuleKey === "function") {
    sdk.setModuleKey(key);
  }

  const isEmbedded = (() => {
    try {
      return window.self !== window.top;
    } catch {
      return true;
    }
  })();
  if (!isEmbedded) return;

  const token = typeof sdk.getToken === "function" ? sdk.getToken() : window.__hrasToken;
  if (!token) return;

  document.addEventListener("click", (event) => {
    const link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
    if (!link) return;
    try {
      const url = new URL(link.getAttribute("href"), window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.searchParams.get("token")) return;
      url.searchParams.set("token", token);
      link.setAttribute("href", url.pathname + url.search + url.hash);
    } catch {
      // Keep the original href if it cannot be rewritten.
    }
  });
})();

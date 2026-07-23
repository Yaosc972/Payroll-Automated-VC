function parseActivationUrl(value) {
  try {
    const activation = new URL(String(value || ""));
    if (activation.protocol !== "sigma-overseas-labor-worker:" || activation.hostname !== "activate") return null;
    const apiUrl = new URL(activation.searchParams.get("apiUrl") || "");
    const activationCode = activation.searchParams.get("code") || "";
    if (apiUrl.protocol !== "https:" || !activationCode.startsWith("sigma_labor_a1_") || activationCode.length < 24) return null;
    return { apiUrl: apiUrl.origin, activationCode };
  } catch (_error) {
    return null;
  }
}

async function exchangeActivation(activation, { workerVersion, fetchImpl = globalThis.fetch } = {}) {
  if (!activation || typeof fetchImpl !== "function") throw new Error("Worker activation exchange unavailable");
  const response = await fetchImpl(`${activation.apiUrl}/api/labor/worker/activate`, {
    method: "POST",
    headers: { "content-type": "application/json", "cache-control": "no-store" },
    cache: "no-store",
    body: JSON.stringify({
      activationCode: activation.activationCode,
      workerVersion: String(workerVersion || "").slice(0, 40)
    })
  });
  if (!response || !response.ok) throw new Error("Worker activation exchange failed");
  const issued = await response.json();
  const token = String(issued?.token || "");
  if (!token.startsWith("sigma_labor_w1_") || token.length < 24) throw new Error("Worker activation response invalid");
  return { ...issued, token };
}

module.exports = { exchangeActivation, parseActivationUrl };

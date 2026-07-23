function createActivationDispatcher(handler) {
  if (typeof handler !== "function") throw new TypeError("Activation handler is required");
  let ready = false;
  const pending = [];
  const seen = new Set();

  async function enqueue(value) {
    const activationUrl = String(value || "");
    if (!activationUrl || seen.has(activationUrl)) return false;
    seen.add(activationUrl);
    if (!ready) {
      pending.push(activationUrl);
      return false;
    }
    await handler(activationUrl);
    return true;
  }

  async function markReady() {
    if (ready) return;
    ready = true;
    while (pending.length) await handler(pending.shift());
  }

  return { enqueue, markReady };
}

module.exports = { createActivationDispatcher };

import { execFileSync } from "node:child_process";

const KEYCHAIN_SERVICES = {
  appKey: "beisen-social-insurance-key",
  appSecret: "beisen-social-insurance-secret",
};

function keychainValue(service) {
  try {
    const account = execFileSync("/usr/bin/id", ["-un"], { encoding: "utf8" }).trim();
    return execFileSync("/usr/bin/security", [
      "find-generic-password", "-a", account, "-s", service, "-w",
    ], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).replace(/[\r\n]+$/u, "");
  } catch {
    return "";
  }
}

/**
 * Local macOS convenience only. Company servers should provide BEISEN_APP_KEY
 * and BEISEN_APP_SECRET through their secret manager/environment.
 */
export function ensureLocalBeisenCredentials() {
  if (process.env.VERCEL) return;
  if (!String(process.env.BEISEN_APP_KEY || "").trim()) {
    process.env.BEISEN_APP_KEY = keychainValue(KEYCHAIN_SERVICES.appKey);
  }
  if (!String(process.env.BEISEN_APP_SECRET || "").trim()) {
    process.env.BEISEN_APP_SECRET = keychainValue(KEYCHAIN_SERVICES.appSecret);
  }
}

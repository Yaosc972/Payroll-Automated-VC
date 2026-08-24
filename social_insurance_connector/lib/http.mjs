import { timingSafeEqual } from "node:crypto";
import { ConnectorError, safeErrorResponse } from "./errors.mjs";

function constantTimeEqual(left, right) {
  const leftBuffer = Buffer.from(left || "", "utf8");
  const rightBuffer = Buffer.from(right || "", "utf8");
  if (!leftBuffer.length || leftBuffer.length !== rightBuffer.length) return false;
  return timingSafeEqual(leftBuffer, rightBuffer);
}

function authorize(request) {
  const expected = String(process.env.CONNECTOR_TOKEN || "").trim();
  if (!expected) throw new ConnectorError("CONNECTOR_NOT_CONFIGURED", "连接器授权未配置", 503);
  const authorization = String(request.headers?.authorization || "");
  const supplied = authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : "";
  if (!constantTimeEqual(expected, supplied)) {
    throw new ConnectorError("UNAUTHORIZED", "连接器授权失败", 401);
  }
}

export function createPostHandler(operation) {
  return async function handler(request, response) {
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("X-Content-Type-Options", "nosniff");
    try {
      if (request.method !== "POST") {
        response.setHeader("Allow", "POST");
        throw new ConnectorError("METHOD_NOT_ALLOWED", "仅允许 POST 请求", 405);
      }
      authorize(request);
      const body = request.body && typeof request.body === "object" ? request.body : {};
      const result = await operation(body);
      return response.status(200).json(result);
    } catch (error) {
      const safe = safeErrorResponse(error);
      if (safe.status >= 500) {
        console.error(JSON.stringify({ event: "social-insurance-connector-failure", code: safe.body.error }));
      }
      return response.status(safe.status).json(safe.body);
    }
  };
}

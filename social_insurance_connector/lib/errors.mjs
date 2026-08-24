export class ConnectorError extends Error {
  constructor(code, message, status = 400) {
    super(message);
    this.name = "ConnectorError";
    this.code = code;
    this.status = status;
  }
}

export function safeErrorResponse(error) {
  if (error instanceof ConnectorError) {
    return {
      status: error.status,
      body: { error: error.code, message: error.message },
    };
  }
  return {
    status: 500,
    body: { error: "CONNECTOR_INTERNAL_ERROR", message: "连接器处理失败" },
  };
}

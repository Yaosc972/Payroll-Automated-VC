module.exports = function handleFeishuEvent(request, response) {
  const payload = request.body && typeof request.body === "object" ? request.body : {};
  const challenge = payload.challenge;

  if (payload.type === "url_verification" && typeof challenge === "string") {
    return response.status(200).json({ challenge });
  }

  return response.status(200).json({ code: 0 });
};

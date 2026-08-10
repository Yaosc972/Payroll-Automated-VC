export const config = { runtime: "edge" };

export default async function handleFeishuEvent(request) {
  const payload = await request.json().catch(() => ({}));
  const challenge = payload.challenge;

  if (payload.type === "url_verification" && typeof challenge === "string") {
    return Response.json({ challenge });
  }

  return Response.json({ code: 0 });
}

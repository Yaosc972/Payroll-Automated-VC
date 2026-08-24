export default function handler(_request, response) {
  response.setHeader("Cache-Control", "no-store");
  return response.status(200).json({
    ok: true,
    service: "sigma-social-insurance-connector-uat",
    configured: Boolean(
      process.env.CONNECTOR_TOKEN
      && process.env.BEISEN_APP_KEY
      && process.env.BEISEN_APP_SECRET
      && process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64
    ),
  });
}

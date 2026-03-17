import { Router } from "express";

export function usageRoutes(db) {
  const router = Router();

  // GET /api/usage — current API key usage stats
  router.get("/", (req, res) => {
    const record = req.apiKeyRecord;
    res.json({
      client_name: record.client_name,
      monthly_limit: record.monthly_limit,
      renders_used: record.renders_used,
      remaining: Math.max(0, record.monthly_limit - record.renders_used),
      expires_at: record.expires_at,
    });
  });

  return router;
}

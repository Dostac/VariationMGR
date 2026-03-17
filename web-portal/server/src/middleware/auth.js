import { hashApiKey, validateApiKey } from "../db.js";

export function authMiddleware(db) {
  return (req, res, next) => {
    // Skip auth for health endpoint
    if (req.path === "/health") return next();

    const header = req.headers.authorization;
    if (!header || !header.startsWith("Bearer ")) {
      return res.status(401).json({ error: "Missing API key" });
    }

    const apiKey = header.slice(7);
    const keyHash = hashApiKey(apiKey);
    const keyRecord = validateApiKey(db, keyHash);

    if (!keyRecord) {
      return res.status(401).json({ error: "Invalid or expired API key" });
    }

    req.apiKeyHash = keyHash;
    req.apiKeyRecord = keyRecord;
    next();
  };
}

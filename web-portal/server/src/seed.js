/**
 * Seed script: creates a test API key for development.
 * Run: node src/seed.js
 */
import crypto from "crypto";
import { initDb, hashApiKey } from "./db.js";
import { loadConfig } from "./config.js";

const config = loadConfig();
const db = initDb(config.dbPath);

// Generate a random API key
const apiKey = `vb_${crypto.randomBytes(24).toString("hex")}`;
const keyHash = hashApiKey(apiKey);
const currentMonth = new Date().toISOString().slice(0, 7);

db.prepare(
  `INSERT OR IGNORE INTO api_keys (api_key_hash, client_name, monthly_limit, reset_month)
   VALUES (?, ?, ?, ?)`
).run(keyHash, "Development Client", 1000, currentMonth);

console.log("---------------------------------------------------");
console.log("API key created. Save this — it won't be shown again:");
console.log("");
console.log(`  ${apiKey}`);
console.log("");
console.log("Use it as: Authorization: Bearer <key>");
console.log("---------------------------------------------------");

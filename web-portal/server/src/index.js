import express from "express";
import cors from "cors";
import { initDb } from "./db.js";
import { authMiddleware } from "./middleware/auth.js";
import { templateRoutes } from "./routes/templates.js";
import { jobRoutes } from "./routes/jobs.js";
import { usageRoutes } from "./routes/usage.js";
import { loadConfig } from "./config.js";

const config = loadConfig();
const db = initDb(config.dbPath);
const app = express();

app.use(cors({ origin: config.corsOrigin }));
app.use(express.json({ limit: "1mb" }));

// Public health endpoint
app.get("/api/health", (_req, res) => {
  res.json({ ok: true, version: "1.0.0" });
});

// All /api routes require API key
app.use("/api", authMiddleware(db));

app.use("/api/templates", templateRoutes(config));
app.use("/api/jobs", jobRoutes(db, config));
app.use("/api/usage", usageRoutes(db));

app.listen(config.port, () => {
  console.log(`Web portal server listening on port ${config.port}`);
  console.log(`Templates dir: ${config.templatesDir}`);
  console.log(`Render server: ${config.renderServerUrl}`);
});

import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export function loadConfig() {
  return {
    port: parseInt(process.env.PORT || "3001", 10),
    corsOrigin: process.env.CORS_ORIGIN || "http://localhost:5173",
    dbPath: process.env.DB_PATH || path.resolve(__dirname, "..", "portal.db"),
    templatesDir:
      process.env.TEMPLATES_DIR ||
      path.resolve(__dirname, "..", "..", "templates"),
    renderServerUrl:
      process.env.RENDER_SERVER_URL || "http://localhost:8765",
    rendersOutputBase:
      process.env.RENDERS_OUTPUT_BASE ||
      path.resolve(__dirname, "..", "..", "renders"),
  };
}

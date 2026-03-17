import { Router } from "express";
import fs from "fs";
import path from "path";

export function templateRoutes(config) {
  const router = Router();

  function loadManifest(templateId) {
    const manifestPath = path.join(
      config.templatesDir,
      templateId,
      "template.json"
    );
    if (!fs.existsSync(manifestPath)) return null;
    return JSON.parse(fs.readFileSync(manifestPath, "utf-8"));
  }

  // GET /api/templates — list all templates
  router.get("/", (_req, res) => {
    const dir = config.templatesDir;
    if (!fs.existsSync(dir)) {
      return res.json({ templates: [] });
    }

    const entries = fs.readdirSync(dir, { withFileTypes: true });
    const templates = [];

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const manifest = loadManifest(entry.name);
      if (!manifest) continue;
      templates.push({
        template_id: manifest.template_id,
        display_name: manifest.display_name,
        description: manifest.description || "",
        thumbnail:
          manifest.preview_images && manifest.preview_images.length > 0
            ? manifest.preview_images[0]
            : null,
      });
    }

    res.json({ templates });
  });

  // GET /api/templates/:id — full manifest
  router.get("/:id", (req, res) => {
    const manifest = loadManifest(req.params.id);
    if (!manifest) {
      return res.status(404).json({ error: "Template not found" });
    }
    res.json(manifest);
  });

  // GET /api/templates/:id/proxy — serve .glb file
  router.get("/:id/proxy", (req, res) => {
    const manifest = loadManifest(req.params.id);
    if (!manifest || !manifest.proxy_gltf) {
      return res.status(404).json({ error: "Proxy model not found" });
    }
    const filePath = path.join(
      config.templatesDir,
      req.params.id,
      manifest.proxy_gltf
    );
    if (!fs.existsSync(filePath)) {
      return res.status(404).json({ error: "Proxy file missing" });
    }
    res.setHeader("Content-Type", "model/gltf-binary");
    res.sendFile(path.resolve(filePath));
  });

  // GET /api/templates/:id/previews/:file — serve preview images
  router.get("/:id/previews/:file", (req, res) => {
    const safeFile = path.basename(req.params.file);
    const filePath = path.join(
      config.templatesDir,
      req.params.id,
      "previews",
      safeFile
    );
    if (!fs.existsSync(filePath)) {
      return res.status(404).json({ error: "Preview not found" });
    }
    res.sendFile(path.resolve(filePath));
  });

  return router;
}

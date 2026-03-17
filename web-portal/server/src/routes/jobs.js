import { Router } from "express";
import fs from "fs";
import path from "path";
import { nanoid } from "nanoid";
import { incrementUsage } from "../db.js";
import { submitToRenderServer, pollRenderServer } from "../render-client.js";

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;

function validateRows(rows, schema) {
  const { headers, columns } = schema;
  const errors = [];

  for (let ri = 0; ri < rows.length; ri++) {
    const row = rows[ri];
    if (row.length !== headers.length) {
      errors.push(`Row ${ri + 1}: expected ${headers.length} values, got ${row.length}`);
      continue;
    }
    for (let ci = 0; ci < headers.length; ci++) {
      const colName = headers[ci];
      const colDef = columns[colName];
      if (!colDef) continue;
      const val = String(row[ci]).trim();

      if (colDef.type === "enum" && colDef.options) {
        if (!colDef.options.includes(val)) {
          errors.push(
            `Row ${ri + 1}, "${colName}": "${val}" not in [${colDef.options.join(", ")}]`
          );
        }
      } else if (colDef.type === "hex_color") {
        if (!HEX_COLOR_RE.test(val)) {
          errors.push(`Row ${ri + 1}, "${colName}": "${val}" is not a valid hex color`);
        }
      } else if (colDef.type === "number") {
        const num = Number(val);
        if (isNaN(num)) {
          errors.push(`Row ${ri + 1}, "${colName}": "${val}" is not a number`);
        } else {
          if (colDef.min !== undefined && num < colDef.min)
            errors.push(`Row ${ri + 1}, "${colName}": ${num} < min ${colDef.min}`);
          if (colDef.max !== undefined && num > colDef.max)
            errors.push(`Row ${ri + 1}, "${colName}": ${num} > max ${colDef.max}`);
        }
      }
    }
  }
  return errors;
}

export function jobRoutes(db, config) {
  const router = Router();

  // POST /api/jobs — submit render job
  router.post("/", (req, res) => {
    const { template_id, rows, render_preset, output_format } = req.body;

    if (!template_id || !rows || !Array.isArray(rows) || rows.length === 0) {
      return res
        .status(400)
        .json({ error: "template_id and non-empty rows[] required" });
    }

    // Check usage limit
    const keyRecord = req.apiKeyRecord;
    if (keyRecord.renders_used >= keyRecord.monthly_limit) {
      return res.status(429).json({
        error: "Monthly render limit reached",
        limit: keyRecord.monthly_limit,
        used: keyRecord.renders_used,
      });
    }

    // Load template manifest
    const manifestPath = path.join(
      config.templatesDir,
      template_id,
      "template.json"
    );
    if (!fs.existsSync(manifestPath)) {
      return res.status(404).json({ error: "Template not found" });
    }
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf-8"));
    const schema = manifest.variation_schema;

    // Validate rows against column schema
    const validationErrors = validateRows(rows, schema);
    if (validationErrors.length > 0) {
      return res.status(400).json({ error: "Validation failed", details: validationErrors });
    }

    // Resolve render preset
    const presetName = render_preset || "standard";
    const preset = (manifest.render_presets || {})[presetName];
    if (!preset) {
      return res.status(400).json({
        error: `Unknown render preset: "${presetName}"`,
        available: Object.keys(manifest.render_presets || {}),
      });
    }

    // Resolve output format
    const fmt = output_format || "jpg";
    if (manifest.output_formats && !manifest.output_formats.includes(fmt)) {
      return res.status(400).json({
        error: `Unsupported format: "${fmt}"`,
        available: manifest.output_formats,
      });
    }

    // Build job
    const jobId = nanoid(16);
    const outputFolder = path
      .join(config.rendersOutputBase, jobId)
      .replace(/\\/g, "/");

    // Build variation_override (same shape as VariationManagerData)
    const variationOverride = {
      scheme: schema.scheme,
      render_camera_mode: schema.render_camera_mode,
      render_camera_column: schema.render_camera_column || "",
      ops_folder: schema.ops_folder,
      headers: schema.headers,
      rows: rows,
      operators: schema.operators,
    };

    const jobPayload = {
      schema_version: 1,
      request_id: jobId,
      scene_file: manifest.scene_file,
      max_files: [],
      load_scene: true,
      output: {
        folder: outputFolder,
        version: null,
        format: fmt,
        depth_index: 0,
        save_alpha: false,
        save_render_elements: false,
      },
      render: {
        override_settings: true,
        resolution: preset.resolution,
        pass_limit: preset.pass_limit,
        noise_limit: preset.noise_limit,
        use_variations: true,
        fallback_camera_mode: "all",
      },
      ocio: { override: false, mode: "display_view", display: "", view: "", target_space: "" },
      variation_override: variationOverride,
    };

    // Store job in local DB
    db.prepare(
      `INSERT INTO jobs (id, api_key_hash, template_id, status, output_folder, job_payload)
       VALUES (?, ?, ?, 'submitting', ?, ?)`
    ).run(jobId, req.apiKeyHash, template_id, outputFolder, JSON.stringify(jobPayload));

    // Submit to render server asynchronously
    submitToRenderServer(config.renderServerUrl, jobPayload)
      .then((result) => {
        db.prepare(
          `UPDATE jobs SET status = 'queued', render_job_id = ?, request_id = ? WHERE id = ?`
        ).run(
          result.job_ids ? result.job_ids[0] : null,
          result.request_id || jobId,
          jobId
        );
      })
      .catch((err) => {
        db.prepare(`UPDATE jobs SET status = 'failed', detail = ? WHERE id = ?`).run(
          String(err),
          jobId
        );
      });

    incrementUsage(db, req.apiKeyHash);

    res.status(202).json({
      job_id: jobId,
      status: "submitting",
      message: "Job is being submitted to the render server",
    });
  });

  // GET /api/jobs/:id — job status
  router.get("/:id", async (req, res) => {
    const job = db.prepare("SELECT * FROM jobs WHERE id = ?").get(req.params.id);
    if (!job) return res.status(404).json({ error: "Job not found" });

    // Only show jobs belonging to this API key
    if (job.api_key_hash !== req.apiKeyHash) {
      return res.status(404).json({ error: "Job not found" });
    }

    // If still in-flight, poll the render server for updates
    if (
      job.render_job_id &&
      job.status !== "done" &&
      job.status !== "failed"
    ) {
      try {
        const serverStatus = await pollRenderServer(
          config.renderServerUrl,
          job.render_job_id
        );
        if (serverStatus && serverStatus.status) {
          const newStatus = serverStatus.status;
          const detail = serverStatus.detail || "";
          db.prepare("UPDATE jobs SET status = ?, detail = ? WHERE id = ?").run(
            newStatus,
            detail,
            job.id
          );
          if (newStatus === "done" || newStatus === "failed") {
            db.prepare(
              "UPDATE jobs SET completed_at = datetime('now') WHERE id = ?"
            ).run(job.id);
          }
          job.status = newStatus;
          job.detail = detail;
        }
      } catch {
        // Render server unreachable — return last known status
      }
    }

    res.json({
      job_id: job.id,
      template_id: job.template_id,
      status: job.status,
      detail: job.detail,
      submitted_at: job.submitted_at,
      completed_at: job.completed_at,
    });
  });

  // GET /api/jobs/:id/outputs — list rendered images
  router.get("/:id/outputs", (req, res) => {
    const job = db.prepare("SELECT * FROM jobs WHERE id = ?").get(req.params.id);
    if (!job || job.api_key_hash !== req.apiKeyHash) {
      return res.status(404).json({ error: "Job not found" });
    }

    const outputDir = job.output_folder;
    if (!outputDir || !fs.existsSync(outputDir)) {
      return res.json({ files: [] });
    }

    const imageExts = new Set([".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr"]);
    const files = fs
      .readdirSync(outputDir)
      .filter((f) => imageExts.has(path.extname(f).toLowerCase()));

    res.json({ files });
  });

  // GET /api/jobs/:id/outputs/:file — serve a rendered image
  router.get("/:id/outputs/:file", (req, res) => {
    const job = db.prepare("SELECT * FROM jobs WHERE id = ?").get(req.params.id);
    if (!job || job.api_key_hash !== req.apiKeyHash) {
      return res.status(404).json({ error: "Job not found" });
    }

    const safeFile = path.basename(req.params.file);
    const filePath = path.join(job.output_folder, safeFile);
    if (!fs.existsSync(filePath)) {
      return res.status(404).json({ error: "File not found" });
    }

    res.sendFile(path.resolve(filePath));
  });

  return router;
}

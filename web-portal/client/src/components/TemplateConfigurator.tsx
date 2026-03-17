import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Button from "@mui/material/Button";
import Paper from "@mui/material/Paper";
import CircularProgress from "@mui/material/CircularProgress";
import Alert from "@mui/material/Alert";
import SendIcon from "@mui/icons-material/Send";
import type { TemplateManifest } from "../types";
import { getTemplate, proxyUrl, submitJob } from "../api/client";
import SceneViewer from "./SceneViewer";
import VariationEditor from "./VariationEditor";
import RenderSettings from "./RenderSettings";

export default function TemplateConfigurator() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [manifest, setManifest] = useState<TemplateManifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Variation rows state
  const [rows, setRows] = useState<string[][]>([]);
  const [renderPreset, setRenderPreset] = useState("standard");
  const [outputFormat, setOutputFormat] = useState("jpg");

  useEffect(() => {
    if (!id) return;
    getTemplate(id)
      .then((m) => {
        setManifest(m);
        // Initialize rows from defaults
        const defaults = m.variation_schema.row_defaults;
        if (defaults && defaults.length > 0) {
          setRows(defaults.map((r) => [...r]));
        } else {
          setRows([
            m.variation_schema.headers.map(
              (h) => m.variation_schema.columns[h]?.default || ""
            ),
          ]);
        }
        // Set first available preset and format
        const presetKeys = Object.keys(m.render_presets || {});
        if (presetKeys.includes("standard")) setRenderPreset("standard");
        else if (presetKeys.length > 0) setRenderPreset(presetKeys[0]);

        if (m.output_formats && m.output_formats.length > 0) {
          setOutputFormat(m.output_formats[0]);
        }
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  const handleSubmit = useCallback(async () => {
    if (!manifest || !id) return;
    setSubmitting(true);
    setError("");
    try {
      const result = await submitJob({
        template_id: id,
        rows,
        render_preset: renderPreset,
        output_format: outputFormat,
      });
      navigate(`/job/${result.job_id}`);
    } catch (e) {
      setError(String(e));
      setSubmitting(false);
    }
  }, [manifest, id, rows, renderPreset, outputFormat, navigate]);

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh">
        <CircularProgress />
      </Box>
    );
  }

  if (!manifest) {
    return (
      <Box p={4}>
        <Alert severity="error">{error || "Template not found"}</Alert>
      </Box>
    );
  }

  return (
    <Box>
      <AppBar position="static" color="default" elevation={0}>
        <Toolbar>
          <IconButton edge="start" onClick={() => navigate("/")} sx={{ mr: 1 }}>
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            {manifest.display_name}
          </Typography>
          <Button
            variant="contained"
            startIcon={submitting ? <CircularProgress size={18} /> : <SendIcon />}
            onClick={handleSubmit}
            disabled={submitting || rows.length === 0}
          >
            {submitting ? "Submitting..." : "Submit Render"}
          </Button>
        </Toolbar>
      </AppBar>

      {error && (
        <Alert severity="error" sx={{ m: 2 }}>
          {error}
        </Alert>
      )}

      <Box
        display="grid"
        gridTemplateColumns={{ xs: "1fr", md: "1fr 1fr" }}
        gap={2}
        p={2}
        minHeight="calc(100vh - 64px)"
      >
        {/* Left: 3D Viewer */}
        <Paper
          variant="outlined"
          sx={{ overflow: "hidden", minHeight: 400, display: "flex" }}
        >
          <SceneViewer glbUrl={proxyUrl(manifest.template_id)} />
        </Paper>

        {/* Right: Configuration */}
        <Box display="flex" flexDirection="column" gap={2}>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle1" gutterBottom>
              Variations
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Configure the rows below. Each row produces a separate render with
              different settings applied.
            </Typography>
            <VariationEditor
              schema={manifest.variation_schema}
              rows={rows}
              onChange={setRows}
            />
          </Paper>

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle1" gutterBottom>
              Render Settings
            </Typography>
            <RenderSettings
              presets={manifest.render_presets}
              formats={manifest.output_formats}
              selectedPreset={renderPreset}
              selectedFormat={outputFormat}
              onPresetChange={setRenderPreset}
              onFormatChange={setOutputFormat}
            />
          </Paper>
        </Box>
      </Box>
    </Box>
  );
}

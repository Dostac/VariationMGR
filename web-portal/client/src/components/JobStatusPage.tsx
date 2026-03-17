import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Paper from "@mui/material/Paper";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import LinearProgress from "@mui/material/LinearProgress";
import Container from "@mui/material/Container";
import Button from "@mui/material/Button";
import DownloadIcon from "@mui/icons-material/Download";
import type { JobStatus } from "../types";
import { getJobStatus, getJobOutputs, outputImageUrl } from "../api/client";

const STATUS_COLORS: Record<string, "info" | "warning" | "success" | "error" | "default"> = {
  submitting: "info",
  queued: "info",
  claimed: "warning",
  running: "warning",
  done: "success",
  failed: "error",
};

const TERMINAL_STATUSES = new Set(["done", "failed"]);

export default function JobStatusPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<JobStatus | null>(null);
  const [outputs, setOutputs] = useState<string[]>([]);
  const [selectedImage, setSelectedImage] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  const fetchStatus = useCallback(async () => {
    if (!id) return;
    try {
      const status = await getJobStatus(id);
      setJob(status);

      if (TERMINAL_STATUSES.has(status.status)) {
        if (pollRef.current) clearInterval(pollRef.current);
        if (status.status === "done") {
          const { files } = await getJobOutputs(id);
          setOutputs(files);
          if (files.length > 0 && !selectedImage) setSelectedImage(files[0]);
        }
      }
    } catch {
      // Keep last known state
    }
  }, [id, selectedImage]);

  useEffect(() => {
    fetchStatus();
    pollRef.current = setInterval(fetchStatus, 5000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchStatus]);

  const isTerminal = job && TERMINAL_STATUSES.has(job.status);

  return (
    <Box>
      <AppBar position="static" color="default" elevation={0}>
        <Toolbar>
          <IconButton edge="start" onClick={() => navigate("/")} sx={{ mr: 1 }}>
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Job: {id?.slice(0, 8)}...
          </Typography>
          {job && (
            <Chip
              label={job.status}
              color={STATUS_COLORS[job.status] || "default"}
            />
          )}
        </Toolbar>
      </AppBar>

      {!isTerminal && (
        <LinearProgress />
      )}

      <Container maxWidth="lg" sx={{ py: 4 }}>
        {!job && (
          <Box display="flex" justifyContent="center" py={8}>
            <CircularProgress />
          </Box>
        )}

        {job && !isTerminal && (
          <Paper variant="outlined" sx={{ p: 4, textAlign: "center" }}>
            <CircularProgress sx={{ mb: 2 }} />
            <Typography variant="h6">Rendering in progress...</Typography>
            <Typography color="text.secondary">
              Status: {job.status}
              {job.detail && ` — ${job.detail}`}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Auto-refreshing every 5 seconds
            </Typography>
          </Paper>
        )}

        {job?.status === "failed" && (
          <Paper variant="outlined" sx={{ p: 4 }}>
            <Typography variant="h6" color="error">
              Render Failed
            </Typography>
            <Typography color="text.secondary">
              {job.detail || "An unknown error occurred"}
            </Typography>
          </Paper>
        )}

        {job?.status === "done" && (
          <Box>
            <Typography variant="h6" gutterBottom>
              Rendered Images ({outputs.length})
            </Typography>

            {/* Selected image preview */}
            {selectedImage && id && (
              <Paper
                variant="outlined"
                sx={{ mb: 3, p: 1, textAlign: "center" }}
              >
                <img
                  src={outputImageUrl(id, selectedImage)}
                  alt={selectedImage}
                  style={{
                    maxWidth: "100%",
                    maxHeight: "60vh",
                    objectFit: "contain",
                  }}
                />
                <Box
                  display="flex"
                  justifyContent="space-between"
                  alignItems="center"
                  mt={1}
                  px={1}
                >
                  <Typography variant="body2">{selectedImage}</Typography>
                  <Button
                    size="small"
                    startIcon={<DownloadIcon />}
                    href={outputImageUrl(id, selectedImage)}
                    download={selectedImage}
                  >
                    Download
                  </Button>
                </Box>
              </Paper>
            )}

            {/* Thumbnail grid */}
            <Box
              display="grid"
              gridTemplateColumns="repeat(auto-fill, minmax(180px, 1fr))"
              gap={1}
            >
              {outputs.map((file) => (
                <Paper
                  key={file}
                  variant="outlined"
                  sx={{
                    cursor: "pointer",
                    overflow: "hidden",
                    border: file === selectedImage ? 2 : 1,
                    borderColor:
                      file === selectedImage ? "primary.main" : "divider",
                  }}
                  onClick={() => setSelectedImage(file)}
                >
                  {id && (
                    <img
                      src={outputImageUrl(id, file)}
                      alt={file}
                      style={{
                        width: "100%",
                        height: 120,
                        objectFit: "cover",
                      }}
                    />
                  )}
                  <Typography
                    variant="caption"
                    sx={{ display: "block", p: 0.5, textAlign: "center" }}
                    noWrap
                  >
                    {file}
                  </Typography>
                </Paper>
              ))}
            </Box>
          </Box>
        )}
      </Container>
    </Box>
  );
}

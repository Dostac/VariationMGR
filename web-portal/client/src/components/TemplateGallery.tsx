import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import CardContent from "@mui/material/CardContent";
import CardMedia from "@mui/material/CardMedia";
import Typography from "@mui/material/Typography";
import Container from "@mui/material/Container";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Alert from "@mui/material/Alert";
import type { TemplateSummary, UsageInfo } from "../types";
import { listTemplates, getUsage, previewUrl } from "../api/client";

export default function TemplateGallery() {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [usage, setUsage] = useState<UsageInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([listTemplates(), getUsage()])
      .then(([t, u]) => {
        setTemplates(t);
        setUsage(u);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <Box>
      <AppBar position="static" color="default" elevation={0}>
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Scene Templates
          </Typography>
          {usage && (
            <Chip
              label={`${usage.remaining} renders remaining`}
              color={usage.remaining > 0 ? "primary" : "error"}
              variant="outlined"
            />
          )}
        </Toolbar>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 4 }}>
        {loading && (
          <Box display="flex" justifyContent="center" py={8}>
            <CircularProgress />
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        <Box
          display="grid"
          gridTemplateColumns="repeat(auto-fill, minmax(300px, 1fr))"
          gap={3}
        >
          {templates.map((t) => (
            <Card key={t.template_id}>
              <CardActionArea
                onClick={() => navigate(`/template/${t.template_id}`)}
              >
                {t.thumbnail && (
                  <CardMedia
                    component="img"
                    height="200"
                    image={previewUrl(t.template_id, t.thumbnail)}
                    alt={t.display_name}
                  />
                )}
                <CardContent>
                  <Typography variant="h6">{t.display_name}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {t.description}
                  </Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          ))}
        </Box>

        {!loading && templates.length === 0 && !error && (
          <Typography color="text.secondary" textAlign="center" py={8}>
            No templates available. Add template directories to the templates
            folder.
          </Typography>
        )}
      </Container>
    </Box>
  );
}

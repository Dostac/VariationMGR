import { useState } from "react";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import TextField from "@mui/material/TextField";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import Alert from "@mui/material/Alert";
import { validateKey } from "../api/client";

interface Props {
  onAuthenticated: () => void;
}

export default function ApiKeyEntry({ onAuthenticated }: Props) {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    localStorage.setItem("vb_api_key", key.trim());

    try {
      await validateKey();
      onAuthenticated();
    } catch {
      localStorage.removeItem("vb_api_key");
      setError("Invalid or expired API key");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card sx={{ maxWidth: 440, width: "100%" }}>
      <CardContent>
        <Typography variant="h5" gutterBottom>
          VariationMGR Web Portal
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Enter your API key to get started.
        </Typography>
        <form onSubmit={handleSubmit}>
          <TextField
            fullWidth
            label="API Key"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            type="password"
            autoFocus
            sx={{ mb: 2 }}
          />
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          <Button
            fullWidth
            variant="contained"
            type="submit"
            disabled={!key.trim() || loading}
          >
            {loading ? "Validating..." : "Connect"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

import { useState, useCallback } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Box from "@mui/material/Box";
import ApiKeyEntry from "./components/ApiKeyEntry";
import TemplateGallery from "./components/TemplateGallery";
import TemplateConfigurator from "./components/TemplateConfigurator";
import JobStatusPage from "./components/JobStatusPage";

export default function App() {
  const [authenticated, setAuthenticated] = useState(
    () => !!localStorage.getItem("vb_api_key")
  );

  const handleAuth = useCallback(() => setAuthenticated(true), []);

  if (!authenticated) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="100vh"
      >
        <ApiKeyEntry onAuthenticated={handleAuth} />
      </Box>
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<TemplateGallery />} />
        <Route path="/template/:id" element={<TemplateConfigurator />} />
        <Route path="/job/:id" element={<JobStatusPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

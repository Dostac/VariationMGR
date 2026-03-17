import Box from "@mui/material/Box";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import Typography from "@mui/material/Typography";
import type { RenderPreset } from "../types";

interface Props {
  presets: Record<string, RenderPreset>;
  formats: string[];
  selectedPreset: string;
  selectedFormat: string;
  onPresetChange: (preset: string) => void;
  onFormatChange: (format: string) => void;
}

export default function RenderSettings({
  presets,
  formats,
  selectedPreset,
  selectedFormat,
  onPresetChange,
  onFormatChange,
}: Props) {
  const preset = presets[selectedPreset];

  return (
    <Box display="flex" flexDirection="column" gap={2}>
      <FormControl fullWidth size="small">
        <InputLabel>Quality Preset</InputLabel>
        <Select
          value={selectedPreset}
          label="Quality Preset"
          onChange={(e) => onPresetChange(e.target.value)}
        >
          {Object.keys(presets).map((name) => (
            <MenuItem key={name} value={name}>
              {name.charAt(0).toUpperCase() + name.slice(1)}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {preset && (
        <Typography variant="caption" color="text.secondary">
          {preset.resolution}px / {preset.pass_limit} passes / noise{" "}
          {preset.noise_limit}%
        </Typography>
      )}

      <FormControl fullWidth size="small">
        <InputLabel>Output Format</InputLabel>
        <Select
          value={selectedFormat}
          label="Output Format"
          onChange={(e) => onFormatChange(e.target.value)}
        >
          {formats.map((fmt) => (
            <MenuItem key={fmt} value={fmt}>
              {fmt.toUpperCase()}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Box>
  );
}

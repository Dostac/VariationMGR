import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  cssVariables: true,
  colorSchemes: {
    dark: true,
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
  },
});

export default theme;

import { useCallback, useMemo } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import {
  DataGrid,
  type GridColDef,
  type GridRenderEditCellParams,
} from "@mui/x-data-grid";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import type { VariationSchema } from "../types";

interface Props {
  schema: VariationSchema;
  rows: string[][];
  onChange: (rows: string[][]) => void;
}

// Custom edit cell for enum columns
function EnumEditCell({
  id,
  field,
  value,
  api,
  options,
}: GridRenderEditCellParams & { options: string[] }) {
  return (
    <Select
      value={value || ""}
      onChange={(e) => api.setEditCellValue({ id, field, value: e.target.value })}
      size="small"
      fullWidth
      autoFocus
    >
      {options.map((opt) => (
        <MenuItem key={opt} value={opt}>
          {opt}
        </MenuItem>
      ))}
    </Select>
  );
}

// Custom edit cell for hex color columns
function ColorEditCell({
  id,
  field,
  value,
  api,
}: GridRenderEditCellParams) {
  return (
    <Box display="flex" alignItems="center" gap={1} px={1} width="100%">
      <input
        type="color"
        value={String(value || "#000000")}
        onChange={(e) => api.setEditCellValue({ id, field, value: e.target.value })}
        style={{ width: 32, height: 32, border: "none", cursor: "pointer" }}
      />
      <TextField
        value={value || ""}
        onChange={(e) => api.setEditCellValue({ id, field, value: e.target.value })}
        size="small"
        variant="standard"
        sx={{ flex: 1 }}
      />
    </Box>
  );
}

export default function VariationEditor({ schema, rows, onChange }: Props) {
  const { headers, columns, max_rows, row_defaults } = schema;

  // Convert rows to DataGrid format
  const gridRows = useMemo(
    () =>
      rows.map((row, idx) => {
        const obj: Record<string, string | number> = { id: idx };
        headers.forEach((h, ci) => {
          obj[h] = row[ci] || "";
        });
        return obj;
      }),
    [rows, headers]
  );

  const gridColumns: GridColDef[] = useMemo(() => {
    const cols: GridColDef[] = headers.map((h) => {
      const colDef = columns[h];
      const base: GridColDef = {
        field: h,
        headerName: colDef?.label || h,
        flex: 1,
        minWidth: 120,
        editable: true,
      };

      if (colDef?.type === "enum" && colDef.options) {
        const opts = colDef.options;
        base.renderEditCell = (params) => (
          <EnumEditCell {...params} options={opts} />
        );
      } else if (colDef?.type === "hex_color") {
        base.renderCell = (params) => (
          <Box display="flex" alignItems="center" gap={1}>
            <Box
              sx={{
                width: 20,
                height: 20,
                borderRadius: 1,
                bgcolor: String(params.value),
                border: "1px solid",
                borderColor: "divider",
              }}
            />
            {String(params.value)}
          </Box>
        );
        base.renderEditCell = (params) => <ColorEditCell {...params} />;
      }

      return base;
    });

    // Delete row button column
    cols.push({
      field: "_actions",
      headerName: "",
      width: 50,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params) => (
        <IconButton
          size="small"
          onClick={() => {
            const newRows = rows.filter((_, i) => i !== params.row.id);
            onChange(newRows.length > 0 ? newRows : [createDefaultRow()]);
          }}
          disabled={rows.length <= 1}
        >
          <DeleteIcon fontSize="small" />
        </IconButton>
      ),
    });

    return cols;
  }, [headers, columns, rows, onChange]);

  function createDefaultRow(): string[] {
    if (row_defaults && row_defaults.length > 0) {
      return [...row_defaults[0]];
    }
    return headers.map((h) => columns[h]?.default || "");
  }

  const handleAddRow = useCallback(() => {
    if (rows.length >= max_rows) return;
    onChange([...rows, createDefaultRow()]);
  }, [rows, max_rows, onChange]);

  const handleCellEdit = useCallback(
    (newRow: Record<string, unknown>) => {
      const idx = newRow.id as number;
      const updated = rows.map((row, i) => {
        if (i !== idx) return row;
        return headers.map((h) => String(newRow[h] ?? row[headers.indexOf(h)] ?? ""));
      });
      onChange(updated);
      return newRow;
    },
    [rows, headers, onChange]
  );

  return (
    <Box>
      <DataGrid
        rows={gridRows}
        columns={gridColumns}
        processRowUpdate={handleCellEdit}
        autoHeight
        disableRowSelectionOnClick
        hideFooter={rows.length <= 20}
        sx={{ mb: 1 }}
      />
      <Button
        startIcon={<AddIcon />}
        onClick={handleAddRow}
        disabled={rows.length >= max_rows}
        size="small"
      >
        Add Row ({rows.length}/{max_rows})
      </Button>
    </Box>
  );
}

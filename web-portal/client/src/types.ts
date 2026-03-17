// Template manifest types (mirrors template.json)

export interface ColumnDef {
  type: "enum" | "hex_color" | "text" | "number";
  label: string;
  description?: string;
  default?: string;
  options?: string[]; // for enum
  min?: number; // for number
  max?: number; // for number
}

export interface OperatorEntry {
  class_name: string;
  settings: Record<string, unknown>;
  ops_folder?: string;
}

export interface VariationSchema {
  scheme: string;
  render_camera_mode: "active" | "all" | "column";
  render_camera_column: string;
  ops_folder: string;
  headers: string[];
  columns: Record<string, ColumnDef>;
  operators: OperatorEntry[];
  row_defaults: string[][];
  max_rows: number;
}

export interface RenderPreset {
  resolution: number;
  pass_limit: number;
  noise_limit: number;
}

export interface TemplateManifest {
  template_id: string;
  display_name: string;
  description: string;
  scene_file: string;
  proxy_gltf: string;
  preview_images: string[];
  variation_schema: VariationSchema;
  render_presets: Record<string, RenderPreset>;
  output_formats: string[];
}

export interface TemplateSummary {
  template_id: string;
  display_name: string;
  description: string;
  thumbnail: string | null;
}

export interface JobStatus {
  job_id: string;
  template_id: string;
  status: string;
  detail: string;
  submitted_at: string;
  completed_at: string | null;
}

export interface UsageInfo {
  client_name: string;
  monthly_limit: number;
  renders_used: number;
  remaining: number;
  expires_at: string | null;
}

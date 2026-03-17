# VariationMGR Web Portal

Web interface for clients to browse 3ds Max template scenes, configure variations, and submit render jobs to the VariationMGR render farm.

## Architecture

```
Client (React + MUI + R3F)  -->  Server (Node.js/Express)  -->  Render Server (Python, LAN)
       |                              |                               |
   API key auth              SQLite (keys, jobs)              Existing server.py
   3D proxy viewer           Template manifests               Workers + 3dsmaxbatch
   Variation editor          Job validation                   batchrenderer_core.py
   Job status polling        Render output serving
```

## Quick Start

### 1. Server

```bash
cd server
npm install
node src/seed.js     # Creates a dev API key — save the output
npm run dev          # Starts on port 3001
```

### 2. Client

```bash
cd client
npm install
npm run dev          # Starts on port 5173, proxies /api to :3001
```

### 3. Configure

Environment variables for the server:

| Variable | Default | Description |
|---|---|---|
| `PORT` | `3001` | Server port |
| `CORS_ORIGIN` | `http://localhost:5173` | Allowed CORS origin |
| `TEMPLATES_DIR` | `../templates` | Path to template directories |
| `RENDER_SERVER_URL` | `http://localhost:8765` | URL of the VariationMGR render server |
| `RENDERS_OUTPUT_BASE` | `../renders` | Base path for render output folders |
| `DB_PATH` | `./portal.db` | SQLite database file path |

## Creating Templates

Each template is a directory under `TEMPLATES_DIR`:

```
templates/
└── my-scene/
    ├── template.json    ← Manifest (required)
    ├── proxy.glb        ← Hand-modeled glTF proxy for web viewer
    └── previews/
        └── thumb.jpg    ← Gallery thumbnail
```

### template.json

See `templates/example-room/template.json` for a complete example.

Key sections:
- **scene_file**: Path to the `.max` file on the NAS (accessible to render workers)
- **variation_schema.headers**: CSV column names
- **variation_schema.columns**: Metadata for each column (type, options, defaults)
- **variation_schema.operators**: Locked operator configurations (copied from the scene's VariationManagerData)
- **render_presets**: Named quality tiers (draft/standard/high)

### Column types

| Type | Web control | Example |
|---|---|---|
| `enum` | Dropdown | `{"type": "enum", "options": ["Oak", "Walnut"]}` |
| `hex_color` | Color picker | `{"type": "hex_color", "default": "#FFFFFF"}` |
| `text` | Text input | `{"type": "text"}` |
| `number` | Number input | `{"type": "number", "min": 0, "max": 100}` |

## Changes to Existing Codebase

Two minimal changes were made to the VariationMGR Python codebase:

1. **`NetworkRender/shared/job_schema.py`**: Added `variation_override` field (optional dict, defaults to `None`)
2. **`batchrenderer_core.py`**: If `variation_override` is present in a job, use it instead of reading VariationManagerData from the `.max` file's custom properties

These changes are fully backward-compatible. Existing jobs without `variation_override` work identically.

## API Key Management

```bash
# Create a new API key
cd server
node src/seed.js
```

Keys are stored hashed in SQLite. The plaintext key is shown once at creation. Each key has a monthly render limit that resets automatically.

## Production Deployment

1. Build the client: `cd client && npm run build`
2. Serve the built files from the server or a reverse proxy (Caddy/nginx)
3. Set up TLS termination at the reverse proxy level
4. Point `RENDER_SERVER_URL` to the LAN render server
5. Point `TEMPLATES_DIR` and `RENDERS_OUTPUT_BASE` to NAS paths accessible from the server

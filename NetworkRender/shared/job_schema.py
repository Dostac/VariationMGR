import copy
import json
import os


JOB_SCHEMA_VERSION = 1


_DEFAULT_JOB_REQUEST = {
    "schema_version": JOB_SCHEMA_VERSION,
    "request_id": "",           # the submission (1 UI submit -> many scene jobs)
    "job_id": "",               # one scene job = one render; tags this job's
                                # lines in the folder's shared batchrender.log.
                                # Worker stamps it for server jobs; empty for
                                # local renders (the core mints one per scene).
    "scene_file": "",
    "max_files": [],
    "load_scene": True,
    "output": {
        "folder": "",
        "version": None,
        "format": "jpg",
        "depth_index": 0,
        "save_alpha": False,
        "save_render_elements": False,
    },
    "render": {
        "override_settings": False,
        "resolution": 4000,
        "pass_limit": 75,
        "noise_limit": 6.0,
        "use_variations": True,
        "fallback_camera_mode": "all",  # "all" | "active"
    },
    "ocio": {
        "override": False,
        "mode": "display_view",  # "display_view" | "color_space"
        "display": "",
        "view": "",
        "target_space": "",
    },
    "variation_override": None,  # Optional: full VariationManagerData dict
    "csv_override": None,        # Optional: {"headers": [...], "rows": [[...], ...]}
    "render_range": None,        # Legacy: {"start": int, "end": int} (1-based inclusive).
                                 # Still accepted; new clients should send render_range_expr.
    "render_range_expr": "",     # Preferred: expression like "2,4-7,10" referring to table
                                 # row numbers (header = row 1, data starts at row 2).
                                 # Empty string = render all rows.
}


def _deep_copy(value):
    return copy.deepcopy(value)


def _norm_path(path_value):
    if not path_value:
        return ""
    return os.path.normpath(str(path_value)).replace("\\", "/")


def _bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def _int(value, default):
    try:
        return int(value)
    except Exception:
        return int(default)


def _float(value, default):
    try:
        return float(value)
    except Exception:
        return float(default)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def get_default_job_request():
    return _deep_copy(_DEFAULT_JOB_REQUEST)


def normalize_job_request(job_request):
    if job_request is None:
        job_request = {}
    if not isinstance(job_request, dict):
        raise TypeError("job_request must be a dict")

    out = get_default_job_request()

    out["schema_version"] = _int(
        job_request.get("schema_version", JOB_SCHEMA_VERSION),
        JOB_SCHEMA_VERSION,
    )
    out["request_id"] = str(job_request.get("request_id", "") or "")
    out["job_id"] = str(job_request.get("job_id", "") or "")

    scene_file = job_request.get("scene_file", job_request.get("file", ""))
    out["scene_file"] = _norm_path(scene_file)

    max_files = job_request.get("max_files", job_request.get("files", []))
    out["max_files"] = [_norm_path(p) for p in _as_list(max_files) if str(p).strip()]

    out["load_scene"] = _bool(
        job_request.get("load_scene", job_request.get("load_files", True)),
        True,
    )

    output_in = job_request.get("output", {})
    if not isinstance(output_in, dict):
        output_in = {}
    output = out["output"]
    output["folder"] = _norm_path(
        output_in.get("folder", job_request.get("output_path", output["folder"]))
    )
    version_raw = output_in.get("version", output["version"])
    version_text = str(version_raw).strip() if version_raw is not None else ""
    if not version_text or version_text.lower() == "none":
        output["version"] = None
    else:
        output["version"] = version_text
    output["format"] = str(
        output_in.get("format", output_in.get("ext", output["format"])) or "jpg"
    ).lower()
    output["depth_index"] = _int(
        output_in.get("depth_index", output_in.get("depth_idx", output["depth_index"])),
        output["depth_index"],
    )
    output["save_alpha"] = _bool(
        output_in.get("save_alpha", output_in.get("alpha", output["save_alpha"])),
        output["save_alpha"],
    )
    output["save_render_elements"] = _bool(
        output_in.get(
            "save_render_elements",
            output_in.get("save_re", output["save_render_elements"]),
        ),
        output["save_render_elements"],
    )

    render_in = job_request.get("render", {})
    if not isinstance(render_in, dict):
        render_in = {}
    render = out["render"]
    render["override_settings"] = _bool(
        render_in.get("override_settings", render["override_settings"]),
        render["override_settings"],
    )
    render["resolution"] = _int(render_in.get("resolution", render["resolution"]), render["resolution"])
    render["pass_limit"] = _int(render_in.get("pass_limit", render["pass_limit"]), render["pass_limit"])
    render["noise_limit"] = _float(render_in.get("noise_limit", render["noise_limit"]), render["noise_limit"])
    render["use_variations"] = _bool(
        render_in.get("use_variations", render["use_variations"]),
        render["use_variations"],
    )
    fallback_mode = str(
        render_in.get("fallback_camera_mode", render_in.get("camera_mode", render["fallback_camera_mode"]))
    ).lower()
    if fallback_mode not in ("all", "active"):
        legacy_mode = render_in.get("render_mode", None)
        if legacy_mode is not None:
            fallback_mode = "all" if _int(legacy_mode, 0) == 0 else "active"
        else:
            fallback_mode = "all"
    render["fallback_camera_mode"] = fallback_mode

    ocio_in = job_request.get("ocio", {})
    if not isinstance(ocio_in, dict):
        ocio_in = {}
    ocio = out["ocio"]
    ocio["override"] = _bool(ocio_in.get("override", ocio["override"]), ocio["override"])
    ocio_mode = ocio_in.get("mode", ocio["mode"])
    if isinstance(ocio_mode, int):
        ocio_mode = "display_view" if ocio_mode == 0 else "color_space"
    ocio_mode = str(ocio_mode).lower().strip()
    if ocio_mode not in ("display_view", "color_space"):
        ocio_mode = "display_view"
    ocio["mode"] = ocio_mode
    ocio["display"] = str(ocio_in.get("display", ocio["display"]) or "")
    ocio["view"] = str(ocio_in.get("view", ocio["view"]) or "")
    ocio["target_space"] = str(ocio_in.get("target_space", ocio["target_space"]) or "")

    vo = job_request.get("variation_override", None)
    out["variation_override"] = vo if isinstance(vo, dict) else None

    csv_ovr = job_request.get("csv_override", None)
    if isinstance(csv_ovr, dict):
        h = csv_ovr.get("headers")
        r = csv_ovr.get("rows")
        if isinstance(h, list) and isinstance(r, list):
            out["csv_override"] = {"headers": list(h), "rows": list(r)}

    rr = job_request.get("render_range", None)
    if isinstance(rr, dict):
        rr_start = _int(rr.get("start", 0), 0)
        rr_end = _int(rr.get("end", 0), 0)
        if rr_start > 0 or rr_end > 0:
            out["render_range"] = {"start": rr_start, "end": rr_end}

    expr = job_request.get("render_range_expr", "")
    if isinstance(expr, str) and expr.strip():
        out["render_range_expr"] = expr.strip()

    if output["format"] not in ("jpg", "png", "tif", "exr"):
        output["format"] = "jpg"
    if output["depth_index"] < 0:
        output["depth_index"] = 0
    return out


def job_request_to_json(job_request, pretty=False):
    normalized = normalize_job_request(job_request)
    if pretty:
        return json.dumps(normalized, indent=2)
    return json.dumps(normalized, separators=(",", ":"))


def job_request_from_json(json_payload):
    if not isinstance(json_payload, str):
        raise TypeError("json_payload must be a JSON string")
    return normalize_job_request(json.loads(json_payload))


def build_scene_jobs(job_request, already_normalized=False):
    normalized = job_request if already_normalized else normalize_job_request(job_request)

    if normalized["max_files"]:
        jobs = []
        for scene_file in normalized["max_files"]:
            scene_job = _deep_copy(normalized)
            scene_job["scene_file"] = scene_file
            scene_job["max_files"] = []
            scene_job["load_scene"] = True
            scene_job["job_id"] = ""  # fresh id per scene; core mints it
            jobs.append(scene_job)
        return jobs

    if normalized["scene_file"] or not normalized["load_scene"]:
        scene_job = _deep_copy(normalized)
        scene_job["max_files"] = []
        return [scene_job]

    return []

import argparse
import json
import os
import sys
from pathlib import Path


if __package__ is None or __package__ == "":
    # Allow direct execution: python NetworkRender/worker/networkrender.py
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

import batchrenderer_core as brcore
from NetworkRender.shared import job_schema as schema


def _log(msg):
    print(msg)


def _load_job_payload(args):
    if args.job_json:
        with open(args.job_json, "r", encoding="utf-8") as f:
            return json.load(f)

    if args.job_json_inline:
        return json.loads(args.job_json_inline)

    env_path = os.environ.get("VB_JOB_JSON_PATH", "").strip()
    if env_path:
        with open(env_path, "r", encoding="utf-8") as f:
            return json.load(f)

    env_inline = os.environ.get("VB_JOB_JSON", "").strip()
    if env_inline:
        return json.loads(env_inline)

    raise RuntimeError(
        "No job payload provided. Use --job-json or --job-json-inline "
        "(or env VB_JOB_JSON_PATH / VB_JOB_JSON)."
    )


def _coerce_single_scene_job(job_request_or_scene_job):
    normalized = schema.normalize_job_request(job_request_or_scene_job)
    scene_jobs = schema.build_scene_jobs(normalized, already_normalized=True)
    if len(scene_jobs) == 0:
        raise RuntimeError("Job has no scene_file/max_files to render.")
    if len(scene_jobs) > 1:
        raise RuntimeError(
            f"networkrender.py expects one scene job, got {len(scene_jobs)}."
        )
    return scene_jobs[0]


def _write_json(path, payload):
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def run(job_payload, result_json=""):
    if not brcore.has_max_runtime():
        raise RuntimeError(
            "3ds Max runtime unavailable. networkrender.py must run inside "
            "3ds Max Python/3dsmaxbatch."
        )

    scene_job = _coerce_single_scene_job(job_payload)
    renderer = brcore.BatchRendererCore(log_cb=_log)
    result = renderer.render_scene_job(scene_job)
    _write_json(result_json, result)

    status = result.get("status", "failed")
    if status in ("success", "skipped"):
        return 0, result
    return 1, result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Execute one batch render scene job in headless 3ds Max."
    )
    parser.add_argument(
        "--job-json",
        default="",
        help="Path to job JSON file (single scene job or request with one file).",
    )
    parser.add_argument(
        "--job-json-inline",
        default="",
        help="Inline job JSON string.",
    )
    parser.add_argument(
        "--result-json",
        default="",
        help="Optional output path for result JSON.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        payload = _load_job_payload(args)
        result_json = args.result_json or os.environ.get("VB_RESULT_JSON_PATH", "").strip()
        code, result = run(payload, result_json=result_json)
        _log(f"networkrender result: {result.get('status', 'unknown')}")
        return code
    except Exception as exc:
        _log(f"networkrender error: {exc}")
        result_json = args.result_json or os.environ.get("VB_RESULT_JSON_PATH", "").strip()
        if result_json:
            _write_json(result_json, {"status": "failed", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

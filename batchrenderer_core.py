import os
import json
import uuid
import datetime
import importlib.util
import job_schema as schema
import variation_core as vcore
import render_logger

try:
    from PySide6 import QtCore
except Exception:
    QtCore = None

try:
    import pymxs
    rt = pymxs.runtime
except Exception:
    pymxs = None
    rt = None


JOB_SCHEMA_VERSION = schema.JOB_SCHEMA_VERSION


# These functions are kept in MXS because parts of renderer/viewport access
# are unreliable when called directly through pymxs.
_MXS = r"""
fn getCoronaCamsInScene = (
    local cams = for obj in objects where isKindOf obj CoronaCam collect obj
    cams
)

fn getRenderCamera = (
    local foundCam = undefined
    local originalView = ViewPanelManager.GetActiveViewPanelIndex()
    -- Fast path: current panel (common case, no panel switching needed)
    if rendViewIndex != undefined do
        foundCam = viewport.getCamera index:rendViewIndex
    -- Fallback: scan docked panels only.
    -- Floating panels are named "Floating Viewport - N"; calling SetActiveViewPanel on them
    -- causes them to pop open, so skip them by name before switching.
    if foundCam == undefined do (
        for i = 1 to ViewPanelManager.GetViewPanelCount() do (
            if not (matchPattern (ViewPanelManager.GetViewPanelName i) pattern:"Floating Viewport*") do (
                ViewPanelManager.SetActiveViewPanel i
                if rendViewIndex != undefined do (
                    foundCam = viewport.getCamera index:rendViewIndex
                    if foundCam != undefined do exit
                )
            )
        )
    )
    if originalView != undefined do ViewPanelManager.SetActiveViewPanel originalView
    foundCam
)

fn applyCameraResolution cam targetLongest = (
    local aspectRatio = rendImageAspectRatio as float
    local camResMod = undefined
    for mod in cam.modifiers where mod.name == "Camera Resolution Mod" do (
        camResMod = mod
        exit
    )
    if camResMod != undefined do aspectRatio = camResMod.ratio
    local newWidth, newHeight
    if aspectRatio >= 1 then (
        newWidth  = targetLongest
        newHeight = targetLongest / aspectRatio
    ) else (
        newHeight = targetLongest
        newWidth  = targetLongest * aspectRatio
    )
    renderWidth  = newWidth
    renderHeight = newHeight
)

fn setPassLimit value    = ( try ( renderers.current.progressive_passLimit  = value ) catch () )
fn setAdaptivity value   = ( try ( renderers.current.adaptivity_targetError = value ) catch () )

fn setupRenderElements enableRE outDir baseName camName ext = (
    local mgr = maxOps.GetCurRenderElementMgr()
    if mgr == undefined then return()
    mgr.SetElementsActive enableRE
    if enableRE == false then return()
    local reDir = outDir + "\\RenderElements"
    if not (doesFileExist reDir) do makeDir reDir
    for i = 0 to (mgr.numRenderElements() - 1) do (
        local el = mgr.getRenderElement i
        local safeEl = substituteString el.elementname ":" "_"
        local safeCam = substituteString camName ":" "_"
        local filename = baseName + "_" + safeCam + "_" + safeEl + "." + ext
        mgr.SetRenderElementFilename i (reDir + "\\" + filename)
    )
)

fn getSceneOcioSettings = (
    local cpm = ColorPipelineMgr
    if cpm == undefined do return #("Error", "", "", "")
    local cs = "", disp = "", view = ""
    local type = cpm.GetDefaultOutputConversion colorSpace:&cs display:&disp viewTransform:&view
    return #(type as string, cs, disp, view)
)

fn applyBitmapIOSettings fmt depthIdx useAlpha = (
    if fmt == "jpg" then (
        try ( jpeg.setQuality 100; jpeg.setSmoothing 0 ) catch()
    ) else if fmt == "png" then (
        try (
            if depthIdx == 0 then pngio.setType #true24 else pngio.setType #true48
            pngio.setAlpha useAlpha
        ) catch()
    ) else if fmt == "tif" then (
        try (
            if depthIdx == 0 then tif.setType #color else tif.setType #color16
            if useAlpha then tif.setAlpha #true else tif.setAlpha #false
            tif.setCompression #none
        ) catch()
    ) else if fmt == "exr" then (
        try (
            fopenexr.setDefaults()
            if depthIdx == 0 then fopenexr.setLayerOutputFormat 0 1
            else if depthIdx == 1 then fopenexr.setLayerOutputFormat 0 0
            else fopenexr.setLayerOutputFormat 0 2
            if useAlpha then fopenexr.setLayerOutputType 0 0 else fopenexr.setLayerOutputType 0 1
        ) catch()
    )
)
"""

if rt is not None:
    rt.execute(_MXS)


def _resolve_name(
    pattern,
    row_data,
    scene_name="Scene",
    camera_name="Cam",
    date_str="Date",
    row_index=0,
):
    result = (
        pattern.replace("{Scene}", scene_name)
        .replace("{Camera}", camera_name)
        .replace("{Date}", date_str)
        .replace("{Row}", str(row_index + 2))
    )
    for key, value in row_data.items():
        result = result.replace(f"[{key}]", str(value))
    return result


def has_max_runtime():
    return rt is not None


def get_default_job_request():
    return schema.get_default_job_request()


def normalize_job_request(job_request):
    return schema.normalize_job_request(job_request)


def job_request_to_json(job_request, pretty=False):
    return schema.job_request_to_json(job_request, pretty=pretty)


def job_request_from_json(json_payload):
    return schema.job_request_from_json(json_payload)


def build_scene_jobs(job_request):
    return schema.build_scene_jobs(job_request)


class BatchRendererCore:
    def __init__(self, log_cb=None):
        self.log_cb = log_cb
        self._rlog = None  # active RenderLog during a scene job, else None

    @staticmethod
    def _ensure_runtime():
        if rt is None:
            raise RuntimeError(
                "3ds Max runtime unavailable. Render execution requires pymxs "
                "inside 3ds Max or 3dsmaxbatch."
            )

    def set_logger(self, log_cb):
        self.log_cb = log_cb

    def log(self, msg):
        # During a scene job, route through the job's log so it lands in the
        # output-folder file and is mirrored live to log_cb. Outside a job
        # (setup, pre-render errors) there is no file yet -- go straight to
        # the callback / stdout.
        if self._rlog is not None:
            self._rlog.write(msg)
        elif callable(self.log_cb):
            self.log_cb(msg)
        else:
            print(msg)

    def _apply_ocio(self, ocio_cfg):
        self._ensure_runtime()
        if not ocio_cfg.get("override", False):
            return

        cpm = rt.ColorPipelineMgr
        if not cpm:
            return

        try:
            if ocio_cfg.get("mode", "display_view") == "display_view":
                cpm.SetDefaultOutputConversion(
                    rt.Name("DisplayViewtransform"),
                    display=ocio_cfg.get("display", ""),
                    viewTransform=ocio_cfg.get("view", ""),
                )
                self.log(
                    "Applied Output Transform: "
                    f"{ocio_cfg.get('view', '')}"
                )
            else:
                cpm.SetDefaultOutputConversion(
                    rt.Name("ColorSpaceConversion"),
                    colorSpace=ocio_cfg.get("target_space", ""),
                )
                self.log(
                    "Applied Color Conversion: "
                    f"{ocio_cfg.get('target_space', '')}"
                )
        except Exception as exc:
            self.log(f"OCIO Apply Error: {exc}")

    def _load_operators(self, variation_data):
        self._ensure_runtime()
        loaded = []
        operators_data = variation_data.get("operators", [])
        if not operators_data:
            return loaded

        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            import inspect

            script_dir = os.path.dirname(
                os.path.abspath(inspect.getfile(inspect.currentframe()))
            )

        ini_ops_folder = ""
        if QtCore is not None:
            vm_ini = os.path.join(
                str(rt.getDir(rt.Name("userScripts"))),
                "VariationManager.ini",
            )
            try:
                ini_ops_folder = (
                    QtCore.QSettings(vm_ini, QtCore.QSettings.IniFormat)
                    .value("General/OpsFolder")
                    or ""
                )
            except Exception:
                pass

        seen = set()
        search_folders = []
        for folder in [
            variation_data.get("ops_folder", ""),
            ini_ops_folder,
            os.path.join(script_dir, "Operators"),
        ]:
            if not folder:
                continue
            norm = os.path.normpath(folder)
            if norm not in seen and os.path.isdir(norm):
                seen.add(norm)
                search_folders.append(norm)

        if not search_folders:
            self.log("  No valid operators folder found.")
            return loaded

        for op_data in operators_data:
            class_name = op_data.get("class_name", "")
            instance_id = op_data.get("instance_id", uuid.uuid4().hex[:8])
            state = op_data.get("settings", op_data.get("state", {}))
            if not class_name:
                self.log("  Operator with empty class_name: skipping.")
                continue

            cls = None
            found_in = None
            for ops_folder in search_folders:
                try:
                    for fname in os.listdir(ops_folder):
                        if not fname.endswith(".py") or fname == "__init__.py":
                            continue
                        fpath = os.path.join(ops_folder, fname)
                        mod_name = f"vb_core_op_{fname[:-3]}_{abs(hash(fpath))}"
                        spec = importlib.util.spec_from_file_location(mod_name, fpath)
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        if hasattr(module, class_name):
                            cls = getattr(module, class_name)
                            found_in = ops_folder
                            break
                    if cls is not None:
                        break
                except Exception as exc:
                    self.log(f"  Operator scan error in '{ops_folder}': {exc}")

            if cls is None:
                self.log(f"  Operator class '{class_name}' not found in: {search_folders}")
                continue

            try:
                instance = cls(context={"rt": rt, "build_ui": False, "instance_id": instance_id})
                if hasattr(instance, "deserialize"):
                    instance.deserialize(state)
                loaded.append(instance)
                self.log(f"  Loaded operator: {class_name} ({found_in})")
            except Exception as exc:
                self.log(f"  Failed to init operator '{class_name}': {exc}")

        return loaded

    def _read_variation_data(self):
        self._ensure_runtime()
        try:
            count = rt.fileProperties.getNumProperties(rt.name("custom"))
            for i in range(1, count + 1):
                if rt.fileProperties.getPropertyName(rt.name("custom"), i) == "VariationManagerData":
                    value = rt.fileProperties.getPropertyValue(rt.name("custom"), i)
                    return json.loads(value)
        except Exception as exc:
            self.log(f"VariationData read error: {exc}")
        return None

    def _do_render(self, cam, out_name, scene_job):
        self._ensure_runtime()
        output_cfg = scene_job["output"]
        render_cfg = scene_job["render"]

        safe_name = (
            out_name.replace("\r", "").replace("\n", "").replace("\t", "")
            .replace(":", "_")
            .replace("/", "_")
            .replace("\\", "_")
            .replace("*", "_")
            .replace("?", "_")
            .replace('"', "_")
            .replace("<", "_")
            .replace(">", "_")
            .replace("|", "_")
        )
        out_dir = output_cfg["folder"]
        fmt = output_cfg["format"]
        full_path = os.path.join(out_dir, f"{safe_name}.{fmt}")

        if render_cfg["override_settings"]:
            rt.applyCameraResolution(cam, render_cfg["resolution"])

        rt.setupRenderElements(
            output_cfg["save_render_elements"],
            out_dir,
            safe_name,
            cam.name if cam else "Active",
            fmt,
        )

        try:
            self.log(f"  Rendering: {safe_name}")
            rt.render(
                camera=cam,
                outputFile=full_path,
                outputHDRbitmap=True,
                outputColorConversion=rt.Name("automatic"),
                vfb=False,
            )
            self.log(f"  -> Saved: {os.path.basename(full_path)}")
            return True
        except Exception as exc:
            self.log(f"  -> Render error: {exc}")
            return False

    def render_scene_job(self, scene_job):
        self._ensure_runtime()
        scene_job = normalize_job_request(scene_job)
        output_cfg = scene_job["output"]
        render_cfg = scene_job["render"]

        scene_file = scene_job.get("scene_file", "")
        if scene_file:
            scene_file = os.path.normpath(str(scene_file)).replace("\\", "/")
            scene_job["scene_file"] = scene_file

        result = {
            "scene_file": scene_file,
            "status": "failed",
            "attempted": 0,
            "rendered": 0,
        }

        out_dir = output_cfg["folder"]
        if not out_dir:
            self.log("Error: No output folder set.")
            return result

        if not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        # Every render gets a job id. Server jobs arrive with one from the
        # worker; local / interactive renders mint one here, so the path is
        # identical either way. All jobs rendering into the same folder share
        # one "batchrender.log" there, each line tagged with its job id. The
        # core owns the file (it always runs, headless or in 3ds Max); log_cb
        # only mirrors each line live to whoever is watching.
        job_id = scene_job.get("job_id") or render_logger.make_job_id(
            os.path.splitext(os.path.basename(scene_file))[0] if scene_file else ""
        )
        scene_job["job_id"] = job_id
        result["job_id"] = job_id

        mirror = self.log_cb if callable(self.log_cb) else print
        self._rlog = render_logger.RenderLog(out_dir, job_id, mirror=mirror).open()
        scene_label = os.path.basename(scene_file) if scene_file else "(current scene)"
        self.log(f"=== Job {job_id} started: {scene_label} ===")
        try:
            result = self._run_scene_job(
                scene_job, output_cfg, render_cfg, scene_file, out_dir, result
            )
            self.log(
                f"=== Job {job_id} finished: {result['status']} "
                f"({result['rendered']}/{result['attempted']} rendered) ==="
            )
            return result
        except Exception as exc:
            self.log(f"=== Job {job_id} aborted: {exc} ===")
            raise
        finally:
            self._rlog.close()
            self._rlog = None

    def _run_scene_job(self, scene_job, output_cfg, render_cfg, scene_file, out_dir, result):
        if scene_job["load_scene"]:
            if not scene_file:
                self.log("Error: scene_file is required when load_scene=True.")
                return result
            if not os.path.exists(scene_file):
                self.log(f"Not found: {scene_file}")
                return result

            self.log(f"Opening: {os.path.basename(scene_file)}")
            try:
                rt.loadMaxFile(scene_file, useFileUnits=True, quiet=True)
            except Exception as exc:
                self.log(f"Error opening: {exc}")
                return result
        else:
            if not scene_file:
                scene_file = (rt.maxFilePath + rt.maxFileName).replace("\\", "/")
                scene_job["scene_file"] = scene_file
                result["scene_file"] = scene_file

        rt.applyBitmapIOSettings(
            output_cfg["format"],
            output_cfg["depth_index"],
            output_cfg["save_alpha"],
        )
        self._apply_ocio(scene_job["ocio"])

        if render_cfg["override_settings"]:
            rt.setPassLimit(render_cfg["pass_limit"])
            rt.setAdaptivity(render_cfg["noise_limit"])

        scene_label = scene_file if scene_file else str(rt.maxFileName)
        scene_name = os.path.splitext(os.path.basename(scene_label))[0]
        version = output_cfg.get("version")
        version_suffix = f"_{version}" if version else ""
        base_name = f"{scene_name}{version_suffix}"
        date_str = datetime.date.today().strftime("%Y%m%d")

        use_variations = render_cfg["use_variations"]
        variation_data = None
        if use_variations:
            variation_data = scene_job.get("variation_override") or self._read_variation_data()
            if scene_job.get("variation_override"):
                self.log("  Using job-supplied variation override.")

            # Apply CSV override: replaces only headers + rows
            csv_override = scene_job.get("csv_override")
            if csv_override and variation_data:
                csv_h = csv_override.get("headers")
                csv_r = csv_override.get("rows")
                if csv_h and csv_r is not None:
                    variation_data = dict(variation_data)
                    variation_data["headers"] = csv_h
                    variation_data["rows"] = csv_r
                    self.log(f"  CSV override: {len(csv_r)} rows, {len(csv_h)} columns")
            elif csv_override and not variation_data:
                csv_h = csv_override.get("headers", [])
                csv_r = csv_override.get("rows", [])
                if csv_h:
                    variation_data = {
                        "headers": csv_h, "rows": csv_r,
                        "render_camera_mode": "active",
                        "render_camera_column": "",
                        "scheme": "{Scene}_{Row}_{Camera}",
                        "operators": [],
                    }
                    self.log(f"  CSV override (no base config): {len(csv_r)} rows")

        rendered_any = False
        attempted = 0
        rendered = 0

        if variation_data:
            headers = variation_data.get("headers", [])
            rows = variation_data.get("rows", [])
            cam_mode = variation_data.get("render_camera_mode", "active")
            cam_column = variation_data.get("render_camera_column", "")
            scheme = variation_data.get("scheme", "{Scene}_{Camera}")

            self.log(f"  VariationMGR: {len(rows)} row(s), mode='{cam_mode}'")

            # Build indexed rows and apply render range.
            # Resolution order (most specific first):
            #   1. Job's render_range_expr (preferred, new format)
            #   2. Job's render_range dict (legacy)
            #   3. Scene's render_range_expr (preferred, new format)
            #   4. Scene's render_range_start/end ints (legacy)
            indexed_rows = list(enumerate(rows))
            max_row = len(rows) + 1  # table row number of last data row

            range_expr = None
            job_expr = scene_job.get("render_range_expr", "")
            if isinstance(job_expr, str) and job_expr.strip():
                range_expr = job_expr.strip()
            else:
                job_range = scene_job.get("render_range")
                if isinstance(job_range, dict):
                    jr_s = job_range.get("start", 0) or 0
                    jr_e = job_range.get("end",   0) or 0
                    if jr_s > 0 or jr_e > 0:
                        range_expr = vcore.format_row_range_expr(jr_s, jr_e)
                if range_expr is None:
                    scene_expr = variation_data.get("render_range_expr", "")
                    if isinstance(scene_expr, str) and scene_expr.strip():
                        range_expr = scene_expr.strip()
                if range_expr is None:
                    sc_s = variation_data.get("render_range_start", 0) or 0
                    sc_e = variation_data.get("render_range_end",   0) or 0
                    if sc_s > 0 or sc_e > 0:
                        range_expr = vcore.format_row_range_expr(sc_s, sc_e)

            if range_expr:
                try:
                    row_numbers = vcore.parse_row_range_expr(range_expr, max_row=max_row)
                except ValueError as e:
                    self.log(f"  Warning: bad render_range_expr '{range_expr}': {e}. Rendering all rows.")
                    row_numbers = None
                if row_numbers:
                    # row_numbers are table row numbers (1-based with header=1);
                    # subtract 2 to get the index into the data rows list.
                    wanted = {n - 2 for n in row_numbers if 2 <= n <= max_row}
                    indexed_rows = [(i, r) for i, r in indexed_rows if i in wanted]
                    self.log(
                        f"  Render range: {range_expr} "
                        f"({len(indexed_rows)} of {len(rows)})")

            operators = self._load_operators(variation_data)
            if variation_data.get("operators", []) and not operators:
                self.log("  Warning: Scene has VariationMGR operators, but none were loaded.")

            for row_idx, row_vals in indexed_rows:
                row_data = dict(zip(headers, row_vals))

                for op in operators:
                    try:
                        op.execute(row_data)
                    except Exception as exc:
                        self.log(f"  Operator error: {exc}")

                if cam_mode == "active":
                    cam = rt.getRenderCamera()
                    if cam:
                        row_cams = [
                            (
                                cam,
                                _resolve_name(
                                    scheme,
                                    row_data,
                                    scene_name=scene_name,
                                    camera_name=cam.name,
                                    date_str=date_str,
                                    row_index=row_idx,
                                ),
                            )
                        ]
                    else:
                        self.log("  Warning: No active camera found.")
                        row_cams = []
                elif cam_mode == "column":
                    cam_name = str(row_data.get(cam_column, "")).strip()
                    cam = rt.getNodeByName(cam_name) if cam_name else None
                    if cam:
                        row_cams = [
                            (
                                cam,
                                _resolve_name(
                                    scheme,
                                    row_data,
                                    scene_name=scene_name,
                                    camera_name=cam.name,
                                    date_str=date_str,
                                    row_index=row_idx,
                                ),
                            )
                        ]
                    else:
                        self.log(f"  Warning: Camera '{cam_name}' not found.")
                        row_cams = []
                else:  # "all"
                    row_cams = [
                        (
                            cam,
                            _resolve_name(
                                scheme,
                                row_data,
                                scene_name=scene_name,
                                camera_name=cam.name,
                                date_str=date_str,
                                row_index=row_idx,
                            ),
                        )
                        for cam in list(rt.getCoronaCamsInScene())
                    ]

                for cam, out_name in row_cams:
                    attempted += 1
                    if self._do_render(cam, out_name, scene_job):
                        rendered += 1
                        rendered_any = True

            if not rendered_any:
                self.log("  No render jobs - skipping file.")
        else:
            if use_variations:
                self.log("  No VariationMGR data in scene - rendering without variations.")

            jobs = []
            if render_cfg["fallback_camera_mode"] == "all":
                for cam in list(rt.getCoronaCamsInScene()):
                    jobs.append((cam, f"{base_name}_{cam.name}"))
            else:
                cam = rt.getRenderCamera()
                if cam:
                    jobs.append((cam, base_name))
                else:
                    self.log("  Warning: No active camera found.")

            if not jobs:
                self.log("  No render jobs - skipping file.")
            else:
                for cam, out_name in jobs:
                    attempted += 1
                    if self._do_render(cam, out_name, scene_job):
                        rendered += 1
                        rendered_any = True

        result["attempted"] = attempted
        result["rendered"] = rendered
        result["status"] = "success" if rendered_any else "skipped"
        return result

    def render_job_request(
        self,
        job_request,
        should_cancel=None,
        on_scene_start=None,
    ):
        normalized = normalize_job_request(job_request)
        scene_jobs = build_scene_jobs(normalized)

        if not scene_jobs:
            self.log("Error: Job request has no scene_file/max_files.")
            return {
                "status": "failed",
                "total_scenes": 0,
                "completed_scenes": 0,
                "results": [],
            }

        results = []
        completed = 0
        aborted = False

        for index, scene_job in enumerate(scene_jobs, start=1):
            if callable(should_cancel) and should_cancel():
                aborted = True
                self.log("Aborted.")
                break

            if callable(on_scene_start):
                try:
                    on_scene_start(scene_job, index, len(scene_jobs))
                except Exception:
                    pass

            results.append(self.render_scene_job(scene_job))
            completed += 1

        return {
            "status": "aborted" if aborted else "complete",
            "total_scenes": len(scene_jobs),
            "completed_scenes": completed,
            "results": results,
        }

    # Alias for simpler call sites
    render_job = render_job_request


def run_json_job(json_payload, log_cb=None):
    request = job_request_from_json(json_payload)
    return BatchRendererCore(log_cb=log_cb).render_job_request(request)

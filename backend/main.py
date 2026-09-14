"""ClipVideo API — streaming upload, validated FFmpeg jobs, and stable downloads."""
import json
import logging
import math
import os
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage"))).resolve()
UPLOAD_DIR, CLIP_DIR, ARCHIVE_DIR, TEMP_DIR = (STORAGE_DIR / "uploads", STORAGE_DIR / "clips", STORAGE_DIR / "archives", STORAGE_DIR / "temp")
MAX_UPLOAD_SIZE_GB = int(os.getenv("MAX_UPLOAD_SIZE_GB", "10"))
MAX_UPLOAD_SIZE, RETENTION_HOURS, CHUNK_SIZE, MAX_CLIPS = MAX_UPLOAD_SIZE_GB * 1024**3, int(os.getenv("JOB_RETENTION_HOURS", "24")), 4 * 1024 * 1024, 10_000
FAST_COPY_WORKERS = max(1, min(int(os.getenv("FAST_COPY_WORKERS", "50")), 50))
TRANSCODE_WORKERS = max(1, min(int(os.getenv("TRANSCODE_WORKERS", "50")), 50))
TRANSCODE_PRESET = os.getenv("TRANSCODE_PRESET", "superfast").lower()
if TRANSCODE_PRESET not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"}: TRANSCODE_PRESET = "superfast"
TRANSCODE_STRATEGY = os.getenv("TRANSCODE_STRATEGY", "parallel").lower()
if TRANSCODE_STRATEGY not in {"parallel", "singlepass"}: TRANSCODE_STRATEGY = "parallel"
VIDEO_ENCODER = os.getenv("VIDEO_ENCODER", "auto").lower()
if VIDEO_ENCODER not in {"auto", "libx264", "h264_qsv", "h264_nvenc", "h264_amf"}: VIDEO_ENCODER = "auto"
for directory in (UPLOAD_DIR, CLIP_DIR, ARCHIVE_DIR, TEMP_DIR): directory.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("clipvideo")

INPUT_FORMATS = {".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo", ".webm": "video/webm", ".m4v": "video/x-m4v", ".mpeg": "video/mpeg", ".mpg": "video/mpeg"}
# The backend owns this format schema; the client reads it from /api/v1/config.
OUTPUT_FORMATS = {"mp4": {"extension": ".mp4", "mime": "video/mp4", "video_codec": "libx264", "audio_codec": "aac"}}
FRAME_PRESETS = {"original": None, "instagram_reel": (1080, 1920, "9:16"), "youtube_shorts": (1080, 1920, "9:16"), "tiktok": (1080, 1920, "9:16"), "instagram_post": (1080, 1080, "1:1"), "instagram_portrait": (1080, 1350, "4:5"), "youtube_landscape": (1920, 1080, "16:9")}

app = FastAPI(title="ClipVideo API", version="6.0.0")
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,https://clipvideo.site.je,https://www.clipvideo.site.je,http://clipvideo.site.je,http://www.clipvideo.site.je"
origins = [item.strip() for item in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if item.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Authorization"])
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()

def api_error(code: str, message: str, status: int = 400) -> HTTPException: return HTTPException(status, {"error": code, "message": message})
@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException): return JSONResponse(status_code=exc.status_code, content=exc.detail if isinstance(exc.detail, dict) else {"error": "REQUEST_ERROR", "message": str(exc.detail)})
@app.exception_handler(RequestValidationError)
async def request_error(_: Request, exc: RequestValidationError): return JSONResponse(status_code=422, content={"error": "INVALID_REQUEST", "message": "The upload request contains missing or invalid fields.", "fields": [".".join(map(str, error["loc"])) for error in exc.errors()]})
def binary(name: str) -> str:
    path = shutil.which(name)
    if not path: raise RuntimeError(f"{name} is not installed or unavailable on PATH.")
    return path
def available_encoders() -> set[str]:
    result = subprocess.run([binary("ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True, check=False)
    return {line.split()[1] for line in result.stdout.splitlines() if len(line.split()) > 1 and line.split()[1] in {"h264_qsv", "h264_nvenc", "h264_amf"}}
def preferred_encoder() -> str:
    available = available_encoders()
    if VIDEO_ENCODER != "auto": return VIDEO_ENCODER if VIDEO_ENCODER in available or VIDEO_ENCODER == "libx264" else "libx264"
    # Prefer detected hardware encoders. Failed hardware initialization is handled
    # by a safe libx264 retry below.
    return next((name for name in ("h264_qsv", "h264_nvenc", "h264_amf") if name in available), "libx264")
def update_job(job_id: str, **values: Any):
    with JOBS_LOCK:
        if job_id in JOBS: JOBS[job_id].update(values)
def get_job(job_id: str):
    with JOBS_LOCK: return dict(JOBS[job_id]) if job_id in JOBS else None
def clean_name(prefix: str, number: int, extension: str) -> str:
    safe = "".join(char for char in prefix if char.isalnum() or char in "_-")[:64] or "clip"
    return f"{safe}_{number:03d}{extension}"

async def stream_upload(upload: UploadFile, destination: Path) -> int:
    total = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(CHUNK_SIZE):
                total += len(chunk)
                if total > MAX_UPLOAD_SIZE: raise api_error("FILE_TOO_LARGE", f"The maximum upload size is {MAX_UPLOAD_SIZE_GB} GB.", 413)
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally: await upload.close()
    if not total: raise api_error("INVALID_FILE", "The selected file is empty. Choose a video file with content.")
    return total

def probe(path: Path) -> dict[str, Any]:
    result = subprocess.run([binary("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, check=False)
    if result.returncode:
        logger.warning("ffprobe: %s", result.stderr[-2000:]); raise RuntimeError("The uploaded file is not a readable video.")
    try:
        payload = json.loads(result.stdout); streams = payload.get("streams", []); video = next(stream for stream in streams if stream.get("codec_type") == "video"); audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        num, den = video.get("r_frame_rate", "0/1").split("/", 1); fps = float(num) / float(den) if float(den) else 0; duration = float(payload.get("format", {}).get("duration", 0))
    except (ValueError, KeyError, StopIteration, TypeError) as error: raise RuntimeError("The uploaded file does not contain a usable video stream.") from error
    if duration <= 0: raise RuntimeError("The video duration could not be determined.")
    return {"duration": duration, "width": int(video.get("width") or 0), "height": int(video.get("height") or 0), "fps": round(fps, 3), "video_codec": video.get("codec_name", "unknown"), "audio_codec": audio.get("codec_name", "none") if audio else "none"}

def parse_time(value: str) -> float:
    try:
        values = [float(part) for part in value.strip().split(":")]
        if len(values) == 1: return values[0]
        if len(values) == 2: return values[0] * 60 + values[1]
        if len(values) == 3: return values[0] * 3600 + values[1] * 60 + values[2]
    except (ValueError, AttributeError): pass
    raise ValueError("Use seconds or HH:MM:SS.")
def build_ranges(settings: dict[str, Any], duration: float) -> list[tuple[float, float]]:
    if settings["split_mode"] == "duration":
        step = settings["clip_duration"]
        ranges, epsilon = [], min(0.001, step / 100)
        for index in range(math.ceil((duration - epsilon) / step)):
            start, end = index * step, min((index + 1) * step, duration)
            if end - start > epsilon: ranges.append((start, end))
    elif settings["split_mode"] == "parts": ranges = [(duration * i / settings["number_of_parts"], duration * (i + 1) / settings["number_of_parts"]) for i in range(settings["number_of_parts"])]
    else:
        try: raw = json.loads(settings["custom_clips"])
        except json.JSONDecodeError as error: raise ValueError("Custom ranges are invalid.") from error
        if not isinstance(raw, list) or not raw: raise ValueError("Add at least one custom range.")
        ranges = []
        for index, item in enumerate(raw, 1):
            start, end = parse_time(str(item.get("start", ""))), parse_time(str(item.get("end", "")))
            if start < 0 or end <= start or start >= duration: raise ValueError(f"Range {index} must start inside the video and end after its start.")
            ranges.append((start, min(end, duration)))
    if len(ranges) > MAX_CLIPS: raise ValueError(f"This setting would create more than {MAX_CLIPS} clips.")
    return ranges
def get_frame(settings: dict[str, Any]) -> tuple[int | None, int | None]:
    preset = settings["frame_preset"]
    if preset == "original": return None, None
    if preset == "custom": return settings["frame_width"], settings["frame_height"]
    width, height, _ = FRAME_PRESETS[preset]; return width, height
def filter_for(width: int, height: int, fit: str) -> str:
    if fit == "stretch": return f"scale={width}:{height}"
    if fit == "crop": return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
def run(command: list[str]):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        logger.error("ffmpeg %s: %s", result.returncode, result.stderr[-4000:]); raise RuntimeError("FFmpeg could not generate this clip. Check that the source video and selected settings are compatible.")
def run_with_progress(command: list[str], job_id: str, duration: float, clip_duration: float, total_clips: int):
    progress_command = [*command[:-1], "-progress", "pipe:1", "-nostats", command[-1]]
    process = subprocess.Popen(progress_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stderr, last_update = "", 0.0
    try:
        for line in process.stdout or []:
            key, _, value = line.strip().partition("=")
            if key != "out_time_ms": continue
            try: seconds_done = max(0.0, int(value) / 1_000_000)
            except ValueError: continue
            now = time.time()
            if now - last_update < 1 and seconds_done < duration: continue
            last_update = now
            percent = min(100, max(0, round(seconds_done * 100 / duration))) if duration > 0 else 0
            formatted = min(total_clips, max(0, int(seconds_done / clip_duration))) if clip_duration > 0 else 0
            update_job(job_id, progress=max(1, min(90, round(percent * 0.9))), current_clip=formatted, progress_label=f"{formatted} of {total_clips} clip lengths formatted", message=f"Formatting source {percent}% complete")
        stderr = process.stderr.read() if process.stderr else ""
        returncode = process.wait()
    finally:
        if process.poll() is None: process.kill()
    if returncode:
        logger.error("ffmpeg %s: %s", returncode, stderr[-4000:]); raise RuntimeError("FFmpeg could not format the source video. Check that the source video and selected frame settings are compatible.")
def make_clip(source: Path, target: Path, start: float, end: float, settings: dict[str, Any], width: int | None, height: int | None) -> bool:
    command = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(source), "-t", str(end - start), "-map", "0:v:0?", "-map", "0:a?"]
    fast = width is None and height is None
    if fast: command += ["-c", "copy", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart"]
    else: command += ["-vf", filter_for(width, height, settings["fit_mode"]), "-c:v", "libx264", "-preset", "veryfast", "-crf", str(settings["crf"]), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
    run(command + [str(target)])
    if not target.is_file() or target.stat().st_size == 0: raise RuntimeError("FFmpeg finished without creating a usable clip.")
    return fast
def add_encoder_options(command: list[str], encoder: str, settings: dict[str, Any]) -> list[str]:
    if encoder == "h264_qsv": return command + ["-c:v", encoder, "-global_quality", str(settings["crf"])]
    if encoder == "h264_nvenc": return command + ["-c:v", encoder, "-preset", "p1", "-cq", str(settings["crf"]), "-b:v", "0"]
    if encoder == "h264_amf": return command + ["-c:v", encoder, "-quality", "speed", "-rc", "cqp", "-qp_i", str(settings["crf"]), "-qp_p", str(settings["crf"])]
    return command + ["-c:v", "libx264", "-preset", TRANSCODE_PRESET, "-crf", str(settings["crf"]), "-threads", "0"]
def audio_options(copy_audio: bool) -> list[str]:
    return ["-pix_fmt", "yuv420p", "-c:a", "copy"] if copy_audio else ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k"]
def transcode_clip_command(source: Path, target: Path, start: float, end: float, settings: dict[str, Any], width: int, height: int, encoder: str, copy_audio: bool) -> list[str]:
    command = [
        binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(source),
        "-t", str(end - start), "-map", "0:v:0?", "-map", "0:a?", "-vf", filter_for(width, height, settings["fit_mode"]),
    ]
    return add_encoder_options(command, encoder, settings) + audio_options(copy_audio) + ["-movflags", "+faststart", str(target)]
def make_transcoded_clip(source: Path, target: Path, start: float, end: float, settings: dict[str, Any], width: int, height: int, encoder: str, copy_audio: bool) -> str:
    try: run(transcode_clip_command(source, target, start, end, settings, width, height, encoder, copy_audio))
    except RuntimeError:
        if encoder == "libx264": raise
        logger.warning("Hardware encoder %s failed for %s; retrying with libx264.", encoder, target.name)
        target.unlink(missing_ok=True)
        run(transcode_clip_command(source, target, start, end, settings, width, height, "libx264", copy_audio))
        encoder = "libx264"
    if not target.is_file() or target.stat().st_size == 0: raise RuntimeError("FFmpeg finished without creating a usable clip.")
    return encoder
def transcode_command(source: Path, target: Path, settings: dict[str, Any], width: int, height: int, encoder: str, gop_frames: int | None, copy_audio: bool, faststart: bool) -> list[str]:
    command = [
        binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:v:0?", "-map", "0:a?", "-vf", filter_for(width, height, settings["fit_mode"]),
    ]
    command = add_encoder_options(command, encoder, settings)
    if gop_frames:
        command += ["-g", str(gop_frames), "-force_key_frames", f"expr:gte(t,n_forced*{settings['clip_duration']})"]
        if encoder in {"h264_qsv", "h264_amf"}: command += ["-forced_idr", "1"]
        if encoder == "h264_nvenc": command += ["-forced-idr", "1"]
    command += audio_options(copy_audio)
    if faststart: command += ["-movflags", "+faststart"]
    return command + [str(target)]
def transcode_source_once(source: Path, target: Path, settings: dict[str, Any], width: int, height: int, gop_frames: int | None, job_id: str, info: dict[str, Any], total_clips: int) -> str:
    """Format the source once; completed clips can then use lossless fast-copy cuts."""
    encoder = preferred_encoder()
    copy_audio = info.get("audio_codec") == "aac"
    try: run_with_progress(transcode_command(source, target, settings, width, height, encoder, gop_frames, copy_audio, False), job_id, info["duration"], settings["clip_duration"], total_clips)
    except RuntimeError:
        if encoder == "libx264": raise
        logger.warning("Hardware encoder %s failed; retrying with libx264.", encoder)
        target.unlink(missing_ok=True)
        update_job(job_id, message="Hardware formatting failed; retrying with CPU encoder.")
        run_with_progress(transcode_command(source, target, settings, width, height, "libx264", gop_frames, copy_audio, False), job_id, info["duration"], settings["clip_duration"], total_clips)
        encoder = "libx264"
    if not target.is_file() or target.stat().st_size == 0: raise RuntimeError("Video formatting completed without creating a usable temporary video.")
    return encoder
def segment_duration_clips(source: Path, output: Path, settings: dict[str, Any], ranges: list[tuple[float, float]]) -> list[Path]:
    """Split a formatted/keyframe-aligned source in one packet-copy FFmpeg pass."""
    prefix = "".join(char for char in settings["filename_prefix"] if char.isalnum() or char in "_-")[:64] or "clip"
    pattern = output / f"{prefix}_%03d.mp4"
    command = [
        binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:v:0?", "-map", "0:a?", "-c", "copy", "-f", "segment",
        "-segment_time", str(settings["clip_duration"]), "-segment_start_number", str(settings["number_start"]),
        "-reset_timestamps", "1", "-avoid_negative_ts", "make_zero", "-segment_format", "mp4",
        "-segment_format_options", "movflags=+faststart", str(pattern),
    ]
    run(command)
    paths = [output / clean_name(settings["filename_prefix"], settings["number_start"] + index, ".mp4") for index in range(len(ranges))]
    if any(not path.is_file() or path.stat().st_size == 0 for path in paths): raise RuntimeError("Fast segmentation did not create all expected clips.")
    return paths
def parallel_transcode_clips(source: Path, output: Path, settings: dict[str, Any], ranges: list[tuple[float, float]], width: int, height: int, info: dict[str, Any], job_id: str) -> list[dict[str, Any]]:
    encoder, copy_audio = preferred_encoder(), info.get("audio_codec") == "aac"
    update_job(job_id, total_clips=len(ranges), processing_mode=f"parallel_{encoder}_transcode", stage="Generating clips", progress_label=f"0 of {len(ranges)} clips", message=f"Transcoding clips with {TRANSCODE_WORKERS} parallel workers…")
    completed, clip_map, used_encoders = 0, {}, set()
    executor = ThreadPoolExecutor(max_workers=TRANSCODE_WORKERS, thread_name_prefix="clipvideo-transcode")
    pending = {}
    try:
        for index, (start, end) in enumerate(ranges):
            number = settings["number_start"] + index
            filename = clean_name(settings["filename_prefix"], number, ".mp4")
            target = output / filename
            future = executor.submit(make_transcoded_clip, source, target, start, end, settings, width, height, encoder, copy_audio)
            pending[future] = (index, number, filename, target, start, end)
        for future in as_completed(pending):
            index, number, filename, target, start, end = pending[future]
            used_encoders.add(future.result())
            clip_map[index] = {"number": number, "filename": filename, "start": start, "end": end, "duration": end - start, "size": target.stat().st_size, "download_url": f"/api/v1/download/{job_id}/{filename}"}
            completed += 1
            update_job(job_id, current_clip=completed, progress=round(completed * 95 / len(ranges)), clips=[clip_map[item] for item in sorted(clip_map)], progress_label=f"{completed} of {len(ranges)} clips", message=f"Generated {completed} of {len(ranges)} clips with {TRANSCODE_WORKERS} workers")
    except Exception:
        for future in pending: future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    if used_encoders:
        update_job(job_id, processing_mode=f"parallel_{'+'.join(sorted(used_encoders))}_transcode")
    return [clip_map[index] for index in range(len(ranges))]
def cleanup():
    cutoff = time.time() - RETENTION_HOURS * 3600
    for base in (UPLOAD_DIR, CLIP_DIR, ARCHIVE_DIR, TEMP_DIR):
        for path in base.iterdir():
            if path.is_dir() and path.stat().st_mtime < cutoff: shutil.rmtree(path, ignore_errors=True)

def process_job(job_id: str, source: Path, settings: dict[str, Any]):
    uploaded_source = source
    try:
        update_job(job_id, status="processing", stage="Processing", message="Inspecting source video…")
        info = probe(source); ranges = build_ranges(settings, info["duration"]); width, height = get_frame(settings); output = CLIP_DIR / job_id; output.mkdir(parents=True, exist_ok=True); fast = width is None and height is None; formatted_encoder = None
        if not fast and TRANSCODE_STRATEGY == "parallel":
            clips = parallel_transcode_clips(source, output, settings, ranges, width, height, info, job_id)
            update_job(job_id, stage="Finalizing", progress=96, message="Creating ZIP archive…")
            folder = ARCHIVE_DIR / job_id; folder.mkdir(parents=True, exist_ok=True); archive = folder / "clipvideo-clips.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zip_file:
                for item in clips: zip_file.write(output / item["filename"], item["filename"])
            update_job(job_id, status="completed", stage="Complete", progress=100, current_clip=len(clips), clips=clips, progress_label=f"{len(clips)} of {len(clips)} clips", zip_url=f"/api/v1/download-zip/{job_id}", message="Clips are ready.", input_info=info)
            return
        if not fast and settings["split_mode"] == "duration":
            temporary = TEMP_DIR / job_id
            temporary.mkdir(parents=True, exist_ok=True)
            formatted_source = temporary / "formatted-source.mp4"
            gop_frames = max(1, round(info["fps"] * settings["clip_duration"])) if settings["split_mode"] == "duration" else None
            update_job(job_id, total_clips=len(ranges), processing_mode="transcode_once_then_fast_copy", stage="Formatting", progress_label=f"0 of {len(ranges)} clip lengths formatted", message="Formatting the source once for all clips…")
            formatted_encoder = transcode_source_once(source, formatted_source, settings, width, height, gop_frames, job_id, info, len(ranges))
            source, fast = formatted_source, True
        if formatted_encoder and settings["split_mode"] == "duration":
            update_job(job_id, total_clips=len(ranges), processing_mode=f"{formatted_encoder}_once_then_segment_copy", stage="Generating clips", progress=91, progress_label=f"0 of {len(ranges)} clips", message="Splitting all formatted clips in one fast FFmpeg pass…")
            targets = segment_duration_clips(source, output, settings, ranges)
            clips = []
            for index, ((start, end), target) in enumerate(zip(ranges, targets)):
                number = settings["number_start"] + index
                clips.append({"number": number, "filename": target.name, "start": start, "end": end, "duration": end - start, "size": target.stat().st_size, "download_url": f"/api/v1/download/{job_id}/{target.name}"})
            update_job(job_id, current_clip=len(clips), progress=95, clips=clips, progress_label=f"{len(clips)} of {len(clips)} clips", message=f"Fast-split {len(clips)} clips in one pass")
            update_job(job_id, stage="Finalizing", progress=96, message="Creating ZIP archive…")
            folder = ARCHIVE_DIR / job_id; folder.mkdir(parents=True, exist_ok=True); archive = folder / "clipvideo-clips.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zip_file:
                for item in clips: zip_file.write(output / item["filename"], item["filename"])
            update_job(job_id, status="completed", stage="Complete", progress=100, current_clip=len(clips), clips=clips, zip_url=f"/api/v1/download-zip/{job_id}", message="Clips are ready.", input_info=info)
            return
        if fast:
            update_job(job_id, total_clips=len(ranges), processing_mode="parallel_fast_copy", stage="Generating clips", progress_label=f"0 of {len(ranges)} clips", message=f"Fast-cutting with {FAST_COPY_WORKERS} workers…")
            if formatted_encoder:
                update_job(job_id, processing_mode=f"{formatted_encoder}_once_then_parallel_fast_copy", message=f"Source formatted once with {formatted_encoder}; fast-cutting with {FAST_COPY_WORKERS} workers…")
            completed, clip_map = 0, {}
            with ThreadPoolExecutor(max_workers=FAST_COPY_WORKERS, thread_name_prefix="clipvideo-fast-cut") as executor:
                pending = {}
                for index, (start, end) in enumerate(ranges):
                    number = settings["number_start"] + index
                    filename = clean_name(settings["filename_prefix"], number, ".mp4")
                    target = output / filename
                    future = executor.submit(make_clip, source, target, start, end, settings, None, None)
                    pending[future] = (index, number, filename, target, start, end)
                for future in as_completed(pending):
                    index, number, filename, target, start, end = pending[future]
                    future.result()
                    clip_map[index] = {"number": number, "filename": filename, "start": start, "end": end, "duration": end - start, "size": target.stat().st_size, "download_url": f"/api/v1/download/{job_id}/{filename}"}
                    completed += 1
                    update_job(job_id, current_clip=completed, progress=round(completed * 95 / len(ranges)), clips=[clip_map[item] for item in sorted(clip_map)], progress_label=f"{completed} of {len(ranges)} clips", message=f"Fast-cut {completed} of {len(ranges)} clips")
            clips = [clip_map[index] for index in range(len(ranges))]
            update_job(job_id, stage="Finalizing", progress=96, message="Creating ZIP archive…")
            folder = ARCHIVE_DIR / job_id; folder.mkdir(parents=True, exist_ok=True); archive = folder / "clipvideo-clips.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zip_file:
                for item in clips: zip_file.write(output / item["filename"], item["filename"])
            update_job(job_id, status="completed", stage="Complete", progress=100, current_clip=len(clips), clips=clips, zip_url=f"/api/v1/download-zip/{job_id}", message="Clips are ready.", input_info=info)
            return
        update_job(job_id, total_clips=len(ranges), processing_mode="fast_copy" if fast else "transcode", stage="Generating clips", message="Fast cutting clips…" if fast else "Transcoding clips with the selected frame…")
        clips = []
        for index, (start, end) in enumerate(ranges):
            number = settings["number_start"] + index; filename = clean_name(settings["filename_prefix"], number, ".mp4"); target = output / filename; make_clip(source, target, start, end, settings, width, height)
            clips.append({"number": number, "filename": filename, "start": start, "end": end, "duration": end - start, "size": target.stat().st_size, "download_url": f"/api/v1/download/{job_id}/{filename}"})
            update_job(job_id, current_clip=index + 1, progress=round((index + 1) * 95 / len(ranges)), clips=clips, progress_label=f"{index + 1} of {len(ranges)} clips", message=f"Generated clip {index + 1} of {len(ranges)}")
        update_job(job_id, stage="Finalizing", progress=96, message="Creating ZIP archive…")
        folder = ARCHIVE_DIR / job_id; folder.mkdir(parents=True, exist_ok=True); archive = folder / "clipvideo-clips.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zip_file:
            for item in clips: zip_file.write(output / item["filename"], item["filename"])
        update_job(job_id, status="completed", stage="Complete", progress=100, current_clip=len(clips), clips=clips, zip_url=f"/api/v1/download-zip/{job_id}", message="Clips are ready.", input_info=info)
    except Exception as error:
        logger.exception("Job %s failed", job_id); update_job(job_id, status="failed", stage="Failed", message="Clip generation failed.", error={"error": "PROCESSING_ERROR", "message": str(error)})
    finally:
        uploaded_source.unlink(missing_ok=True)
        source.unlink(missing_ok=True)
        shutil.rmtree(TEMP_DIR / job_id, ignore_errors=True)
        cleanup()

def validate(split_mode: str, duration: float | None, parts: int | None, preset: str, width: int | None, height: int | None, fit: str, output: str, start: int, prefix: str, custom: str | None, quality: str) -> dict[str, Any]:
    if output not in OUTPUT_FORMATS: raise api_error("INVALID_OUTPUT_FORMAT", f"{output.upper()} output is not available. Choose MP4.")
    if split_mode not in {"duration", "parts", "custom"}: raise api_error("INVALID_SETTINGS", "Choose duration, number of clips, or custom ranges.")
    if preset not in {*FRAME_PRESETS, "custom"} or fit not in {"contain", "crop", "stretch"}: raise api_error("INVALID_SETTINGS", "Choose a supported frame setting.")
    if start < 0: raise api_error("INVALID_SETTINGS", "Starting clip number must be zero or greater.")
    if split_mode == "duration" and (duration is None or duration <= 0): raise api_error("INVALID_SETTINGS", "Clip duration must be greater than zero.")
    if split_mode == "parts" and (parts is None or not 0 < parts <= MAX_CLIPS): raise api_error("INVALID_SETTINGS", f"Number of clips must be between 1 and {MAX_CLIPS}.")
    if split_mode == "custom" and not custom: raise api_error("INVALID_SETTINGS", "Add at least one custom start and end time.")
    if preset == "custom" and (not width or not height or width <= 0 or height <= 0 or width > 7680 or height > 7680): raise api_error("INVALID_SETTINGS", "Custom width and height must be between 1 and 7680 pixels.")
    return {"split_mode": split_mode, "clip_duration": duration or 0, "number_of_parts": parts or 0, "frame_preset": preset, "frame_width": width, "frame_height": height, "fit_mode": fit, "output_format": output, "number_start": start, "filename_prefix": prefix, "custom_clips": custom or "[]", "crf": {"low": 28, "medium": 23, "high": 20}.get(quality, 20)}

@app.get("/")
def root(): return {"success": True, "app": "ClipVideo", "version": app.version}
@app.get("/api/v1/health")
def health(): return {"success": True, "status": "healthy", "ffmpeg_available": bool(shutil.which("ffmpeg")), "ffprobe_available": bool(shutil.which("ffprobe"))}
@app.get("/api/v1/config")
def config(): return {"max_upload_size_gb": MAX_UPLOAD_SIZE_GB, "retention_hours": RETENTION_HOURS, "input_extensions": sorted(INPUT_FORMATS), "output_formats": [{"id": key, "extension": value["extension"], "mime": value["mime"]} for key, value in OUTPUT_FORMATS.items()]}
@app.post("/api/v1/process", status_code=202)
async def process_video(background_tasks: BackgroundTasks, file: UploadFile = File(...), split_mode: str = Form("duration"), clip_duration: float | None = Form(None), number_of_parts: int | None = Form(None), frame_preset: str = Form("original"), frame_width: int | None = Form(None), frame_height: int | None = Form(None), fit_mode: str = Form("contain"), output_format: str = Form("mp4"), number_start: int = Form(1), filename_prefix: str = Form("clip"), custom_clips: str | None = Form(None), video_quality: str = Form("high")):
    extension = Path(file.filename or "").suffix.lower()
    if extension not in INPUT_FORMATS: raise api_error("INVALID_FILE", "Video format is not supported. Choose MP4, MOV, MKV, AVI, WEBM, M4V, MPEG, or MPG.")
    if file.content_type and not (file.content_type.startswith("video/") or file.content_type == "application/octet-stream"): raise api_error("INVALID_FILE", "The selected file is not a video. Choose a supported video file.")
    settings = validate(split_mode, clip_duration, number_of_parts, frame_preset, frame_width, frame_height, fit_mode, output_format.lower(), number_start, filename_prefix, custom_clips, video_quality)
    job_id = str(uuid.uuid4()); directory = UPLOAD_DIR / job_id; directory.mkdir(parents=True); source = directory / f"source{extension}"
    with JOBS_LOCK: JOBS[job_id] = {"job_id": job_id, "status": "uploading", "stage": "Uploading", "progress": 0, "current_clip": 0, "total_clips": 0, "message": "Uploading video…", "clips": [], "zip_url": ""}
    try: size = await stream_upload(file, source)
    except Exception:
        with JOBS_LOCK: JOBS.pop(job_id, None)
        shutil.rmtree(directory, ignore_errors=True); raise
    update_job(job_id, status="queued", stage="Queued", message="Upload complete. Preparing processing…", file_size=size); background_tasks.add_task(process_job, job_id, source, settings)
    return {"job_id": job_id, "status": "queued", "status_url": f"/api/v1/status/{job_id}"}
@app.get("/api/v1/status/{job_id}")
def status(job_id: str):
    job = get_job(job_id)
    if not job: raise api_error("JOB_NOT_FOUND", "This processing job no longer exists. Upload the video again.", 404)
    return job
def job_file(base: Path, job_id: str, filename: str) -> Path:
    path = base / job_id / Path(filename).name
    if Path(filename).name != filename or not path.is_file(): raise api_error("DOWNLOAD_NOT_FOUND", "The requested download was not found or has expired.", 404)
    return path
@app.get("/api/v1/download/{job_id}/{filename}")
def download_clip(job_id: str, filename: str): return FileResponse(job_file(CLIP_DIR, job_id, filename), media_type="video/mp4", filename=filename, content_disposition_type="attachment")
@app.get("/api/v1/download-zip/{job_id}")
def download_zip(job_id: str): return FileResponse(job_file(ARCHIVE_DIR, job_id, "clipvideo-clips.zip"), media_type="application/zip", filename="clipvideo-clips.zip", content_disposition_type="attachment")
@app.delete("/api/v1/job/{job_id}", status_code=204)
def delete_job(job_id: str):
    with JOBS_LOCK: found = JOBS.pop(job_id, None)
    if not found: raise api_error("JOB_NOT_FOUND", "This processing job no longer exists.", 404)
    for base in (UPLOAD_DIR, CLIP_DIR, ARCHIVE_DIR): shutil.rmtree(base / job_id, ignore_errors=True)

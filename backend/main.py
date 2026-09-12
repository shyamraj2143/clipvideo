import json
import shutil
import subprocess
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024
CHUNK_SIZE = 4 * 1024 * 1024

UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="ClipVideo API",
    version="5.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# STATIC OUTPUT
# ============================================================

app.mount(
    "/outputs",
    StaticFiles(
        directory=str(OUTPUT_DIR)
    ),
    name="outputs",
)


# ============================================================
# JOB STORE
# ============================================================

JOBS = {}
JOBS_LOCK = threading.Lock()


def update_job(job_id, **values):

    with JOBS_LOCK:

        if job_id in JOBS:
            JOBS[job_id].update(values)


def get_job(job_id):

    with JOBS_LOCK:

        if job_id not in JOBS:
            return None

        return dict(
            JOBS[job_id]
        )


# ============================================================
# FFMPEG
# ============================================================

def get_ffmpeg():

    path = shutil.which("ffmpeg")

    if not path:

        raise RuntimeError(
            "FFmpeg is not installed or not available in PATH."
        )

    return path


def get_ffprobe():

    path = shutil.which("ffprobe")

    if not path:

        raise RuntimeError(
            "FFprobe is not installed or not available in PATH."
        )

    return path


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():

    return {
        "success": True,
        "app": "ClipVideo",
        "version": "5.0.0",
        "status": "running",
    }


@app.get("/api/health")
async def health():

    return {
        "success": True,
        "status": "healthy",
    }


@app.get("/api/v1/health")
async def v1_health():

    return {
        "success": True,
        "status": "healthy",
        "version": "v1",
    }


# ============================================================
# SAFE FILENAME
# ============================================================

def safe_filename(filename):

    filename = Path(
        filename or "video.mp4"
    ).name

    allowed = {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".webm",
        ".m4v",
        ".mpeg",
        ".mpg",
    }

    extension = Path(
        filename
    ).suffix.lower()

    if extension not in allowed:

        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported video format. "
                "Supported: MP4, MOV, MKV, AVI, "
                "WEBM, M4V, MPEG, MPG."
            ),
        )

    return filename


# ============================================================
# SAVE UPLOAD
# ============================================================

async def save_upload(
    upload: UploadFile,
    destination: Path,
):

    total = 0

    with destination.open(
        "wb"
    ) as output:

        while True:

            chunk = await upload.read(
                CHUNK_SIZE
            )

            if not chunk:
                break

            total += len(chunk)

            if total > MAX_FILE_SIZE:

                try:
                    destination.unlink()
                except Exception:
                    pass

                raise HTTPException(
                    status_code=413,
                    detail="Maximum video size is 10 GB.",
                )

            output.write(chunk)

    return total


# ============================================================
# VIDEO INFO
# ============================================================

def get_video_info(path: Path):

    command = [
        get_ffprobe(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:

        raise RuntimeError(
            result.stderr
            or "Unable to inspect video."
        )

    try:

        data = json.loads(
            result.stdout
        )

    except Exception:

        raise RuntimeError(
            "Invalid video information."
        )

    video_stream = None

    audio_stream = None

    for stream in data.get(
        "streams",
        [],
    ):

        if (
            stream.get("codec_type")
            == "video"
            and video_stream is None
        ):

            video_stream = stream

        if (
            stream.get("codec_type")
            == "audio"
            and audio_stream is None
        ):

            audio_stream = stream

    if not video_stream:

        raise RuntimeError(
            "No video stream found."
        )

    duration = float(
        data.get(
            "format",
            {},
        ).get(
            "duration",
            0,
        )
    )

    width = int(
        video_stream.get(
            "width",
            0,
        )
    )

    height = int(
        video_stream.get(
            "height",
            0,
        )
    )

    video_codec = (
        video_stream.get(
            "codec_name"
        )
        or ""
    ).lower()

    audio_codec = ""

    if audio_stream:

        audio_codec = (
            audio_stream.get(
                "codec_name"
            )
            or ""
        ).lower()

    fps = 0

    fps_value = (
        video_stream.get(
            "r_frame_rate",
            "0/1",
        )
    )

    try:

        a, b = fps_value.split("/")

        a = float(a)
        b = float(b)

        if b:
            fps = a / b

    except Exception:

        fps = 0

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
    }


# ============================================================
# FRAME PRESETS
# ============================================================

FRAME_PRESETS = {

    "original": None,

    "instagram_reel": {
        "width": 1080,
        "height": 1920,
        "ratio": "9:16",
    },

    "instagram_post": {
        "width": 1080,
        "height": 1080,
        "ratio": "1:1",
    },

    "instagram_portrait": {
        "width": 1080,
        "height": 1350,
        "ratio": "4:5",
    },

    "youtube": {
        "width": 1920,
        "height": 1080,
        "ratio": "16:9",
    },

    "youtube_shorts": {
        "width": 1080,
        "height": 1920,
        "ratio": "9:16",
    },

    "tiktok": {
        "width": 1080,
        "height": 1920,
        "ratio": "9:16",
    },

    "facebook": {
        "width": 1920,
        "height": 1080,
        "ratio": "16:9",
    },

}


# ============================================================
# FRAME RESOLUTION
# ============================================================

def resolve_frame(
    preset,
    width,
    height,
):

    if preset == "custom":

        if not width or not height:

            raise RuntimeError(
                "Custom frame requires width and height."
            )

        width = int(width)
        height = int(height)

        if width <= 0 or height <= 0:

            raise RuntimeError(
                "Invalid custom frame size."
            )

        return width, height, "custom"

    if preset == "original":

        return (
            None,
            None,
            "original",
        )

    data = FRAME_PRESETS.get(
        preset
    )

    if not data:

        raise RuntimeError(
            f"Unknown frame preset: {preset}"
        )

    return (
        data["width"],
        data["height"],
        data["ratio"],
    )


# ============================================================
# VIDEO FILTER
# ============================================================

def create_filter(
    width,
    height,
    fit_mode,
):

    if not width or not height:

        return (
            "scale="
            "trunc(iw/2)*2:"
            "trunc(ih/2)*2"
        )

    if fit_mode == "stretch":

        return (
            f"scale={width}:{height}"
        )

    if fit_mode == "crop":

        return (
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )

    return (
        f"scale={width}:{height}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:"
        "(ow-iw)/2:"
        "(oh-ih)/2"
    )


# ============================================================
# QUALITY
# ============================================================

def quality_crf(quality):

    values = {

        "low": "28",

        "medium": "23",

        "high": "20",

        "very_high": "17",

        "ultra": "15",

    }

    return values.get(
        str(
            quality or "high"
        ).lower(),
        "20",
    )


# ============================================================
# TIME PARSER
# ============================================================

def parse_time(value):

    if value is None:
        return 0.0

    value = str(
        value
    ).strip()

    if not value:
        return 0.0

    if ":" not in value:

        return float(value)

    parts = value.split(":")

    numbers = [
        float(x)
        for x in parts
    ]

    if len(numbers) == 3:

        return (
            numbers[0] * 3600
            + numbers[1] * 60
            + numbers[2]
        )

    if len(numbers) == 2:

        return (
            numbers[0] * 60
            + numbers[1]
        )

    return 0.0


# ============================================================
# CLIP RANGES
# ============================================================

def create_ranges(
    split_mode,
    video_duration,
    clip_duration,
    number_of_parts,
    custom_clips,
):

    if split_mode == "duration":

        clip_duration = float(
            clip_duration
        )

        if clip_duration <= 0:

            raise RuntimeError(
                "Clip duration must be greater than 0."
            )

        ranges = []

        current = 0.0

        while current < video_duration:

            end = min(
                current + clip_duration,
                video_duration,
            )

            ranges.append(
                {
                    "start": current,
                    "end": end,
                }
            )

            current = end

        return ranges


    if split_mode == "parts":

        parts = int(
            number_of_parts
        )

        if parts <= 0:

            raise RuntimeError(
                "Number of parts must be greater than 0."
            )

        if parts > 10000:

            raise RuntimeError(
                "Maximum 10000 parts are allowed."
            )

        part_duration = (
            video_duration / parts
        )

        ranges = []

        for i in range(parts):

            start = (
                i * part_duration
            )

            end = (
                video_duration
                if i == parts - 1
                else (
                    (i + 1)
                    * part_duration
                )
            )

            ranges.append(
                {
                    "start": start,
                    "end": end,
                }
            )

        return ranges


    if split_mode == "custom":

        try:

            clips = json.loads(
                custom_clips or "[]"
            )

        except Exception:

            raise RuntimeError(
                "Invalid custom clips."
            )

        if not clips:

            raise RuntimeError(
                "At least one custom clip is required."
            )

        ranges = []

        for index, clip in enumerate(
            clips
        ):

            start = parse_time(
                clip.get("start")
            )

            end = parse_time(
                clip.get("end")
            )

            if start < 0:

                raise RuntimeError(
                    f"Clip {index + 1}: "
                    "invalid start time."
                )

            if end <= start:

                raise RuntimeError(
                    f"Clip {index + 1}: "
                    "end must be greater than start."
                )

            if start >= video_duration:

                raise RuntimeError(
                    f"Clip {index + 1}: "
                    "start is outside video."
                )

            end = min(
                end,
                video_duration,
            )

            ranges.append(
                {
                    "start": start,
                    "end": end,
                }
            )

        return ranges


    raise RuntimeError(
        "Invalid split mode."
    )


# ============================================================
# PREFIX
# ============================================================

def clean_prefix(prefix):

    prefix = str(
        prefix or "clip"
    )

    result = ""

    for char in prefix:

        if (
            char.isalnum()
            or char in "_-"
        ):

            result += char

    return result or "clip"


# ============================================================
# FAST COPY CHECK
# ============================================================

def can_use_fast_copy(
    frame_preset,
    frame_width,
    frame_height,
    fps,
    fit_mode,
    output_format,
):
    """
    Stream copy is extremely fast because FFmpeg
    does NOT decode/re-encode the video.

    It is safe for our automatic fast mode when
    the user wants the original frame and source FPS.
    """

    original_frame = (
        frame_preset
        in (
            None,
            "",
            "original",
        )
    )

    original_fps = (
        fps
        in (
            None,
            "",
            "source",
            "original",
            "auto",
        )
    )

    no_custom_size = (
        not frame_width
        and not frame_height
    )

    normal_fit = (
        fit_mode
        in (
            None,
            "",
            "fit",
            "crop",
        )
    )

    mp4_output = (
        str(
            output_format
            or "mp4"
        ).lower()
        == "mp4"
    )

    return (
        original_frame
        and original_fps
        and no_custom_size
        and normal_fit
        and mp4_output
    )


# ============================================================
# CREATE ONE CLIP
# ============================================================

def create_clip_fast(
    input_path,
    output_path,
    start,
    duration,
):
    """
    FAST MODE.

    No video re-encoding.
    This is dramatically faster for large videos.
    """

    command = [

        get_ffmpeg(),

        "-hide_banner",

        "-loglevel",
        "error",

        "-y",

        "-ss",
        str(start),

        "-i",
        str(input_path),

        "-t",
        str(duration),

        "-map",
        "0:v:0?",

        "-map",
        "0:a?",

        "-c",
        "copy",

        "-avoid_negative_ts",
        "make_zero",

        "-movflags",
        "+faststart",

        str(output_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:

        raise RuntimeError(
            result.stderr
            or "Fast FFmpeg copy failed."
        )


# ============================================================
# CREATE ONE CLIP — ENCODE
# ============================================================

def create_clip_encoded(
    input_path,
    output_path,
    start,
    duration,
    video_filter,
    quality,
    fps,
):
    """
    Used when the user changes frame size,
    crop, resolution or FPS.
    """

    command = [

        get_ffmpeg(),

        "-hide_banner",

        "-loglevel",
        "error",

        "-y",

        "-ss",
        str(start),

        "-i",
        str(input_path),

        "-t",
        str(duration),

        "-map",
        "0:v:0?",

        "-map",
        "0:a?",

        "-vf",
        video_filter,

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-crf",
        quality,

        "-pix_fmt",
        "yuv420p",

        "-c:a",
        "aac",

        "-b:a",
        "160k",

        "-movflags",
        "+faststart",
    ]


    if fps not in (
        None,
        "",
        "source",
        "original",
        "auto",
    ):

        try:

            fps_value = float(
                fps
            )

            if fps_value > 0:

                command.extend(
                    [
                        "-r",
                        str(fps_value),
                    ]
                )

        except Exception:

            pass


    command.append(
        str(output_path)
    )


    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )


    if result.returncode != 0:

        raise RuntimeError(
            result.stderr
            or "FFmpeg encoding failed."
        )


# ============================================================
# PROCESS JOB
# ============================================================

def process_job(
    job_id,
    input_path,
    output_dir,
    settings,
):

    try:

        update_job(
            job_id,
            status="processing",
            progress=0,
            current_clip=0,
            total_clips=0,
            message="Reading video...",
        )


        # ----------------------------------------------------
        # VIDEO INFO
        # ----------------------------------------------------

        info = get_video_info(
            input_path
        )

        duration = float(
            info["duration"]
        )

        if duration <= 0:

            raise RuntimeError(
                "Invalid video duration."
            )


        # ----------------------------------------------------
        # FRAME
        # ----------------------------------------------------

        width, height, ratio = (
            resolve_frame(
                settings[
                    "frame_preset"
                ],
                settings[
                    "frame_width"
                ],
                settings[
                    "frame_height"
                ],
            )
        )


        video_filter = create_filter(
            width,
            height,
            settings[
                "fit_mode"
            ],
        )


        # ----------------------------------------------------
        # RANGES
        # ----------------------------------------------------

        ranges = create_ranges(
            settings[
                "split_mode"
            ],
            duration,
            settings[
                "clip_duration"
            ],
            settings[
                "number_of_parts"
            ],
            settings[
                "custom_clips"
            ],
        )


        total = len(
            ranges
        )


        # ----------------------------------------------------
        # FAST MODE
        # ----------------------------------------------------

        fast_mode = can_use_fast_copy(

            settings[
                "frame_preset"
            ],

            settings[
                "frame_width"
            ],

            settings[
                "frame_height"
            ],

            settings[
                "fps"
            ],

            settings[
                "fit_mode"
            ],

            settings[
                "output_format"
            ],
        )


        # ----------------------------------------------------
        # SETTINGS
        # ----------------------------------------------------

        crf = quality_crf(
            settings[
                "video_quality"
            ]
        )

        prefix = clean_prefix(
            settings[
                "filename_prefix"
            ]
        )

        start_number = int(
            settings[
                "number_start"
            ]
        )


        # ----------------------------------------------------
        # MODE MESSAGE
        # ----------------------------------------------------

        if fast_mode:

            update_job(
                job_id,
                total_clips=total,
                processing_mode="fast_copy",
                message=(
                    "Fast mode enabled — "
                    "original video quality preserved."
                ),
            )

        else:

            update_job(
                job_id,
                total_clips=total,
                processing_mode="encoding",
                message=(
                    "Encoding clips with selected "
                    "frame settings..."
                ),
            )


        results = []


        # ----------------------------------------------------
        # CREATE CLIPS
        # ----------------------------------------------------

        for index, clip_range in enumerate(
            ranges
        ):

            clip_number = (
                start_number
                + index
            )

            start = float(
                clip_range[
                    "start"
                ]
            )

            end = float(
                clip_range[
                    "end"
                ]
            )

            clip_duration = (
                end - start
            )


            filename = (
                f"{prefix}_"
                f"{clip_number:03d}.mp4"
            )


            output_path = (
                output_dir
                / filename
            )


            update_job(
                job_id,

                current_clip=index + 1,

                total_clips=total,

                progress=round(
                    (
                        index
                        / total
                    )
                    * 100
                ),

                message=(
                    "Creating clip "
                    f"{index + 1} "
                    f"of {total}"
                ),
            )


            # =================================================
            # FAST COPY
            # =================================================

            if fast_mode:

                create_clip_fast(

                    input_path,

                    output_path,

                    start,

                    clip_duration,
                )


            # =================================================
            # NORMAL ENCODE
            # =================================================

            else:

                create_clip_encoded(

                    input_path,

                    output_path,

                    start,

                    clip_duration,

                    video_filter,

                    crf,

                    settings[
                        "fps"
                    ],
                )


            # ------------------------------------------------
            # CHECK OUTPUT
            # ------------------------------------------------

            if not output_path.exists():

                raise RuntimeError(
                    f"Clip was not created: "
                    f"{filename}"
                )


            file_size = (
                output_path.stat()
                .st_size
            )


            results.append(
                {
                    "index": index,

                    "number": clip_number,

                    "name": filename,

                    "filename": filename,

                    "start": start,

                    "end": end,

                    "duration": clip_duration,

                    "size": file_size,

                    "url": (
                        f"/outputs/"
                        f"{job_id}/"
                        f"{filename}"
                    ),

                    "download_url": (
                        f"/api/v1/download/"
                        f"{job_id}/"
                        f"{filename}"
                    ),
                }
            )


            # ------------------------------------------------
            # PROGRESS
            # ------------------------------------------------

            progress = round(
                (
                    (
                        index + 1
                    )
                    / total
                )
                * 100
            )


            update_job(
                job_id,

                progress=progress,

                current_clip=(
                    index + 1
                ),

                total_clips=total,

                clips=results,

                message=(
                    "Created clip "
                    f"{index + 1} "
                    f"of {total}"
                ),
            )


        # ====================================================
        # ZIP
        # ====================================================

        update_job(
            job_id,
            progress=99,
            message="Creating ZIP file...",
            clips=results,
        )


        zip_path = (
            output_dir
            / "clips.zip"
        )


        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_STORED,
        ) as archive:

            for item in results:

                file_path = (
                    output_dir
                    / item[
                        "filename"
                    ]
                )

                archive.write(
                    file_path,
                    arcname=item[
                        "filename"
                    ],
                )


        # ====================================================
        # COMPLETE
        # ====================================================

        update_job(

            job_id,

            status="completed",

            progress=100,

            current_clip=total,

            total_clips=total,

            message="Processing completed.",

            clips=results,

            zip_url=(
                f"/api/v1/"
                f"download-zip/"
                f"{job_id}"
            ),

            input_info=info,

            settings=settings,

            processing_mode=(
                "fast_copy"
                if fast_mode
                else "encoding"
            ),
        )


        # ----------------------------------------------------
        # DELETE ORIGINAL UPLOAD
        # ----------------------------------------------------

        try:

            if input_path.exists():

                input_path.unlink()

        except Exception:

            pass


    except Exception as error:

        update_job(

            job_id,

            status="failed",

            progress=0,

            message="Processing failed.",

            error=str(error),

        )


        try:

            if input_path.exists():

                input_path.unlink()

        except Exception:

            pass


# ============================================================
# PROCESS API
# ============================================================

@app.post(
    "/api/v1/process"
)
async def process_video(

    background_tasks: BackgroundTasks,

    file: UploadFile = File(...),

    split_mode: str = Form(
        "duration"
    ),

    clip_duration: float = Form(
        60
    ),

    number_of_parts: int = Form(
        5
    ),

    frame_preset: str = Form(
        "original"
    ),

    frame_ratio: str = Form(
        "Original"
    ),

    frame_width: Optional[int] = Form(
        None
    ),

    frame_height: Optional[int] = Form(
        None
    ),

    fit_mode: str = Form(
        "crop"
    ),

    output_format: str = Form(
        "mp4"
    ),

    video_quality: str = Form(
        "high"
    ),

    fps: str = Form(
        "source"
    ),

    number_start: int = Form(
        1
    ),

    filename_prefix: str = Form(
        "clip"
    ),

    custom_clips: Optional[str] = Form(
        None
    ),
):


    # ========================================================
    # VALIDATION
    # ========================================================

    if output_format.lower() != "mp4":

        raise HTTPException(
            status_code=400,
            detail=(
                "Currently only MP4 "
                "output is supported."
            ),
        )


    if split_mode not in (
        "duration",
        "parts",
        "custom",
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid split mode.",
        )


    if fit_mode not in (
        "fit",
        "crop",
        "stretch",
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid fit mode.",
        )


    if number_start < 0:

        raise HTTPException(
            status_code=400,
            detail=(
                "Number start "
                "cannot be negative."
            ),
        )


    original_filename = (
        safe_filename(
            file.filename
        )
    )


    # ========================================================
    # JOB ID
    # ========================================================

    job_id = str(
        uuid.uuid4()
    )


    upload_dir = (
        UPLOAD_DIR
        / job_id
    )


    output_dir = (
        OUTPUT_DIR
        / job_id
    )


    upload_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    input_path = (
        upload_dir
        / original_filename
    )


    # ========================================================
    # CREATE JOB
    # ========================================================

    with JOBS_LOCK:

        JOBS[job_id] = {

            "job_id": job_id,

            "status": "uploading",

            "progress": 0,

            "current_clip": 0,

            "total_clips": 0,

            "message": (
                "Uploading video..."
            ),

            "clips": [],

            "zip_url": "",

        }


    # ========================================================
    # SAVE VIDEO
    # ========================================================

    try:

        file_size = await save_upload(
            file,
            input_path,
        )

    except Exception:

        with JOBS_LOCK:

            JOBS.pop(
                job_id,
                None,
            )

        raise


    # ========================================================
    # SETTINGS
    # ========================================================

    settings = {

        "split_mode": split_mode,

        "clip_duration": float(
            clip_duration
        ),

        "number_of_parts": int(
            number_of_parts
        ),

        "frame_preset": frame_preset,

        "frame_ratio": frame_ratio,

        "frame_width": frame_width,

        "frame_height": frame_height,

        "fit_mode": fit_mode,

        "output_format": "mp4",

        "video_quality": video_quality,

        "fps": fps,

        "number_start": int(
            number_start
        ),

        "filename_prefix": filename_prefix,

        "custom_clips": custom_clips,

    }


    # ========================================================
    # START BACKGROUND PROCESS
    # ========================================================

    background_tasks.add_task(

        process_job,

        job_id,

        input_path,

        output_dir,

        settings,

    )


    # ========================================================
    # RETURN IMMEDIATELY
    # ========================================================

    update_job(

        job_id,

        status="queued",

        progress=0,

        message=(
            "Upload complete. "
            "Processing started."
        ),

        file_size=file_size,

        filename=original_filename,

    )


    return {

        "success": True,

        "status": "queued",

        "job_id": job_id,

        "message": (
            "Upload completed. "
            "Processing has started."
        ),

        "filename": original_filename,

        "file_size": file_size,

        "status_url": (
            f"/api/v1/status/"
            f"{job_id}"
        ),

    }


# ============================================================
# STATUS
# ============================================================

@app.get(
    "/api/v1/status/{job_id}"
)
async def processing_status(
    job_id: str,
):

    job = get_job(
        job_id
    )

    if not job:

        raise HTTPException(
            status_code=404,
            detail="Job not found.",
        )

    return {
        "success": True,
        **job,
    }


# ============================================================
# DOWNLOAD ZIP
# ============================================================

@app.get(
    "/api/v1/download-zip/{job_id}"
)
async def download_zip(
    job_id: str,
):

    zip_path = (
        OUTPUT_DIR
        / job_id
        / "clips.zip"
    )


    if not zip_path.exists():

        raise HTTPException(
            status_code=404,
            detail="ZIP file not found.",
        )


    return FileResponse(

        str(zip_path),

        filename="clipvideo-clips.zip",

        media_type="application/zip",

    )


# ============================================================
# DOWNLOAD SINGLE CLIP
# ============================================================

@app.get(
    "/api/v1/download/{job_id}/{filename}"
)
async def download_clip(
    job_id: str,
    filename: str,
):

    filename = Path(
        filename
    ).name


    file_path = (
        OUTPUT_DIR
        / job_id
        / filename
    )


    if not file_path.exists():

        raise HTTPException(
            status_code=404,
            detail="Clip not found.",
        )


    return FileResponse(

        str(file_path),

        filename=filename,

        media_type="video/mp4",

    )


# ============================================================
# DELETE JOB
# ============================================================

@app.delete(
    "/api/v1/job/{job_id}"
)
async def delete_job(
    job_id: str,
):

    output_dir = (
        OUTPUT_DIR
        / job_id
    )

    upload_dir = (
        UPLOAD_DIR
        / job_id
    )


    if output_dir.exists():

        shutil.rmtree(
            output_dir,
            ignore_errors=True,
        )


    if upload_dir.exists():

        shutil.rmtree(
            upload_dir,
            ignore_errors=True,
        )


    with JOBS_LOCK:

        JOBS.pop(
            job_id,
            None,
        )


    return {

        "success": True,

        "message": (
            "Job deleted."
        ),

        "job_id": job_id,

    }


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(

        "main:app",

        host="127.0.0.1",

        port=8000,

        reload=True,

    )
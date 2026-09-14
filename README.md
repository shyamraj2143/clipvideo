# ClipVideo

ClipVideo splits one uploaded video into numbered clips, optionally reformats each clip for a social or landscape frame, and provides individual and ZIP downloads.

## Features

- Streaming, disk-backed uploads with a configurable 10 GB default limit.
- Duration, equal-parts, and custom start/end range clipping.
- Numbered filenames, browser-side source metadata, and searchable/paginated results.
- Original-frame MP4 clips use safe stream copy and 50 bounded parallel workers by default. Frame changes use up to 50 bounded parallel FFmpeg workers by default, with optional single-pass segment mode.
- Real upload progress and server-side clip/job progress.
- Stable attachment downloads retained for a configurable period (24 hours by default).

## Architecture

- `frontend/`: React 19 + Vite single-page UI.
- `backend/main.py`: FastAPI API, input/settings validation, FFmpeg/FFprobe integration, jobs, downloads, and cleanup.
- `backend/storage/`: ignored runtime storage for uploads, generated clips, and ZIP archives.

## Requirements

- Python 3.10+
- Node.js 20+
- FFmpeg and FFprobe available on `PATH`

## Run locally

Terminal 1:

```powershell
cd F:\projects\clipvideo\backend
..\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
cd F:\projects\clipvideo\frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite development proxy forwards `/api/*` to the backend, so `VITE_API_BASE_URL` is unnecessary locally. To use a deployed API, create `frontend/.env`:

```env
VITE_API_BASE_URL=https://your-api.example.com
```

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `MAX_UPLOAD_SIZE_GB` | `10` | Maximum streamed upload size. |
| `JOB_RETENTION_HOURS` | `24` | Generated clip/archive lifetime. |
| `FAST_COPY_WORKERS` | `50` | Parallel safe stream-copy processes (1–50). |
| `TRANSCODE_WORKERS` | `50` | Parallel FFmpeg processes for frame-changing clips (1–50). |
| `TRANSCODE_STRATEGY` | `parallel` | `parallel` creates frame-changing clips with multiple workers; `singlepass` encodes once then packet-splits duration clips. |
| `TRANSCODE_PRESET` | `superfast` | FFmpeg H.264 speed preset. `veryfast` uses less output storage. |
| `VIDEO_ENCODER` | `auto` | `auto`, `h264_qsv`, `h264_nvenc`, `h264_amf`, or `libx264`. Hardware failure safely retries with `libx264`. |
| `CORS_ORIGINS` | local Vite origins | Comma-separated allowed browser origins. |
| `LOG_LEVEL` | `INFO` | Backend log level. |

## API

`GET /docs` exposes the interactive FastAPI contract.

| Endpoint | Description |
| --- | --- |
| `GET /api/v1/health` | Service and FFmpeg availability. |
| `GET /api/v1/config` | Supported input/output formats and limits. |
| `POST /api/v1/process` | Multipart upload and process request; returns `202` with a job ID. |
| `GET /api/v1/status/{job_id}` | Actual upload/processing progress and results. |
| `GET /api/v1/download/{job_id}/{filename}` | Individual attachment download. |
| `GET /api/v1/download-zip/{job_id}` | ZIP attachment download. |

The process request uses `file`, `split_mode` (`duration`, `parts`, or `custom`), the active splitting field, frame values, `output_format`, `number_start`, and `filename_prefix`. Errors have a stable `{ "error", "message" }` shape.

## Formats and frames

Input extensions: MP4, MOV, MKV, AVI, WEBM, M4V, MPEG, MPG. The API currently supports MP4 output only; it intentionally advertises only MP4 through `/api/v1/config`. Frame presets are Original, Reels/Shorts/TikTok 9:16, Instagram Post 1:1, Instagram Portrait 4:5, YouTube Landscape 16:9, and Custom (up to 7680 px each side).

## Performance and security

Uploads are read in 4 MB chunks and written straight to job storage. FFprobe validates that the saved file contains a video stream. Original-frame cuts use `-c copy`; frame changes run multiple FFmpeg workers by default. The optional single-pass duration strategy encodes once with forced segment keyframes, live formatting progress, and fast packet splitting. FFmpeg receives argument arrays, not shell commands. Internal filenames are generated, user prefixes are filtered, and download paths reject traversal.

## Troubleshooting

- `ffmpeg_available: false`: install FFmpeg and restart the backend.
- `INVALID_FILE`: use a supported extension and a readable video stream.
- `INVALID_OUTPUT_FORMAT`: only MP4 is implemented; choose MP4.
- A 422 response means malformed or missing multipart fields. Inspect `/docs`; the frontend sends only the active optional fields.
- Downloads expire after `JOB_RETENTION_HOURS`; create the clips again when needed.

## Development checks

```powershell
cd F:\projects\clipvideo\frontend
npm run build

cd ..\backend
..\.venv\Scripts\python.exe -m compileall main.py
..\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Test a small MP4 through the UI with original frame, then with a 9:16 frame, custom range, number start `101`, and both individual/ZIP downloads. Test unsupported files, invalid ranges, invalid numbers, and a direct `POST /api/v1/process` through `/docs`.

## Roadmap

- Resumable uploads for unreliable networks.
- Persistent job records and queue workers for multi-user deployments.
- Additional output containers after codec/container test coverage is added.

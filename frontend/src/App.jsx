import React, { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const API_BASE =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024;

const FRAME_PRESETS = {
  original: {
    name: "Original",
    ratio: "Original",
    width: null,
    height: null,
    description: "Keep the original video frame",
    icon: "🎞️",
  },

  instagram_reel: {
    name: "Instagram Reel",
    ratio: "9:16",
    width: 1080,
    height: 1920,
    description: "Vertical short video",
    icon: "📸",
  },

  instagram_post: {
    name: "Instagram Post",
    ratio: "1:1",
    width: 1080,
    height: 1080,
    description: "Square Instagram video",
    icon: "⬛",
  },

  instagram_portrait: {
    name: "Instagram Portrait",
    ratio: "4:5",
    width: 1080,
    height: 1350,
    description: "Portrait Instagram video",
    icon: "▯",
  },

  youtube: {
    name: "YouTube",
    ratio: "16:9",
    width: 1920,
    height: 1080,
    description: "Standard YouTube video",
    icon: "▶️",
  },

  youtube_shorts: {
    name: "YouTube Shorts",
    ratio: "9:16",
    width: 1080,
    height: 1920,
    description: "Vertical Shorts video",
    icon: "📱",
  },

  tiktok: {
    name: "TikTok",
    ratio: "9:16",
    width: 1080,
    height: 1920,
    description: "Vertical TikTok video",
    icon: "🎵",
  },

  facebook: {
    name: "Facebook",
    ratio: "16:9",
    width: 1920,
    height: 1080,
    description: "Landscape Facebook video",
    icon: "f",
  },

  custom: {
    name: "Custom",
    ratio: "Custom",
    width: null,
    height: null,
    description: "Choose your own dimensions",
    icon: "⚙️",
  },
};

const DEFAULT_CLIP = {
  start: "00:00:00",
  end: "00:01:00",
};

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";

  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1
  );

  return `${(bytes / Math.pow(1024, index)).toFixed(
    index === 0 ? 0 : 2
  )} ${units[index]}`;
}

function formatSeconds(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "00:00:00";
  }

  const total = Math.floor(seconds);

  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;

  return [hours, minutes, secs]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}

function parseTime(value) {
  if (!value) return 0;

  const clean = String(value).trim();

  if (/^\d+(\.\d+)?$/.test(clean)) {
    return Number(clean);
  }

  const parts = clean.split(":").map(Number);

  if (parts.some((part) => Number.isNaN(part))) {
    return 0;
  }

  if (parts.length === 3) {
    return (
      parts[0] * 3600 +
      parts[1] * 60 +
      parts[2]
    );
  }

  if (parts.length === 2) {
    return parts[0] * 60 + parts[1];
  }

  return 0;
}

function getFileExtension(name) {
  const parts = name.split(".");
  return parts.length > 1
    ? parts[parts.length - 1].toUpperCase()
    : "VIDEO";
}

function App() {
  const fileInputRef = useRef(null);
  const videoRef = useRef(null);

  const [videoFile, setVideoFile] = useState(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [dragging, setDragging] = useState(false);

  const [videoDuration, setVideoDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);

  const [splitMode, setSplitMode] =
    useState("duration");

  const [clipDuration, setClipDuration] =
    useState("60");

  const [numberOfParts, setNumberOfParts] =
    useState("5");

  const [clips, setClips] = useState([
    { ...DEFAULT_CLIP },
  ]);

  const [framePreset, setFramePreset] =
    useState("original");

  const [customWidth, setCustomWidth] =
    useState("1080");

  const [customHeight, setCustomHeight] =
    useState("1920");

  const [fitMode, setFitMode] =
    useState("crop");

  const [outputFormat, setOutputFormat] =
    useState("mp4");

  const [videoQuality, setVideoQuality] =
    useState("high");

  const [fps, setFps] =
    useState("source");

  const [numberStart, setNumberStart] =
    useState("1");

  const [filenamePrefix, setFilenamePrefix] =
    useState("clip");

  const [showAdvanced, setShowAdvanced] =
    useState(false);

  const [uploadProgress, setUploadProgress] =
    useState(0);

  const [processingProgress, setProcessingProgress] =
    useState(0);

  const [uploading, setUploading] =
    useState(false);

  const [processing, setProcessing] =
    useState(false);

  const [error, setError] =
    useState("");

  const [successMessage, setSuccessMessage] =
    useState("");

  const [results, setResults] =
    useState([]);

  const [zipUrl, setZipUrl] =
    useState("");

  useEffect(() => {
    return () => {
      if (videoUrl) {
        URL.revokeObjectURL(videoUrl);
      }
    };
  }, [videoUrl]);

  const selectedFrame = FRAME_PRESETS[framePreset];

  const frameWidth =
    framePreset === "custom"
      ? Number(customWidth) || null
      : selectedFrame.width;

  const frameHeight =
    framePreset === "custom"
      ? Number(customHeight) || null
      : selectedFrame.height;

  const frameRatio = useMemo(() => {
    if (framePreset !== "custom") {
      return selectedFrame.ratio;
    }

    if (!frameWidth || !frameHeight) {
      return "Custom";
    }

    return `${frameWidth}:${frameHeight}`;
  }, [
    framePreset,
    selectedFrame.ratio,
    frameWidth,
    frameHeight,
  ]);

  const frameResolution = useMemo(() => {
    if (!frameWidth || !frameHeight) {
      return "Original";
    }

    return `${frameWidth} × ${frameHeight}`;
  }, [frameWidth, frameHeight]);

  const generatedClipCount = useMemo(() => {
    if (!videoDuration) return 0;

    if (splitMode === "parts") {
      return Math.max(
        1,
        Number(numberOfParts) || 1
      );
    }

    if (splitMode === "custom") {
      return clips.length;
    }

    const duration =
      Number(clipDuration) || 0;

    if (duration <= 0) return 0;

    return Math.ceil(videoDuration / duration);
  }, [
    videoDuration,
    splitMode,
    numberOfParts,
    clipDuration,
    clips.length,
  ]);

  function resetProcessingState() {
    setUploadProgress(0);
    setProcessingProgress(0);
    setUploading(false);
    setProcessing(false);
    setResults([]);
    setZipUrl("");
  }

  function handleSelectedFile(file) {
    setError("");
    setSuccessMessage("");
    setResults([]);
    setZipUrl("");

    if (!file) return;

    if (!file.type.startsWith("video/")) {
      setError(
        "Please select a valid video file."
      );
      return;
    }

    if (file.size > MAX_FILE_SIZE) {
      setError(
        "Video size cannot be greater than 10 GB."
      );
      return;
    }

    if (videoUrl) {
      URL.revokeObjectURL(videoUrl);
    }

    const url = URL.createObjectURL(file);

    setVideoFile(file);
    setVideoUrl(url);
    setVideoDuration(0);
    setCurrentTime(0);

    setClips([
      { ...DEFAULT_CLIP },
    ]);

    resetProcessingState();
  }

  function handleFileChange(event) {
    const file = event.target.files?.[0];

    handleSelectedFile(file);

    event.target.value = "";
  }

  function handleDrop(event) {
    event.preventDefault();
    setDragging(false);

    const file = event.dataTransfer.files?.[0];

    handleSelectedFile(file);
  }

  function removeVideo() {
    if (videoUrl) {
      URL.revokeObjectURL(videoUrl);
    }

    setVideoFile(null);
    setVideoUrl("");
    setVideoDuration(0);
    setCurrentTime(0);
    setError("");
    setSuccessMessage("");
    setResults([]);
    setZipUrl("");
  }

  function handleLoadedMetadata() {
    const duration =
      videoRef.current?.duration || 0;

    setVideoDuration(duration);

    setClips([
      {
        start: "00:00:00",
        end: formatSeconds(
          Math.min(duration, 60)
        ),
      },
    ]);
  }

  function handleTimeUpdate() {
    setCurrentTime(
      videoRef.current?.currentTime || 0
    );
  }

  function seekVideo(time) {
    if (!videoRef.current) return;

    const safeTime = Math.max(
      0,
      Math.min(time, videoDuration || time)
    );

    videoRef.current.currentTime = safeTime;
    setCurrentTime(safeTime);
  }

  function addClip() {
    const lastClip =
      clips[clips.length - 1];

    const lastEnd =
      parseTime(lastClip?.end) || 0;

    const start =
      Math.min(
        lastEnd,
        videoDuration || lastEnd
      );

    const end =
      Math.min(
        start + 60,
        videoDuration || start + 60
      );

    setClips([
      ...clips,
      {
        start: formatSeconds(start),
        end: formatSeconds(end),
      },
    ]);
  }

  function removeClip(index) {
    if (clips.length === 1) {
      setError(
        "At least one custom clip is required."
      );
      return;
    }

    setClips(
      clips.filter(
        (_, clipIndex) =>
          clipIndex !== index
      )
    );
  }

  function updateClip(index, field, value) {
    setClips((current) =>
      current.map((clip, clipIndex) =>
        clipIndex === index
          ? {
              ...clip,
              [field]: value,
            }
          : clip
      )
    );
  }

  function useCurrentTime(index, field) {
    updateClip(
      index,
      field,
      formatSeconds(currentTime)
    );
  }

  function validateCustomClips() {
    if (!clips.length) {
      return "Please add at least one clip.";
    }

    for (let i = 0; i < clips.length; i++) {
      const start = parseTime(
        clips[i].start
      );

      const end = parseTime(
        clips[i].end
      );

      if (end <= start) {
        return `Clip ${i + 1}: end time must be greater than start time.`;
      }

      if (
        videoDuration &&
        end > videoDuration + 0.5
      ) {
        return `Clip ${i + 1}: end time is beyond the video duration.`;
      }
    }

    return "";
  }

  function buildFormData() {
    const formData = new FormData();

    formData.append(
      "file",
      videoFile
    );

    formData.append(
      "split_mode",
      splitMode
    );

    formData.append(
      "clip_duration",
      clipDuration
    );

    formData.append(
      "number_of_parts",
      numberOfParts
    );

    formData.append(
      "frame_preset",
      framePreset
    );

    formData.append(
      "frame_ratio",
      frameRatio
    );

    formData.append(
      "frame_width",
      frameWidth ?? ""
    );

    formData.append(
      "frame_height",
      frameHeight ?? ""
    );

    formData.append(
      "fit_mode",
      fitMode
    );

    formData.append(
      "output_format",
      outputFormat
    );

    formData.append(
      "video_quality",
      videoQuality
    );

    formData.append(
      "fps",
      fps
    );

    formData.append(
      "number_start",
      numberStart
    );

    formData.append(
      "filename_prefix",
      filenamePrefix
    );

    if (splitMode === "custom") {
      formData.append(
        "custom_clips",
        JSON.stringify(clips)
      );
    }

    return formData;
  }

  async function uploadAndProcess() {
    setError("");
    setSuccessMessage("");
    setResults([]);
    setZipUrl("");
    setUploadProgress(0);
    setProcessingProgress(0);

    if (!videoFile) {
      setError("Please select a video first.");
      return;
    }

    if (videoFile.size > MAX_FILE_SIZE) {
      setError("Video size cannot be greater than 10 GB.");
      return;
    }

    if (splitMode === "duration") {
      const duration = Number(clipDuration);
      if (!Number.isFinite(duration) || duration <= 0) {
        setError("Please enter a valid clip duration.");
        return;
      }
    }

    if (splitMode === "parts") {
      const parts = Number(numberOfParts);
      if (!Number.isInteger(parts) || parts <= 0) {
        setError("Please enter a valid number of parts.");
        return;
      }
    }

    if (splitMode === "custom") {
      const validation = validateCustomClips();
      if (validation) {
        setError(validation);
        return;
      }
    }

    if (framePreset === "custom") {
      if (!frameWidth || !frameHeight || frameWidth <= 0 || frameHeight <= 0) {
        setError("Please enter a valid custom frame width and height.");
        return;
      }
    }

    const formData = buildFormData();
    setUploading(true);
    setProcessing(false);

    try {
      // Upload only. The backend returns a job_id as soon as the file is saved.
      const job = await sendMultipartRequest(
        `${API_BASE}/api/v1/process`,
        formData,
        (progress) => {
          setUploadProgress(progress);
        }
      );

      setUploading(false);

      if (!job?.job_id) {
        // Backward compatibility with the previous backend response format.
        const normalized = normalizeResult(job);

        if (normalized.clips.length) {
          setResults(normalized.clips);
        }

        if (normalized.zip) {
          setZipUrl(normalized.zip);
        }

        setProcessingProgress(100);
        setProcessing(false);
        setSuccessMessage(
          `Successfully created ${normalized.clips.length || generatedClipCount} clip(s).`
        );
        return;
      }

      // Processing is now a separate stage.
      setProcessing(true);
      setProcessingProgress(0);

      await pollProcessingJob(job.job_id);

    } catch (err) {
      setUploading(false);
      setProcessing(false);
      setError(
        err?.message ||
          "Something went wrong while processing the video."
      );
    }
  }

  async function pollProcessingJob(jobId) {
    while (true) {
      const response = await fetch(
        `${API_BASE}/api/v1/status/${jobId}`,
        {
          method: "GET",
          headers: {
            Accept: "application/json",
          },
          cache: "no-store",
        }
      );

      if (!response.ok) {
        let message = `Status request failed: HTTP ${response.status}.`;
        try {
          const body = await response.json();
          message = body?.detail || body?.message || message;
        } catch {
          // Keep the HTTP error message.
        }
        throw new Error(message);
      }

      const data = await response.json();
      const progress = Number(data?.progress ?? 0);

      setProcessingProgress(
        Math.max(0, Math.min(100, Math.round(progress)))
      );

      if (Array.isArray(data?.clips) && data.clips.length > 0) {
        setResults(
          data.clips.map((item, index) => ({
            name:
              item?.name ||
              item?.filename ||
              `${filenamePrefix}_${String(
                Number(numberStart) + index
              ).padStart(2, "0")}.${outputFormat}`,
            url: makeApiUrl(
              item?.download_url ||
                item?.url ||
                item?.file_url ||
                item?.path ||
                ""
            ),
            duration: item?.duration || "",
            start: item?.start ?? "",
            end: item?.end ?? "",
          }))
        );
      }

      if (data?.zip_url || data?.download_all || data?.zip) {
        setZipUrl(
          makeApiUrl(
            data?.zip_url || data?.download_all || data?.zip
          )
        );
      }

      if (data?.status === "failed") {
        throw new Error(
          data?.error ||
            data?.message ||
            "Video processing failed."
        );
      }

      if (data?.status === "completed") {
        setProcessingProgress(100);
        setProcessing(false);

        const normalized = normalizeResult(data);

        if (normalized.clips.length) {
          setResults(normalized.clips);
        }

        if (normalized.zip) {
          setZipUrl(normalized.zip);
        }

        const count =
          data?.total_clips ||
          normalized.clips.length ||
          generatedClipCount;

        setSuccessMessage(
          `Successfully created ${count} clip(s).`
        );

        return;
      }

      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }

  function sendMultipartRequest(
    url,
    formData,
    onProgress
  ) {
    return new Promise(
      (resolve, reject) => {
        const xhr =
          new XMLHttpRequest();

        xhr.open(
          "POST",
          url,
          true
        );

        xhr.responseType = "json";

        xhr.upload.onprogress =
          (event) => {
            if (!event.lengthComputable) {
              return;
            }

            const progress = Math.round(
              (event.loaded /
                event.total) *
                100
            );

            onProgress(progress);
          };

        xhr.onload = () => {
          let response =
            xhr.response;

          if (!response) {
            try {
              response =
                JSON.parse(
                  xhr.responseText
                );
            } catch {
              response = null;
            }
          }

          if (
            xhr.status >= 200 &&
            xhr.status < 300
          ) {
            resolve(response);
            return;
          }

          const message =
            response?.detail ||
            response?.message ||
            `Server returned HTTP ${xhr.status}.`;

          reject(
            new Error(message)
          );
        };

        xhr.onerror = () => {
          reject(
            new Error(
              "Cannot connect to backend. Make sure FastAPI is running."
            )
          );
        };

        xhr.onabort = () => {
          reject(
            new Error(
              "Upload was cancelled."
            )
          );
        };

        xhr.send(formData);
      }
    );
  }

  function normalizeResult(data) {
    const rawClips =
      data?.clips ||
      data?.results ||
      data?.files ||
      [];

    const clipsResult =
      Array.isArray(rawClips)
        ? rawClips.map(
            (item, index) => {
              if (
                typeof item === "string"
              ) {
                return {
                  name:
                    `${filenamePrefix}_${String(
                      Number(numberStart) +
                        index
                    ).padStart(
                      2,
                      "0"
                    )}.${outputFormat}`,
                  url: makeApiUrl(item),
                  duration: "",
                  start: "",
                  end: "",
                };
              }

              const url =
                item?.url ||
                item?.download_url ||
                item?.file_url ||
                item?.path ||
                "";

              return {
                name:
                  item?.name ||
                  item?.filename ||
                  `${filenamePrefix}_${String(
                    Number(numberStart) +
                      index
                  ).padStart(
                    2,
                    "0"
                  )}.${outputFormat}`,

                url:
                  makeApiUrl(url),

                duration:
                  item?.duration ||
                  "",

                start:
                  item?.start ||
                  "",

                end:
                  item?.end ||
                  "",
              };
            }
          )
        : [];

    return {
      clips: clipsResult,
      zip: makeApiUrl(
        data?.zip_url ||
          data?.download_all ||
          data?.zip ||
          ""
      ),
    };
  }

  function makeApiUrl(url) {
    if (!url) return "";

    if (
      url.startsWith("http://") ||
      url.startsWith("https://")
    ) {
      return url;
    }

    if (url.startsWith("/")) {
      return `${API_BASE}${url}`;
    }

    return `${API_BASE}/${url}`;
  }

  function renderModeDescription() {
    if (splitMode === "duration") {
      return "Create clips using a fixed duration.";
    }

    if (splitMode === "parts") {
      return "Automatically divide the video into equal parts.";
    }

    return "Manually define every clip using start and end time.";
  }

  return (
    <div className="app">

      {/* =====================================================
          HEADER
      ===================================================== */}

      <header className="header">

        <div className="logo">

          <div className="logo-mark">
            ✂
          </div>

          <div>
            <div className="logo-title">
              ClipVideo
            </div>

            <div className="logo-subtitle">
              Fast video clipping & formatting
            </div>
          </div>

        </div>

        <div className="header-right">

          <div className="status-pill">
            <span className="status-dot" />
            Local processing
          </div>

          <div className="limit-pill">
            MAX 10 GB
          </div>

        </div>

      </header>


      {/* =====================================================
          MAIN
      ===================================================== */}

      <main className="container">

        {/* HERO */}

        <section className="hero">

          <div className="eyebrow">
            PROFESSIONAL VIDEO CLIPPER
          </div>

          <h1>
            Turn one video into
            <br />
            <span>perfect clips.</span>
          </h1>

          <p className="subtitle">
            Upload a video up to 10 GB, split it
            exactly how you want, choose a platform
            frame, and generate numbered clips ready
            for publishing.
          </p>

        </section>


        {/* ERROR */}

        {error && (
          <div className="error-box">
            <span>⚠️</span>
            <div>{error}</div>
          </div>
        )}


        {/* SUCCESS */}

        {successMessage && (
          <div className="upload-success">
            <div className="success-icon">
              ✓
            </div>

            <div>
              <strong>
                {successMessage}
              </strong>

              <span>
                Your clips are ready below.
              </span>
            </div>
          </div>
        )}


        {/* =====================================================
          RESULTS / DOWNLOADS
      ===================================================== */}

      {results.length > 0 && (
        <section
          className="card results-card results-bottom"
        >

          {/* RESULT HEADER */}
          <div className="results-heading">

            <div className="results-title-area">

              <div className="results-success-icon">
                ✓
              </div>

              <div>

                <h2>
                  Clips Ready
                </h2>

                <p>
                  Successfully created{" "}
                  <strong>
                    {results.length}
                  </strong>{" "}
                  numbered clip(s).
                </p>

              </div>

            </div>


            {/* DOWNLOAD ALL */}
            {zipUrl && (
              <a
                className="download-all-btn"
                href={zipUrl}
                download="clipvideo-clips.zip"
              >
                ↓ Download All ZIP
              </a>
            )}

          </div>


          {/* DIVIDER */}
          <div className="results-divider" />


          {/* DOWNLOAD DESCRIPTION */}
          <div className="download-section-title">

            <div>

              <h3>
                Download your clips
              </h3>

              <p>
                Each clip is numbered according to your
                selected starting number.
              </p>

            </div>

            {zipUrl && (
              <a
                className="download-all-secondary"
                href={zipUrl}
                download="clipvideo-clips.zip"
              >
                ↓ Download All
              </a>
            )}

          </div>


          {/* CLIP LIST */}
          <div className="clip-list">

            {results.map(
              (clip, index) => {

                const clipNumber =
                  Number(numberStart) + index;

                const clipName =
                  clip.name ||
                  clip.filename ||
                  `clip_${String(
                    clipNumber
                  ).padStart(
                    2,
                    "0"
                  )}.${outputFormat}`;

                const downloadUrl =
                  clip.download_url ||
                  clip.url ||
                  "";

                return (
                  <div
                    className="clip-row"
                    key={`${clipName}-${index}`}
                  >

                    {/* NUMBER */}
                    <div className="clip-number-large">
                      {clipNumber}
                    </div>


                    {/* INFO */}
                    <div className="clip-info">

                      <strong>
                        {clipName}
                      </strong>

                      <span>

                        {clip.start &&
                        clip.end
                          ? `${clip.start} → ${clip.end}`
                          : clip.duration
                          ? clip.duration
                          : "Video clip"}

                      </span>

                    </div>


                    {/* DOWNLOAD */}
                    {downloadUrl && (
                      <a
                        className="clip-download"
                        href={downloadUrl}
                        download={clipName}
                        target="_blank"
                        rel="noreferrer"
                      >
                        ↓ Download
                      </a>
                    )}

                  </div>
                );

              }
            )}

          </div>

        </section>
      )}


        {/* =================================================
            UPLOAD CARD
        ================================================= */}

        <section className="card">

          {!videoFile ? (

            <div
              className={`dropzone ${
                dragging
                  ? "dragging"
                  : ""
              }`}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() =>
                setDragging(false)
              }
              onDrop={handleDrop}
              onClick={() =>
                fileInputRef.current?.click()
              }
            >

              <div className="upload-icon">
                ↑
              </div>

              <h2>
                Drop your video here
              </h2>

              <p>
                or click anywhere to browse
              </p>

              <div className="upload-formats">
                MP4
                <span>•</span>
                MOV
                <span>•</span>
                AVI
                <span>•</span>
                MKV
                <span>•</span>
                WEBM
              </div>

              <div className="upload-limit">
                Maximum file size: 10 GB
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept="video/*"
                onChange={
                  handleFileChange
                }
                hidden
              />

            </div>

          ) : (

            <div className="selected-video-wrapper">

              <div className="selected-file">

                <div className="video-file-icon">
                  🎬
                </div>

                <div className="file-details">

                  <div className="file-name">
                    {videoFile.name}
                  </div>

                  <div className="file-meta">

                    <span>
                      {formatBytes(
                        videoFile.size
                      )}
                    </span>

                    <span>•</span>

                    <span>
                      {getFileExtension(
                        videoFile.name
                      )}
                    </span>

                    {videoDuration > 0 && (
                      <>
                        <span>•</span>

                        <span>
                          {formatSeconds(
                            videoDuration
                          )}
                        </span>
                      </>
                    )}

                  </div>

                </div>

                <button
                  className="remove-btn"
                  onClick={removeVideo}
                  type="button"
                  title="Remove video"
                >
                  ×
                </button>

              </div>


              {/* VIDEO PREVIEW */}

              <div className="video-preview">

                <video
                  ref={videoRef}
                  src={videoUrl}
                  controls
                  preload="metadata"
                  onLoadedMetadata={
                    handleLoadedMetadata
                  }
                  onTimeUpdate={
                    handleTimeUpdate
                  }
                />

              </div>


              {/* CURRENT TIME */}

              <div className="video-time-bar">

                <span>
                  Current
                </span>

                <strong>
                  {formatSeconds(
                    currentTime
                  )}
                </strong>

                <span>
                  /
                </span>

                <strong>
                  {formatSeconds(
                    videoDuration
                  )}
                </strong>

              </div>


              {/* UPLOAD BUTTON */}

              <button
                type="button"
                className="primary-btn"
                onClick={() =>
                  fileInputRef.current?.click()
                }
              >
                Change Video
              </button>

              <input
                ref={fileInputRef}
                type="file"
                accept="video/*"
                onChange={
                  handleFileChange
                }
                hidden
              />

            </div>

          )}

          {/* UPLOAD PROGRESS */}

          {uploading && (
            <div className="upload-progress">

              <div className="progress-top">

                <span>
                  Uploading video...
                </span>

                <strong>
                  {uploadProgress}%
                </strong>

              </div>

              <div className="progress-bar">

                <div
                  className="progress-fill"
                  style={{
                    width:
                      `${uploadProgress}%`,
                  }}
                />

              </div>

              <div className="progress-bottom">
                <span>
                  Large files may take some time.
                </span>
              </div>

            </div>
          )}

        </section>


        {/* =================================================
            CLIPPING SETTINGS
        ================================================= */}

        {videoFile && (
          <section className="card">

            <div className="section-heading">

              <div>
                <h2>
                  01. Clip settings
                </h2>

                <p>
                  Decide exactly how the video
                  should be divided.
                </p>
              </div>

              {videoDuration > 0 && (
                <div className="video-duration-badge">

                  <span>
                    VIDEO LENGTH
                  </span>

                  <strong>
                    {formatSeconds(
                      videoDuration
                    )}
                  </strong>

                </div>
              )}

            </div>


            {/* MODE GRID */}

            <div className="mode-grid">

              <button
                type="button"
                className={`mode-card ${
                  splitMode === "duration"
                    ? "active"
                    : ""
                }`}
                onClick={() =>
                  setSplitMode(
                    "duration"
                  )
                }
              >

                <div className="mode-icon">
                  ⏱
                </div>

                <div className="mode-content">

                  <strong>
                    By Duration
                  </strong>

                  <span>
                    Every clip has the
                    selected length.
                  </span>

                </div>

                <div className="mode-radio">
                  {splitMode ===
                    "duration" && "✓"}
                </div>

              </button>


              <button
                type="button"
                className={`mode-card ${
                  splitMode === "parts"
                    ? "active"
                    : ""
                }`}
                onClick={() =>
                  setSplitMode(
                    "parts"
                  )
                }
              >

                <div className="mode-icon">
                  🧩
                </div>

                <div className="mode-content">

                  <strong>
                    Equal Parts
                  </strong>

                  <span>
                    Divide the complete
                    video equally.
                  </span>

                </div>

                <div className="mode-radio">
                  {splitMode ===
                    "parts" && "✓"}
                </div>

              </button>


              <button
                type="button"
                className={`mode-card ${
                  splitMode === "custom"
                    ? "active"
                    : ""
                }`}
                onClick={() =>
                  setSplitMode(
                    "custom"
                  )
                }
              >

                <div className="mode-icon">
                  🎯
                </div>

                <div className="mode-content">

                  <strong>
                    Custom Timestamps
                  </strong>

                  <span>
                    Set your own start
                    and end points.
                  </span>

                </div>

                <div className="mode-radio">
                  {splitMode ===
                    "custom" && "✓"}
                </div>

              </button>

            </div>


            <p className="mode-description">
              {renderModeDescription()}
            </p>


            {/* DURATION */}

            {splitMode === "duration" && (
              <div className="configuration-panel">

                <div className="field">

                  <label>
                    Clip duration
                  </label>

                  <div className="input-with-unit">

                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={
                        clipDuration
                      }
                      onChange={(event) =>
                        setClipDuration(
                          event.target.value
                        )
                      }
                    />

                    <span>
                      seconds
                    </span>

                  </div>

                  <small>
                    Example: 60 = one-minute
                    clips.
                  </small>

                </div>

              </div>
            )}


            {/* PARTS */}

            {splitMode === "parts" && (
              <div className="configuration-panel">

                <div className="field">

                  <label>
                    Number of clips
                  </label>

                  <div className="input-with-unit">

                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={
                        numberOfParts
                      }
                      onChange={(event) =>
                        setNumberOfParts(
                          event.target.value
                        )
                      }
                    />

                    <span>
                      clips
                    </span>

                  </div>

                  <small>
                    The complete video will
                    be divided equally.
                  </small>

                </div>

              </div>
            )}


            {/* CUSTOM TIMESTAMPS */}

            {splitMode === "custom" && (
              <div className="custom-panel configuration-panel">

                <div className="custom-header">

                  <div>
                    <strong>
                      Custom clip list
                    </strong>

                    <span>
                      Use HH:MM:SS format.
                    </span>
                  </div>

                  <button
                    type="button"
                    className="small-primary-btn"
                    onClick={addClip}
                  >
                    + Add Clip
                  </button>

                </div>


                <div className="custom-list">

                  {clips.map(
                    (clip, index) => (
                      <div
                        className="timestamp-row"
                        key={index}
                      >

                        <div className="clip-number">
                          #{Number(
                            numberStart
                          ) + index}
                        </div>


                        <div className="field">

                          <label>
                            Start
                          </label>

                          <input
                            type="text"
                            value={
                              clip.start
                            }
                            placeholder="00:00:00"
                            onChange={(
                              event
                            ) =>
                              updateClip(
                                index,
                                "start",
                                event.target
                                  .value
                              )
                            }
                          />

                        </div>


                        <div className="field">

                          <label>
                            End
                          </label>

                          <input
                            type="text"
                            value={
                              clip.end
                            }
                            placeholder="00:01:00"
                            onChange={(
                              event
                            ) =>
                              updateClip(
                                index,
                                "end",
                                event.target
                                  .value
                              )
                            }
                          />

                        </div>


                        <div className="timestamp-preview">
                          {Math.max(
                            0,
                            parseTime(
                              clip.end
                            ) -
                              parseTime(
                                clip.start
                              )
                          ).toFixed(0)}
                          s
                        </div>


                        <button
                          type="button"
                          className="delete-btn"
                          onClick={() =>
                            removeClip(
                              index
                            )
                          }
                          title="Delete clip"
                        >
                          ×
                        </button>


                        <div className="timestamp-actions">

                          <button
                            type="button"
                            onClick={() =>
                              useCurrentTime(
                                index,
                                "start"
                              )
                            }
                          >
                            Use current as start
                          </button>

                          <button
                            type="button"
                            onClick={() =>
                              useCurrentTime(
                                index,
                                "end"
                              )
                            }
                          >
                            Use current as end
                          </button>

                          <button
                            type="button"
                            onClick={() =>
                              seekVideo(
                                parseTime(
                                  clip.start
                                )
                              )
                            }
                          >
                            ▶ Preview
                          </button>

                        </div>

                      </div>
                    )
                  )}

                </div>

              </div>
            )}


            {/* =================================================
                FRAME SETTINGS
            ================================================= */}

            <div className="frame-settings">

              <div className="frame-settings-header">

                <div>
                  <h3>
                    🎬 02. Video frame & platform
                  </h3>

                  <p>
                    Choose the platform and the
                    output frame size for every clip.
                  </p>
                </div>

              </div>


              <div className="platform-grid">

                {Object.entries(
                  FRAME_PRESETS
                ).map(
                  ([
                    key,
                    preset,
                  ]) => (
                    <button
                      key={key}
                      type="button"
                      className={`platform-card ${
                        framePreset === key
                          ? "active"
                          : ""
                      }`}
                      onClick={() =>
                        setFramePreset(
                          key
                        )
                      }
                    >

                      <div className="platform-icon">
                        {preset.icon}
                      </div>

                      <div className="platform-info">

                        <strong>
                          {preset.name}
                        </strong>

                        <span>
                          {preset.ratio}

                          {preset.width &&
                            preset.height &&
                            ` • ${preset.width} × ${preset.height}`}

                          {!preset.width &&
                            key === "original" &&
                            " • Source resolution"}

                          {key === "custom" &&
                            " • Your own size"}
                        </span>

                      </div>

                      {framePreset ===
                        key && (
                        <div className="selected-check">
                          ✓
                        </div>
                      )}

                    </button>
                  )
                )}

              </div>


              {/* CUSTOM FRAME */}

              {framePreset === "custom" && (
                <div className="custom-frame-box">

                  <div className="custom-frame-title">

                    <strong>
                      Custom frame size
                    </strong>

                    <span>
                      Enter width and height
                      in pixels.
                    </span>

                  </div>


                  <div className="frame-input-grid">

                    <div className="field">

                      <label>
                        Width
                      </label>

                      <div className="input-with-unit">

                        <input
                          type="number"
                          min="1"
                          value={
                            customWidth
                          }
                          onChange={(event) =>
                            setCustomWidth(
                              event.target
                                .value
                            )
                          }
                        />

                        <span>
                          px
                        </span>

                      </div>

                    </div>


                    <div className="field">

                      <label>
                        Height
                      </label>

                      <div className="input-with-unit">

                        <input
                          type="number"
                          min="1"
                          value={
                            customHeight
                          }
                          onChange={(event) =>
                            setCustomHeight(
                              event.target
                                .value
                            )
                          }
                        />

                        <span>
                          px
                        </span>

                      </div>

                    </div>

                  </div>


                  <div className="custom-ratio">

                    <span>
                      Aspect ratio
                    </span>

                    <strong>
                      {frameRatio}
                    </strong>

                  </div>

                </div>
              )}


              {/* FRAME SUMMARY */}

              <div className="frame-summary">

                <div>
                  <span>
                    Platform
                  </span>

                  <strong>
                    {selectedFrame.name}
                  </strong>
                </div>


                <div>
                  <span>
                    Frame
                  </span>

                  <strong>
                    {frameRatio}
                  </strong>
                </div>


                <div>
                  <span>
                    Resolution
                  </span>

                  <strong>
                    {frameResolution}
                  </strong>
                </div>

              </div>


              {/* FIT MODE */}

              {framePreset !==
                "original" && (
                <div className="fit-mode">

                  <div className="field">

                    <label>
                      How should the original
                      video fit?
                    </label>

                    <select
                      value={fitMode}
                      onChange={(event) =>
                        setFitMode(
                          event.target.value
                        )
                      }
                    >

                      <option value="crop">
                        Crop to fill frame
                      </option>

                      <option value="contain">
                        Fit entire video
                      </option>

                    </select>

                  </div>

                </div>
              )}

            </div>


            {/* =================================================
                ADVANCED
            ================================================= */}

            <div className="advanced-wrapper">

              <button
                type="button"
                className="advanced-toggle"
                onClick={() =>
                  setShowAdvanced(
                    !showAdvanced
                  )
                }
              >

                <span>
                  ⚙️ Advanced output settings
                </span>

                <span>
                  {showAdvanced
                    ? "▲"
                    : "▼"}
                </span>

              </button>


              {showAdvanced && (
                <div className="advanced-settings">

                  <div className="field">

                    <label>
                      Output format
                    </label>

                    <select
                      value={
                        outputFormat
                      }
                      onChange={(event) =>
                        setOutputFormat(
                          event.target
                            .value
                        )
                      }
                    >

                      <option value="mp4">
                        MP4
                      </option>

                      <option value="webm">
                        WebM
                      </option>

                    </select>

                  </div>


                  <div className="field">

                    <label>
                      Video quality
                    </label>

                    <select
                      value={
                        videoQuality
                      }
                      onChange={(event) =>
                        setVideoQuality(
                          event.target
                            .value
                        )
                      }
                    >

                      <option value="high">
                        High
                      </option>

                      <option value="medium">
                        Medium
                      </option>

                      <option value="low">
                        Low
                      </option>

                    </select>

                  </div>


                  <div className="field">

                    <label>
                      FPS
                    </label>

                    <select
                      value={fps}
                      onChange={(event) =>
                        setFps(
                          event.target
                            .value
                        )
                      }
                    >

                      <option value="source">
                        Keep source FPS
                      </option>

                      <option value="24">
                        24 FPS
                      </option>

                      <option value="30">
                        30 FPS
                      </option>

                      <option value="60">
                        60 FPS
                      </option>

                    </select>

                  </div>


                  <div className="field">

                    <label>
                      Starting clip number
                    </label>

                    <input
                      type="number"
                      min="0"
                      value={
                        numberStart
                      }
                      onChange={(event) =>
                        setNumberStart(
                          event.target
                            .value
                        )
                      }
                    />

                  </div>


                  <div className="field">

                    <label>
                      Filename prefix
                    </label>

                    <input
                      type="text"
                      value={
                        filenamePrefix
                      }
                      onChange={(event) =>
                        setFilenamePrefix(
                          event.target
                            .value
                        )
                      }
                      placeholder="clip"
                    />

                  </div>


                  <div className="output-preview">

                    <span>
                      Example output
                    </span>

                    <strong>
                      {filenamePrefix || "clip"}_
                      {String(
                        Number(
                          numberStart
                        ) || 1
                      ).padStart(
                        2,
                        "0"
                      )}
                      .
                      {outputFormat}
                    </strong>

                  </div>

                </div>
              )}

            </div>


            {/* =================================================
                FINAL SUMMARY
            ================================================= */}

            <div className="final-settings-summary">

              <div className="summary-item">

                <span>
                  Split mode
                </span>

                <strong>
                  {splitMode ===
                    "duration" &&
                    "By Duration"}

                  {splitMode ===
                    "parts" &&
                    "Equal Parts"}

                  {splitMode ===
                    "custom" &&
                    "Custom Timestamps"}
                </strong>

              </div>


              <div className="summary-item">

                <span>
                  Expected clips
                </span>

                <strong>
                  {generatedClipCount ||
                    "—"}
                </strong>

              </div>


              <div className="summary-item">

                <span>
                  Output frame
                </span>

                <strong>
                  {frameRatio}
                </strong>

              </div>


              <div className="summary-item">

                <span>
                  Output size
                </span>

                <strong>
                  {frameResolution}
                </strong>

              </div>

            </div>


            {/* PROCESS BUTTON */}

            <button
              type="button"
              className="create-btn"
              disabled={
                uploading ||
                processing ||
                !videoFile
              }
              onClick={
                uploadAndProcess
              }
            >

              {uploading ? (
                <>
                  <span className="spinner" />
                  Uploading {uploadProgress}%
                </>
              ) : processing ? (
                <>
                  <span className="spinner" />
                  Processing...
                </>
              ) : (
                <>
                  ✂ Create {generatedClipCount || ""} Clips
                </>
              )}

            </button>


            {processing && (
              <div className="processing-progress">

                <div className="progress-top">

                  <span>
                    Processing video...
                  </span>

                  <strong>
                    {processingProgress}%
                  </strong>

                </div>

                <div className="progress-bar">

                  <div
                    className="progress-fill"
                    style={{
                      width:
                        `${processingProgress}%`,
                    }}
                  />

                </div>

              </div>
            )}

          </section>
        )}


      </main>


      {/* =====================================================
          FOOTER
      ===================================================== */}

      <footer className="footer">

        <span>
          ClipVideo
        </span>

        <span>
          Large video clipping • Platform
          formatting • Numbered exports
        </span>

      </footer>

    </div>
  );
}

export default App;
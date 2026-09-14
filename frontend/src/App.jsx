import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const PRODUCTION_API_BASE = "https://clipvideo-production.up.railway.app";
const localHosts = new Set(["localhost", "127.0.0.1"]);
const configuredApiBase = import.meta.env.VITE_API_BASE_URL || "";
const API_BASE = (configuredApiBase || (localHosts.has(window.location.hostname) ? "" : PRODUCTION_API_BASE)).replace(/\/$/, "");
const FALLBACK_EXTENSIONS = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpeg", ".mpg"];
const DEFAULT_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024;
const FRAMES = [
  ["original", "Original", "Source resolution", null, null],
  ["instagram_reel", "Instagram Reels", "9:16 · 1080 × 1920", 1080, 1920],
  ["youtube_shorts", "YouTube Shorts", "9:16 · 1080 × 1920", 1080, 1920],
  ["tiktok", "TikTok", "9:16 · 1080 × 1920", 1080, 1920],
  ["instagram_post", "Instagram Post", "1:1 · 1080 × 1080", 1080, 1080],
  ["instagram_portrait", "Instagram Portrait", "4:5 · 1080 × 1350", 1080, 1350],
  ["youtube_landscape", "YouTube Landscape", "16:9 · 1920 × 1080", 1920, 1080],
  ["custom", "Custom", "Choose width and height", null, null],
];

const bytes = (value = 0) => value < 1024 ? `${value} B` : value < 1024 ** 2 ? `${(value / 1024).toFixed(1)} KB` : value < 1024 ** 3 ? `${(value / 1024 ** 2).toFixed(1)} MB` : `${(value / 1024 ** 3).toFixed(2)} GB`;
const seconds = (value) => {
  if (!Number.isFinite(Number(value))) return "—";
  const total = Math.round(Number(value)); const h = Math.floor(total / 3600); const m = Math.floor((total % 3600) / 60); const s = total % 60;
  return h ? `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
};
const friendlyError = (error) => error?.message || "The request could not be completed. Check your connection and try again.";

function App() {
  const input = useRef(null);
  const [file, setFile] = useState(null); const [metadata, setMetadata] = useState(null); const [dragging, setDragging] = useState(false);
  const [config, setConfig] = useState({ max_upload_size_gb: 10, upload_chunk_size: DEFAULT_UPLOAD_CHUNK_SIZE, fast_copy_workers: 4, transcode_workers: 1, ffmpeg_threads: 2, input_extensions: FALLBACK_EXTENSIONS, output_formats: [{ id: "mp4", extension: ".mp4" }] });
  const [method, setMethod] = useState("duration"); const [clipDuration, setClipDuration] = useState("60"); const [parts, setParts] = useState("5"); const [ranges, setRanges] = useState([{ start: "0", end: "" }]);
  const [numberStart, setNumberStart] = useState("1"); const [prefix, setPrefix] = useState("clip"); const [frame, setFrame] = useState("original"); const [fit, setFit] = useState("contain"); const [width, setWidth] = useState("1080"); const [height, setHeight] = useState("1920"); const [format, setFormat] = useState("mp4"); const [quality, setQuality] = useState("high");
  const [notice, setNotice] = useState(null); const [job, setJob] = useState(null); const [uploadProgress, setUploadProgress] = useState(null); const [query, setQuery] = useState(""); const [sort, setSort] = useState("number"); const [page, setPage] = useState(1);

  useEffect(() => { fetch(`${API_BASE}/api/v1/config`).then(async response => response.ok ? response.json() : Promise.reject()).then(data => { setConfig(data); }).catch(() => {}); }, []);
  useEffect(() => { if (!job?.job_id || ["completed", "failed"].includes(job.status)) return undefined; const timer = setTimeout(async () => { try { const response = await fetch(`${API_BASE}/api/v1/status/${job.job_id}`); const data = await response.json(); if (!response.ok) throw data; setJob(data); if (data.status === "failed") setNotice({ type: "error", text: friendlyError(data.error) }); } catch (error) { setNotice({ type: "error", text: `Unable to check processing status. ${friendlyError(error)}` }); } }, 1000); return () => clearTimeout(timer); }, [job]);

  const selectedFrame = FRAMES.find(([id]) => id === frame) || FRAMES[0];
  const selectedWidth = frame === "custom" ? Number(width) : selectedFrame[3]; const selectedHeight = frame === "custom" ? Number(height) : selectedFrame[4];
  const estimated = useMemo(() => { if (!metadata?.duration) return null; if (method === "duration") return Math.ceil(metadata.duration / Number(clipDuration || 0)) || null; if (method === "parts") return Number(parts) || null; return ranges.length; }, [metadata, method, clipDuration, parts, ranges.length]);
  const errors = useMemo(() => {
    if (!file) return ["Choose a video file to continue."];
    if (method === "duration" && !(Number(clipDuration) > 0)) return ["Clip duration must be greater than zero."];
    if (method === "parts" && !(Number(parts) > 0)) return ["Number of clips must be greater than zero."];
    if (method === "custom" && ranges.some(range => !(Number(range.end) > Number(range.start)) || Number(range.start) < 0)) return ["Every custom range needs an end time greater than its start time."];
    if (!(Number(numberStart) >= 0)) return ["Starting number must be zero or greater."];
    if (frame === "custom" && (!(selectedWidth > 0) || !(selectedHeight > 0))) return ["Custom width and height must be positive values."];
    return [];
  }, [file, method, clipDuration, parts, ranges, numberStart, frame, selectedWidth, selectedHeight]);
  const clips = useMemo(() => [...(job?.clips || [])].filter(clip => clip.filename.toLowerCase().includes(query.toLowerCase())).sort((a, b) => sort === "name" ? a.filename.localeCompare(b.filename) : a.number - b.number), [job?.clips, query, sort]);
  const visibleClips = clips.slice((page - 1) * 50, page * 50); const pages = Math.max(1, Math.ceil(clips.length / 50));

  function chooseFile(candidate) {
    if (!candidate) return;
    const extension = `.${candidate.name.split(".").pop()?.toLowerCase()}`;
    if (!config.input_extensions.includes(extension)) { setNotice({ type: "error", text: "Video format is not supported. Choose MP4, MOV, MKV, AVI, WEBM, M4V, MPEG, or MPG." }); return; }
    if (candidate.size > config.max_upload_size_gb * 1024 ** 3) { setNotice({ type: "error", text: `This file is larger than the ${config.max_upload_size_gb} GB upload limit.` }); return; }
    setFile(candidate); setMetadata(null); setJob(null); setNotice(null); setUploadProgress(null); setPage(1);
    const video = document.createElement("video"); video.preload = "metadata"; video.onloadedmetadata = () => { setMetadata({ duration: video.duration, width: video.videoWidth, height: video.videoHeight }); URL.revokeObjectURL(video.src); }; video.onerror = () => { setNotice({ type: "error", text: "The browser could not read this video’s metadata. You can still process it if it is valid." }); URL.revokeObjectURL(video.src); }; video.src = URL.createObjectURL(candidate);
  }
  function applyPreset(name) {
    if (name === "quick") { setMethod("duration"); setClipDuration("30"); setFrame("original"); setFormat("mp4"); }
    if (name === "social") { setMethod("duration"); setClipDuration("60"); setFrame("instagram_reel"); setFormat("mp4"); }
    if (name === "youtube") { setMethod("duration"); setClipDuration("300"); setFrame("youtube_landscape"); setFormat("mp4"); }
    if (name === "custom") { setMethod("duration"); setClipDuration("60"); setFrame("custom"); }
  }
  function buildData(includeFile = false) {
    const data = new FormData(); if (includeFile) data.append("file", file); data.append("split_mode", method); data.append("frame_preset", frame); data.append("fit_mode", fit); data.append("output_format", format); data.append("number_start", String(Number(numberStart))); data.append("filename_prefix", prefix || "clip"); data.append("video_quality", quality);
    if (method === "duration") data.append("clip_duration", String(Number(clipDuration))); if (method === "parts") data.append("number_of_parts", String(Number(parts))); if (method === "custom") data.append("custom_clips", JSON.stringify(ranges)); if (frame === "custom") { data.append("frame_width", String(selectedWidth)); data.append("frame_height", String(selectedHeight)); } return data;
  }
  function uploadChunk(uploadId, chunk, index, total, uploadedBefore) {
    return new Promise((resolve, reject) => {
      const data = new FormData(); data.append("chunk", chunk, file.name); data.append("chunk_index", String(index)); data.append("total_chunks", String(total));
      const request = new XMLHttpRequest(); request.open("POST", `${API_BASE}/api/v1/uploads/${uploadId}/chunk`); request.responseType = "json";
      request.upload.onprogress = event => { if (event.lengthComputable) setUploadProgress(Math.min(99, Math.round((uploadedBefore + event.loaded) * 100 / file.size))); };
      request.onerror = () => reject({ message: "Network error. Confirm the ClipVideo API is running, then try again." });
      request.onload = () => request.status >= 200 && request.status < 300 ? resolve(request.response || {}) : reject(request.response || { message: "Upload chunk failed." });
      request.send(data);
    });
  }
  async function submit() {
    if (errors.length) { setNotice({ type: "error", text: errors[0] }); return; }
    setNotice(null); setJob({ status: "uploading", stage: "Uploading", message: "Uploading video…", clips: [] }); setUploadProgress(0);
    try {
      const startResponse = await fetch(`${API_BASE}/api/v1/uploads/start`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: file.name, content_type: file.type || "application/octet-stream", total_size: file.size }) });
      const startData = await startResponse.json(); if (!startResponse.ok) throw startData;
      const chunkSize = Number(startData.chunk_size || config.upload_chunk_size || DEFAULT_UPLOAD_CHUNK_SIZE);
      const totalChunks = Math.ceil(file.size / chunkSize); let uploaded = 0;
      for (let index = 0; index < totalChunks; index += 1) {
        const start = index * chunkSize; const chunk = file.slice(start, Math.min(file.size, start + chunkSize));
        await uploadChunk(startData.upload_id, chunk, index, totalChunks, uploaded);
        uploaded += chunk.size; setUploadProgress(Math.min(99, Math.round(uploaded * 100 / file.size)));
      }
      setJob({ status: "uploading", stage: "Finalizing upload", message: "Finalizing upload…", clips: [] });
      const response = await fetch(`${API_BASE}/api/v1/uploads/${startData.upload_id}/complete`, { method: "POST", body: buildData(false) });
      const data = await response.json(); if (!response.ok) throw data;
      setUploadProgress(null); setJob({ ...data, status: "queued", stage: "Queued", message: "Upload complete. Preparing processing…", clips: [] });
    } catch (error) {
      setJob(null); setUploadProgress(null); setNotice({ type: "error", text: friendlyError(error) });
    }
  }
  const busy = job && !["completed", "failed"].includes(job.status);

  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="#top" aria-label="ClipVideo home"><span className="brand-mark">▶</span> ClipVideo</a><p>Cut, format, and download video clips without the clutter.</p><a href={`${API_BASE}/docs`} target="_blank" rel="noreferrer">API docs</a></header>
    <main id="top"><section className="hero"><p className="eyebrow">VIDEO CLIPPING WORKSPACE</p><h1>Make clean clips,<br /><em>on your terms.</em></h1><p>Upload one video, choose its cuts and frame, then download each finished clip or a single ZIP.</p></section>
      {notice && <div className={`notice ${notice.type}`} role="alert"><span>{notice.type === "error" ? "!" : "✓"}</span><p>{notice.text}</p><button type="button" onClick={() => setNotice(null)} aria-label="Dismiss message">×</button></div>}
      <div className="workflow"><section className="card step"><Step number="1" title="Upload video" text="Select one supported video file. Files are streamed to disk, never loaded into server memory." />
        <div className={`dropzone ${dragging ? "dragging" : ""}`} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files[0]); }}>
          <input ref={input} type="file" accept={config.input_extensions.join(",")} onChange={event => chooseFile(event.target.files[0])} />
          <div className="upload-icon">↑</div><strong>Drag and drop your video</strong><span>or</span><button type="button" className="secondary" onClick={() => input.current?.click()}>Browse file</button><small>Supported: {config.input_extensions.map(item => item.slice(1).toUpperCase()).join(", ")} · Up to {config.max_upload_size_gb} GB</small>
        </div>
        {file && <div className="file-row"><div className="file-icon">▣</div><div><strong>{file.name}</strong><span>{bytes(file.size)} · {file.type || "Video file"}</span></div><button type="button" className="icon-button" onClick={() => { setFile(null); setMetadata(null); setJob(null); input.current.value = ""; }} aria-label="Remove selected video">×</button></div>}
      </section>
      {file && <section className="card step"><Step number="2" title="Video information" text="Read from your browser before processing begins." /><div className="info-grid"><Info label="Filename" value={file.name} /><Info label="File size" value={bytes(file.size)} /><Info label="File type" value={file.type || "Unknown MIME type"} /><Info label="Duration" value={metadata ? seconds(metadata.duration) : "Reading…"} /><Info label="Resolution" value={metadata ? `${metadata.width} × ${metadata.height}` : "Reading…"} /><Info label="Video codec" value="Available after processing" /></div></section>}
      {file && <section className="card step"><Step number="3" title="Clip settings" text="Choose one way to divide the source video." /><div className="preset-row"><button type="button" onClick={() => applyPreset("quick")}>Quick Clip <span>30 sec · Original</span></button><button type="button" onClick={() => applyPreset("social")}>Social Media <span>60 sec · 9:16</span></button><button type="button" onClick={() => applyPreset("youtube")}>YouTube <span>5 min · 16:9</span></button><button type="button" onClick={() => applyPreset("custom")}>Custom <span>Editable custom frame</span></button></div><div className="segmentation">
          <label className={method === "duration" ? "selected" : ""}><input type="radio" name="method" checked={method === "duration"} onChange={() => setMethod("duration")} /> <b>By duration</b><span>Split every fixed interval.</span></label><label className={method === "parts" ? "selected" : ""}><input type="radio" name="method" checked={method === "parts"} onChange={() => setMethod("parts")} /> <b>Number of clips</b><span>Divide video into equal parts.</span></label><label className={method === "custom" ? "selected" : ""}><input type="radio" name="method" checked={method === "custom"} onChange={() => setMethod("custom")} /> <b>Custom ranges</b><span>Choose start and end points.</span></label>
        </div>
        {method === "duration" && <div className="field-line"><label htmlFor="duration">Clip duration</label><select id="duration" value={[5, 10, 15, 30, 60, 90, 120, 300].includes(Number(clipDuration)) ? clipDuration : "custom"} onChange={event => { if (event.target.value === "custom") setClipDuration(""); else setClipDuration(event.target.value); }}>{[5, 10, 15, 30, 60, 90, 120, 300].map(value => <option key={value} value={value}>{value >= 60 ? `${value / 60} minute${value > 60 ? "s" : ""}` : `${value} seconds`}</option>)}<option value="custom">Custom</option></select>{![5, 10, 15, 30, 60, 90, 120, 300].includes(Number(clipDuration)) && <input type="number" min="1" placeholder="Seconds" value={clipDuration} onChange={event => setClipDuration(event.target.value)} />}</div>}
        {method === "parts" && <div className="field-line"><label htmlFor="parts">Number of clips</label><input id="parts" type="number" min="1" max="10000" value={parts} onChange={event => setParts(event.target.value)} /></div>}
        {method === "custom" && <div className="ranges">{ranges.map((range, index) => <div className="range" key={index}><label>Range {index + 1}<input type="number" min="0" step="0.1" value={range.start} onChange={event => setRanges(ranges.map((item, itemIndex) => itemIndex === index ? { ...item, start: event.target.value } : item))} /></label><label>Start (sec)</label><label>End (sec)<input type="number" min="0" step="0.1" value={range.end} onChange={event => setRanges(ranges.map((item, itemIndex) => itemIndex === index ? { ...item, end: event.target.value } : item))} /></label>{ranges.length > 1 && <button type="button" className="icon-button" onClick={() => setRanges(ranges.filter((_, itemIndex) => itemIndex !== index))} aria-label="Remove range">×</button>}</div>)}<button type="button" className="text-button" onClick={() => setRanges([...ranges, { start: "0", end: "" }])}>+ Add range</button></div>}
      </section>}
      {file && <section className="card step"><Step number="4" title="Numbering" text="Each clip receives a predictable filename." /><div className="two-fields"><label>Starting number<input type="number" min="0" value={numberStart} onChange={event => setNumberStart(event.target.value)} /></label><label>Filename prefix<input value={prefix} maxLength="64" onChange={event => setPrefix(event.target.value)} /></label></div><p className="example-name">Example: <strong>{prefix || "clip"}_{String(Number(numberStart) || 0).padStart(3, "0")}.mp4</strong></p></section>}
      {file && <section className="card step"><Step number="5" title="Frame & format" text="A frame preset changes the video canvas. Output format is a separate setting." /><div className="frame-grid">{FRAMES.map(([id, name, detail]) => <button type="button" key={id} className={frame === id ? "frame active" : "frame"} onClick={() => setFrame(id)}><strong>{name}</strong><span>{detail}</span></button>)}</div>{frame === "custom" && <div className="two-fields custom-size"><label>Width (px)<input type="number" min="1" max="7680" value={width} onChange={event => setWidth(event.target.value)} /></label><label>Height (px)<input type="number" min="1" max="7680" value={height} onChange={event => setHeight(event.target.value)} /></label></div>}{frame !== "original" && <div className="field-line"><label htmlFor="fit">Frame fit</label><select id="fit" value={fit} onChange={event => setFit(event.target.value)}><option value="contain">Fit entire video (letterbox)</option><option value="crop">Crop to fill</option><option value="stretch">Stretch</option></select></div>}<div className="two-fields advanced"><label>Output format<select value={format} onChange={event => setFormat(event.target.value)}>{config.output_formats.map(item => <option key={item.id} value={item.id}>{item.id.toUpperCase()}</option>)}</select></label><label>Transcode quality<select value={quality} onChange={event => setQuality(event.target.value)}><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label></div></section>}
      {file && <aside className="summary"><div><p className="eyebrow">READY TO PROCESS</p><h2>Settings summary</h2></div><dl><Summary label="Source" value={file.name} /><Summary label="Duration" value={metadata ? seconds(metadata.duration) : "Unknown"} /><Summary label="Clipping" value={method === "duration" ? `${clipDuration} sec` : method === "parts" ? `${parts} equal clips` : `${ranges.length} custom ranges`} /><Summary label="Estimated clips" value={estimated || "—"} /><Summary label="Starting number" value={numberStart} /><Summary label="Frame" value={frame === "original" ? "Original" : selectedFrame[2]} /><Summary label="Output" value={format.toUpperCase()} /></dl><button type="button" className="primary create" disabled={Boolean(errors.length) || busy} onClick={submit}>{busy ? "Processing…" : `Create${estimated ? ` ${estimated}` : ""} Clips`}</button>{errors.length > 0 && <p className="validation">{errors[0]}</p>}<p className="speed-note">Laptop-safe mode: original clips use up to {config.fast_copy_workers} fast-copy workers; frame conversion uses {config.transcode_workers} worker(s) × {config.ffmpeg_threads} FFmpeg thread(s).</p></aside>}
      {job && <section className="card processing"><div><p className="eyebrow">{job.stage || "PROCESSING"}</p><h2>{job.status === "completed" ? "Clips ready" : job.status === "failed" ? "Processing failed" : job.message}</h2><p>{job.status === "uploading" ? `Uploading ${uploadProgress ?? 0}%` : job.message}</p></div>{job.status !== "failed" && <div className="progress"><div style={{ width: `${job.status === "uploading" ? uploadProgress ?? 0 : job.progress ?? 0}%` }} /></div>}{job.total_clips > 0 && <span>{job.progress_label || `${job.current_clip || 0} of ${job.total_clips} clips`}</span>}</section>}
      {job?.status === "completed" && <section className="card results"><div className="results-head"><div><p className="eyebrow">CLIPS READY</p><h2>{job.clips.length} clips generated successfully.</h2></div><a className="primary" href={`${API_BASE}${job.zip_url}`} download>Download all ZIP</a></div><div className="result-controls"><input aria-label="Search clips" placeholder="Search clips…" value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} /><select aria-label="Sort clips" value={sort} onChange={event => { setSort(event.target.value); setPage(1); }}><option value="number">Sort: Number</option><option value="name">Sort: Name</option></select></div><div className="clip-list">{visibleClips.map(clip => <div className="clip" key={clip.filename}><div><strong>{clip.filename}</strong><span>{seconds(clip.start)} – {seconds(clip.end)} · {bytes(clip.size)}</span></div><a href={`${API_BASE}${clip.download_url}`} download={clip.filename}>Download</a></div>)}{!visibleClips.length && <p className="empty">No clips match your search.</p>}</div>{pages > 1 && <div className="pagination"><button disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page} of {pages}</span><button disabled={page === pages} onClick={() => setPage(page + 1)}>Next</button></div>}</section>}
      </div>
    </main><footer>ClipVideo · Files and downloads are retained for {config.retention_hours || 24} hours.</footer>
  </div>;
}
function Step({ number, title, text }) { return <div className="step-title"><span>{number}</span><div><h2>{title}</h2><p>{text}</p></div></div>; }
function Info({ label, value }) { return <div><span>{label}</span><strong title={value}>{value}</strong></div>; }
function Summary({ label, value }) { return <><dt>{label}</dt><dd title={String(value)}>{value}</dd></>; }
export default App;

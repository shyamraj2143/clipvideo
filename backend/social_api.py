"""Additive ClipVideo Social Hub.

The existing clipping API is intentionally left untouched. This router adds
server-side scheduling and publishing adapters for Instagram, Facebook,
Threads, YouTube and X. OAuth credentials/tokens are stored server-side.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/api/v1/social", tags=["Social Publisher"])
API_VERSION = os.getenv("META_GRAPH_VERSION", "v25.0")
PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE_URL", "https://clipvideo-production.up.railway.app").rstrip("/")
SOCIAL_OWNER = os.getenv("SOCIAL_OWNER_ID", "default")
_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "")
DB_PATH = Path(os.getenv("SOCIAL_DB_PATH", str(Path(_mount) / "social.db" if _mount else Path(__file__).resolve().parent / "storage" / "social.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
TOKEN_KEY = os.getenv("SOCIAL_TOKEN_KEY", "")
fernet = Fernet(TOKEN_KEY.encode()) if TOKEN_KEY else None
DB_LOCK = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with DB_LOCK, db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS oauth_state (state TEXT PRIMARY KEY, provider TEXT NOT NULL, verifier TEXT, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS social_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id TEXT NOT NULL, provider TEXT NOT NULL,
            external_id TEXT NOT NULL, display_name TEXT NOT NULL, token_blob TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            UNIQUE(owner_id, provider, external_id)
        );
        CREATE TABLE IF NOT EXISTS social_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id TEXT NOT NULL, account_id INTEGER NOT NULL,
            media_url TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
            scheduled_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled', remote_id TEXT, error TEXT,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            FOREIGN KEY(account_id) REFERENCES social_accounts(id)
        );
        CREATE INDEX IF NOT EXISTS idx_social_posts_due ON social_posts(status, scheduled_at);
        """)


init_db()


def now_ts() -> int:
    return int(time.time())


def require_crypto():
    if not fernet:
        raise HTTPException(503, "Set SOCIAL_TOKEN_KEY before connecting social accounts.")


def encrypt(value: dict[str, Any]) -> str:
    require_crypto()
    return fernet.encrypt(json.dumps(value).encode()).decode()


def decrypt(value: str) -> dict[str, Any]:
    require_crypto()
    return json.loads(fernet.decrypt(value.encode()).decode())


def oauth_redirect(provider: str) -> str:
    env = {"meta": "META_REDIRECT_URI", "threads": "THREADS_REDIRECT_URI", "youtube": "YOUTUBE_REDIRECT_URI", "x": "X_REDIRECT_URI"}[provider]
    return os.getenv(env, f"{PUBLIC_API_BASE}/api/v1/social/auth/{provider}/callback")


def put_account(provider: str, external_id: str, display_name: str, token: dict[str, Any], metadata: dict[str, Any] | None = None):
    ts = now_ts()
    with DB_LOCK, db() as conn:
        conn.execute("""INSERT INTO social_accounts(owner_id,provider,external_id,display_name,token_blob,metadata_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(owner_id,provider,external_id) DO UPDATE SET display_name=excluded.display_name,
            token_blob=excluded.token_blob, metadata_json=excluded.metadata_json, updated_at=excluded.updated_at""",
            (SOCIAL_OWNER, provider, external_id, display_name, encrypt(token), json.dumps(metadata or {}), ts, ts))


def account_rows():
    with DB_LOCK, db() as conn:
        rows = conn.execute("SELECT id,provider,external_id,display_name,metadata_json FROM social_accounts WHERE owner_id=? ORDER BY provider,display_name", (SOCIAL_OWNER,)).fetchall()
    return [{"id": r[0], "provider": r[1], "external_id": r[2], "display_name": r[3], "metadata": json.loads(r[4] or "{}")} for r in rows]


def account(account_id: int):
    with DB_LOCK, db() as conn:
        row = conn.execute("SELECT * FROM social_accounts WHERE id=? AND owner_id=?", (account_id, SOCIAL_OWNER)).fetchone()
    if not row:
        raise HTTPException(404, "Social account not found.")
    return row


@router.get("/health")
def social_health():
    return {"enabled": True, "token_storage_configured": bool(TOKEN_KEY), "accounts": len(account_rows())}


@router.get("/providers")
def providers():
    return {
        "instagram": {"label": "Instagram", "configured": bool(os.getenv("META_APP_ID")), "kind": "meta"},
        "facebook": {"label": "Facebook", "configured": bool(os.getenv("META_APP_ID")), "kind": "meta"},
        "threads": {"label": "Threads", "configured": bool(os.getenv("THREADS_APP_ID"))},
        "youtube": {"label": "YouTube", "configured": bool(os.getenv("GOOGLE_CLIENT_ID"))},
        "x": {"label": "X", "configured": bool(os.getenv("X_CLIENT_ID"))},
    }


@router.get("/accounts")
def accounts():
    return {"accounts": account_rows()}


@router.get("/auth/{provider}/start")
def oauth_start(provider: str):
    if provider == "meta":
        client_id = os.getenv("META_APP_ID")
        if not client_id: raise HTTPException(503, "META_APP_ID is not configured.")
        state = secrets.token_urlsafe(32)
        with DB_LOCK, db() as conn: conn.execute("INSERT INTO oauth_state VALUES(?,?,?,?)", (state, provider, None, now_ts()))
        params = {"client_id": client_id, "redirect_uri": oauth_redirect("meta"), "state": state, "response_type": "code", "scope": "pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish"}
        return RedirectResponse("https://www.facebook.com/dialog/oauth?" + urlencode(params))
    if provider == "threads":
        client_id = os.getenv("THREADS_APP_ID")
        if not client_id: raise HTTPException(503, "THREADS_APP_ID is not configured.")
        state = secrets.token_urlsafe(32)
        with DB_LOCK, db() as conn: conn.execute("INSERT INTO oauth_state VALUES(?,?,?,?)", (state, provider, None, now_ts()))
        params = {"client_id": client_id, "redirect_uri": oauth_redirect("threads"), "scope": "threads_basic,threads_content_publish", "response_type": "code", "state": state}
        return RedirectResponse("https://threads.net/oauth/authorize?" + urlencode(params))
    if provider == "youtube":
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        if not client_id: raise HTTPException(503, "GOOGLE_CLIENT_ID is not configured.")
        state = secrets.token_urlsafe(32)
        with DB_LOCK, db() as conn: conn.execute("INSERT INTO oauth_state VALUES(?,?,?,?)", (state, provider, None, now_ts()))
        params = {"client_id": client_id, "redirect_uri": oauth_redirect("youtube"), "response_type": "code", "scope": "https://www.googleapis.com/auth/youtube.upload", "access_type": "offline", "prompt": "consent", "state": state}
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))
    if provider == "x":
        client_id = os.getenv("X_CLIENT_ID")
        if not client_id: raise HTTPException(503, "X_CLIENT_ID is not configured.")
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(32)
        with DB_LOCK, db() as conn: conn.execute("INSERT INTO oauth_state VALUES(?,?,?,?)", (state, provider, verifier, now_ts()))
        params = {"response_type": "code", "client_id": client_id, "redirect_uri": oauth_redirect("x"), "scope": "tweet.read tweet.write users.read media.write offline.access", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
        return RedirectResponse("https://x.com/i/oauth2/authorize?" + urlencode(params))
    raise HTTPException(404, "Unsupported provider.")


async def state_row(state: str, provider: str):
    with DB_LOCK, db() as conn:
        row = conn.execute("SELECT * FROM oauth_state WHERE state=? AND provider=?", (state, provider)).fetchone()
        conn.execute("DELETE FROM oauth_state WHERE state=?", (state,))
    if not row or now_ts() - row[3] > 600: raise HTTPException(400, "OAuth state expired or invalid.")
    return row


@router.get("/auth/meta/callback")
async def meta_callback(code: str = Query(...), state: str = Query(...)):
    await state_row(state, "meta")
    async with httpx.AsyncClient(timeout=30) as client:
        token = (await client.get("https://graph.facebook.com/oauth/access_token", params={"client_id": os.getenv("META_APP_ID"), "client_secret": os.getenv("META_APP_SECRET"), "redirect_uri": oauth_redirect("meta"), "code": code})).json()
        if "access_token" not in token: raise HTTPException(400, f"Meta OAuth failed: {token}")
        user_token = token["access_token"]
        pages = (await client.get(f"https://graph.facebook.com/{API_VERSION}/me/accounts", params={"fields": "id,name,access_token,instagram_business_account", "access_token": user_token})).json().get("data", [])
        for page in pages:
            put_account("facebook", page["id"], page.get("name", "Facebook Page"), {"access_token": page["access_token"], "page_id": page["id"]})
            ig = page.get("instagram_business_account")
            if ig:
                put_account("instagram", ig["id"], f"Instagram via {page.get('name','Facebook Page')}", {"access_token": page["access_token"], "ig_user_id": ig["id"], "page_id": page["id"]})
    return RedirectResponse("/social/")


@router.get("/auth/threads/callback")
async def threads_callback(code: str = Query(...), state: str = Query(...)):
    await state_row(state, "threads")
    async with httpx.AsyncClient(timeout=30) as client:
        token = (await client.post("https://graph.threads.net/oauth/access_token", data={"client_id": os.getenv("THREADS_APP_ID"), "client_secret": os.getenv("THREADS_APP_SECRET"), "code": code, "grant_type": "authorization_code", "redirect_uri": oauth_redirect("threads")})).json()
        if "access_token" not in token: raise HTTPException(400, f"Threads OAuth failed: {token}")
        access = token["access_token"]
        profile = (await client.get("https://graph.threads.net/me", params={"fields": "id,username", "access_token": access})).json()
        put_account("threads", profile["id"], "@" + profile.get("username", profile["id"]), {"access_token": access, "threads_user_id": profile["id"]})
    return RedirectResponse("/social/")


@router.get("/auth/youtube/callback")
async def youtube_callback(code: str = Query(...), state: str = Query(...)):
    await state_row(state, "youtube")
    async with httpx.AsyncClient(timeout=30) as client:
        token = (await client.post("https://oauth2.googleapis.com/token", data={"client_id": os.getenv("GOOGLE_CLIENT_ID"), "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"), "code": code, "grant_type": "authorization_code", "redirect_uri": oauth_redirect("youtube")})).json()
        if "access_token" not in token: raise HTTPException(400, f"Google OAuth failed: {token}")
        headers = {"Authorization": "Bearer " + token["access_token"]}
        channels = (await client.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"}, headers=headers)).json().get("items", [])
        if not channels: raise HTTPException(400, "No YouTube channel was returned for this Google account.")
        channel = channels[0]
        put_account("youtube", channel["id"], channel["snippet"]["title"], token, {"channel_id": channel["id"]})
    return RedirectResponse("/social/")


@router.get("/auth/x/callback")
async def x_callback(code: str = Query(...), state: str = Query(...)):
    row = await state_row(state, "x")
    client_id = os.getenv("X_CLIENT_ID")
    basic = base64.b64encode((client_id + ":" + os.getenv("X_CLIENT_SECRET", "")).encode()).decode()
    async with httpx.AsyncClient(timeout=30) as client:
        token = (await client.post("https://api.x.com/2/oauth2/token", headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": "Basic " + basic}, data={"code": code, "grant_type": "authorization_code", "redirect_uri": oauth_redirect("x"), "client_id": client_id, "code_verifier": row[2]})).json()
        if "access_token" not in token: raise HTTPException(400, f"X OAuth failed: {token}")
        profile = (await client.get("https://api.x.com/2/users/me", headers={"Authorization": "Bearer " + token["access_token"]})).json().get("data")
        if not profile: raise HTTPException(400, "X profile lookup failed.")
        put_account("x", profile["id"], "@" + profile.get("username", profile["id"]), token, {"user_id": profile["id"]})
    return RedirectResponse("/social/")


def public_media_url(media_url: str) -> str:
    return media_url if media_url.startswith(("http://", "https://")) else PUBLIC_API_BASE + "/" + media_url.lstrip("/")


async def publish_instagram(row, post):
    token = decrypt(row[5]); ig_id = token["ig_user_id"]
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"https://graph.facebook.com/{API_VERSION}/{ig_id}/media", params={"media_type": "REELS", "video_url": public_media_url(post[3]), "caption": post[4], "share_to_feed": "true", "access_token": token["access_token"]})
        data = r.json(); r.raise_for_status(); container = data.get("id")
        if not container: raise RuntimeError(f"Instagram container creation failed: {data}")
        for _ in range(40):
            status = (await client.get(f"https://graph.facebook.com/{API_VERSION}/{container}", params={"fields": "status_code,status", "access_token": token["access_token"]})).json()
            if status.get("status_code") == "FINISHED": break
            if status.get("status_code") in {"ERROR", "EXPIRED"}: raise RuntimeError(str(status))
            await __import__("asyncio").sleep(3)
        result = await client.post(f"https://graph.facebook.com/{API_VERSION}/{ig_id}/media_publish", params={"creation_id": container, "access_token": token["access_token"]})
        result.raise_for_status(); return result.json().get("id")


async def publish_facebook(row, post):
    token = decrypt(row[5]); page_id = token["page_id"]
    async with httpx.AsyncClient(timeout=90) as client:
        start = await client.post(f"https://graph.facebook.com/{API_VERSION}/{page_id}/video_reels", params={"access_token": token["access_token"], "upload_phase": "start"})
        start.raise_for_status(); data = start.json()
        upload = await client.post(data["upload_url"], headers={"Authorization": "OAuth " + token["access_token"], "file_url": public_media_url(post[3])})
        upload.raise_for_status()
        finish = await client.post(f"https://graph.facebook.com/{API_VERSION}/{page_id}/video_reels", params={"access_token": token["access_token"], "video_id": data["video_id"], "upload_phase": "finish", "video_state": "PUBLISHED", "description": post[4]})
        finish.raise_for_status(); return data["video_id"]


async def publish_threads(row, post):
    token = decrypt(row[5]); user_id = token["threads_user_id"]
    async with httpx.AsyncClient(timeout=90) as client:
        container = await client.post(f"https://graph.threads.net/{user_id}/threads", params={"media_type": "VIDEO", "video_url": public_media_url(post[3]), "text": post[4], "access_token": token["access_token"]})
        container.raise_for_status(); creation_id = container.json()["id"]
        for _ in range(40):
            status = (await client.get(f"https://graph.threads.net/{creation_id}", params={"fields": "status", "access_token": token["access_token"]})).json().get("status")
            if status == "FINISHED": break
            if status in {"ERROR", "EXPIRED"}: raise RuntimeError(f"Threads container status: {status}")
            await __import__("asyncio").sleep(3)
        result = await client.post(f"https://graph.threads.net/{user_id}/threads_publish", params={"creation_id": creation_id, "access_token": token["access_token"]})
        result.raise_for_status(); return result.json().get("id")


async def publish_youtube(row, post):
    token = decrypt(row[5]); access = token["access_token"]
    if token.get("expires_at", 0) and token["expires_at"] < now_ts() + 60 and token.get("refresh_token"):
        async with httpx.AsyncClient(timeout=30) as client:
            refreshed = (await client.post("https://oauth2.googleapis.com/token", data={"client_id": os.getenv("GOOGLE_CLIENT_ID"), "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"), "refresh_token": token["refresh_token"], "grant_type": "refresh_token"})).json()
            if "access_token" in refreshed:
                access = refreshed["access_token"]; token.update(refreshed); put_account("youtube", row[3], row[4], token, json.loads(row[6] or "{}"))
    video = {"snippet": {"title": post[5] or post[4][:95] or "ClipVideo", "description": post[4]}, "status": {"privacyStatus": "public"}}
    async with httpx.AsyncClient(timeout=120) as client:
        content = await client.get(public_media_url(post[3])); content.raise_for_status()
        start = await client.post("https://www.googleapis.com/upload/youtube/v3/videos", params={"part": "snippet,status", "uploadType": "resumable"}, headers={"Authorization": "Bearer " + access, "Content-Type": "application/json; charset=UTF-8"}, json=video)
        start.raise_for_status(); upload_url = start.headers.get("location")
        if not upload_url: raise RuntimeError("YouTube did not return a resumable upload URL.")
        result = await client.put(upload_url, headers={"Authorization": "Bearer " + access, "Content-Type": "video/mp4", "Content-Length": str(len(content.content))}, content=content.content)
        result.raise_for_status(); return result.json().get("id")


async def publish_x(row, post):
    token = decrypt(row[5]); access = token["access_token"]
    async with httpx.AsyncClient(timeout=120) as client:
        media = await client.get(public_media_url(post[3])); media.raise_for_status(); blob = media.content
        init = await client.post("https://api.x.com/2/media/upload/initialize", headers={"Authorization": "Bearer " + access, "Content-Type": "application/json"}, json={"media_category": "tweet_video", "media_type": "video/mp4", "total_bytes": len(blob), "shared": True})
        init.raise_for_status(); media_id = init.json()["data"]["id"]
        chunk_size = 4 * 1024 * 1024
        for index in range(0, len(blob), chunk_size):
            part = blob[index:index + chunk_size]
            r = await client.post("https://api.x.com/2/media/upload", headers={"Authorization": "Bearer " + access}, data={"command": "APPEND", "media_id": media_id, "segment_index": str(index // chunk_size)}, files={"media": ("clip.mp4", part, "video/mp4")})
            r.raise_for_status()
        final = await client.post("https://api.x.com/2/media/upload", headers={"Authorization": "Bearer " + access}, data={"command": "FINALIZE", "media_id": media_id})
        final.raise_for_status(); info = final.json().get("data", {}).get("processing_info")
        for _ in range(60):
            if not info or info.get("state") == "succeeded": break
            if info.get("state") == "failed": raise RuntimeError(str(info))
            await __import__("asyncio").sleep(max(1, int(info.get("check_after_secs", 2))))
            status = await client.get("https://api.x.com/2/media/upload", params={"command": "STATUS", "media_id": media_id}, headers={"Authorization": "Bearer " + access})
            status.raise_for_status(); info = status.json().get("data", {}).get("processing_info")
        result = await client.post("https://api.x.com/2/tweets", headers={"Authorization": "Bearer " + access, "Content-Type": "application/json"}, json={"text": post[4], "media": {"media_ids": [media_id]}})
        result.raise_for_status(); return result.json().get("data", {}).get("id")


PUBLISHERS = {"instagram": publish_instagram, "facebook": publish_facebook, "threads": publish_threads, "youtube": publish_youtube, "x": publish_x}


async def process_post(post_id: int):
    with DB_LOCK, db() as conn:
        post = conn.execute("SELECT * FROM social_posts WHERE id=? AND owner_id=?", (post_id, SOCIAL_OWNER)).fetchone()
    if not post: return
    row = account(post[2]); provider = row[2]
    try:
        remote = await PUBLISHERS[provider](row, post)
        with DB_LOCK, db() as conn: conn.execute("UPDATE social_posts SET status='published',remote_id=?,error=NULL,updated_at=? WHERE id=?", (remote, now_ts(), post_id))
    except Exception as exc:
        with DB_LOCK, db() as conn: conn.execute("UPDATE social_posts SET status='failed',error=?,updated_at=? WHERE id=?", (str(exc)[:2000], now_ts(), post_id))


async def scheduler_tick():
    with DB_LOCK, db() as conn:
        due = conn.execute("SELECT id FROM social_posts WHERE owner_id=? AND status='scheduled' AND scheduled_at<=? ORDER BY scheduled_at LIMIT 3", (SOCIAL_OWNER, datetime.now(timezone.utc).isoformat())).fetchall()
        for row in due: conn.execute("UPDATE social_posts SET status='publishing',updated_at=? WHERE id=?", (now_ts(), row[0]))
    for row in due: await process_post(row[0])


def scheduler_loop():
    import asyncio
    while True:
        try: asyncio.run(scheduler_tick())
        except Exception: pass
        time.sleep(20)


threading.Thread(target=scheduler_loop, name="clipvideo-social-scheduler", daemon=True).start()


@router.post("/posts/bulk")
def schedule_posts(payload: dict[str, Any]):
    posts = payload.get("posts") or []
    if not posts or len(posts) > 1000: raise HTTPException(400, "posts must contain 1-1000 items.")
    created = []; ts = now_ts()
    with DB_LOCK, db() as conn:
        for item in posts:
            account_id = int(item["account_id"]); account(account_id)
            scheduled = datetime.fromisoformat(str(item["scheduled_at"]).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
            cur = conn.execute("INSERT INTO social_posts(owner_id,account_id,media_url,caption,title,scheduled_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (SOCIAL_OWNER, account_id, str(item["media_url"]), str(item.get("caption", "")), str(item.get("title", "")), scheduled, "scheduled", ts, ts))
            created.append(cur.lastrowid)
    return {"created": len(created), "ids": created}


@router.get("/posts")
def list_posts(limit: int = 200):
    limit = max(1, min(limit, 1000))
    with DB_LOCK, db() as conn:
        rows = conn.execute("SELECT p.*,a.provider,a.display_name FROM social_posts p JOIN social_accounts a ON a.id=p.account_id WHERE p.owner_id=? ORDER BY p.scheduled_at LIMIT ?", (SOCIAL_OWNER, limit)).fetchall()
    return {"posts": [dict(r) for r in rows]}


@router.delete("/posts/{post_id}")
def cancel_post(post_id: int):
    with DB_LOCK, db() as conn:
        cur = conn.execute("UPDATE social_posts SET status='cancelled',updated_at=? WHERE id=? AND owner_id=? AND status='scheduled'", (now_ts(), post_id, SOCIAL_OWNER))
    if cur.rowcount == 0: raise HTTPException(404, "Scheduled post not found or already processed.")
    return {"cancelled": True}

"""
Optional web UI for gallerydl-bot.

Provides a lightweight HTTP status page so PaaS platforms (Render, Railway,
Heroku, Fly.io, etc.) have a public endpoint to probe and keep the dyno alive.

Enable with ``WEBUI=true`` in your environment.  The server binds to
``WEBUI_HOST`` (default ``0.0.0.0``) on ``WEBUI_PORT`` (default ``8080``).

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Review it carefully before deploying to production.
"""

import json
import logging
import time
from typing import TYPE_CHECKING

try:
    from aiohttp import web as _aio_web
    _AIOHTTP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _AIOHTTP_AVAILABLE = False

try:
    import psutil as _psutil
    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PSUTIL_AVAILABLE = False

from task_manager import task_manager

logger = logging.getLogger(__name__)

# Recorded when this module is first imported (i.e. when the bot starts).
_BOT_START_TIME: float = time.monotonic()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_uptime(seconds: float) -> str:
    """Return a human-readable uptime string like ``2d 4h 32m 10s``."""
    secs = int(seconds)
    d, secs = divmod(secs, 86400)
    h, secs = divmod(secs, 3600)
    m, s = divmod(secs, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def collect_stats() -> dict:
    """Gather system and bot statistics into a plain dict.

    Returns keys: ``status``, ``uptime_seconds``, ``uptime_human``,
    ``active_jobs``.  When *psutil* is available the dict also includes
    ``cpu_percent``, ``memory_used_mb``, ``memory_total_mb``,
    ``memory_percent``, ``disk_used_gb``, ``disk_total_gb``,
    ``disk_percent``.
    """
    uptime_secs = time.monotonic() - _BOT_START_TIME

    stats: dict = {
        "status": "running",
        "uptime_seconds": int(uptime_secs),
        "uptime_human": format_uptime(uptime_secs),
        "active_jobs": task_manager.count_active_jobs(),
    }

    if _PSUTIL_AVAILABLE:
        cpu = _psutil.cpu_percent(interval=None)
        mem = _psutil.virtual_memory()
        disk = _psutil.disk_usage("/")
        stats.update(
            {
                "cpu_percent": round(cpu, 1),
                "memory_used_mb": mem.used // (1024 * 1024),
                "memory_total_mb": mem.total // (1024 * 1024),
                "memory_percent": round(mem.percent, 1),
                "disk_used_gb": disk.used // (1024 ** 3),
                "disk_total_gb": disk.total // (1024 ** 3),
                "disk_percent": round(disk.percent, 1),
            }
        )

    return stats


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>gallerydl-bot status</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      max-width: 640px;
      margin: 2rem auto;
      padding: 0 1rem;
      color: #1f2937;
      background: #f9fafb;
    }}
    h1 {{ display: flex; align-items: center; gap: .5rem; font-size: 1.5rem; }}
    .badge {{
      background: #22c55e;
      color: #fff;
      border-radius: 9999px;
      padding: .2rem .7rem;
      font-size: .75rem;
      font-weight: 600;
      letter-spacing: .03em;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 1.25rem;
      background: #fff;
      border-radius: .5rem;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(0,0,0,.08);
    }}
    th, td {{
      padding: .55rem .85rem;
      text-align: left;
      border-bottom: 1px solid #e5e7eb;
    }}
    th {{
      font-weight: 600;
      width: 40%;
      background: #f3f4f6;
    }}
    tr:last-child th, tr:last-child td {{ border-bottom: none; }}
    .footer {{
      margin-top: 1.5rem;
      font-size: .8rem;
      color: #6b7280;
    }}
    a {{ color: #3b82f6; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <h1>gallerydl-bot <span class="badge">running</span></h1>
  <table>
    <tr><th>Uptime</th><td>{uptime_human}</td></tr>
    <tr><th>Active jobs</th><td>{active_jobs}</td></tr>
    {cpu_row}
    {mem_row}
    {disk_row}
  </table>
  <p class="footer">
    <a href="/health">JSON health endpoint</a> &middot;
    <a href="https://github.com/mikf/gallery-dl">gallery-dl</a>
  </p>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Request handlers
# ---------------------------------------------------------------------------

async def _handle_index(request: object) -> object:
    """Serve the HTML status page."""
    stats = collect_stats()
    cpu_row = mem_row = disk_row = ""
    if _PSUTIL_AVAILABLE:
        cpu_row = f"<tr><th>CPU</th><td>{stats['cpu_percent']:.1f}%</td></tr>"
        mem_row = (
            f"<tr><th>Memory</th><td>"
            f"{stats['memory_used_mb']} MB / {stats['memory_total_mb']} MB"
            f" ({stats['memory_percent']:.1f}%)</td></tr>"
        )
        disk_row = (
            f"<tr><th>Disk</th><td>"
            f"{stats['disk_used_gb']} GB / {stats['disk_total_gb']} GB"
            f" ({stats['disk_percent']:.1f}%)</td></tr>"
        )
    html = _HTML_TEMPLATE.format(
        uptime_human=stats["uptime_human"],
        active_jobs=stats["active_jobs"],
        cpu_row=cpu_row,
        mem_row=mem_row,
        disk_row=disk_row,
    )
    return _aio_web.Response(text=html, content_type="text/html")  # type: ignore[attr-defined]


async def _handle_health(request: object) -> object:
    """Serve the JSON health/stats endpoint."""
    stats = collect_stats()
    return _aio_web.Response(  # type: ignore[attr-defined]
        text=json.dumps(stats, indent=2),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

async def start_webui(host: str, port: int) -> None:
    """Create and start the aiohttp web server in the current event loop.

    This is a non-blocking call: the server runs as a background task and
    the coroutine returns once the TCP socket is bound and listening.

    Args:
        host: Interface to bind to (e.g. ``"0.0.0.0"``).
        port: Port number to listen on (e.g. ``8080``).
    """
    if not _AIOHTTP_AVAILABLE:
        logger.error(
            "WEBUI=true but aiohttp is not installed. "
            "Ensure all requirements.txt dependencies are installed: pip install -r requirements.txt"
        )
        return

    app = _aio_web.Application()
    app.router.add_get("/", _handle_index)
    app.router.add_get("/health", _handle_health)

    runner = _aio_web.AppRunner(app)
    await runner.setup()
    site = _aio_web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Web UI listening on http://%s:%d", host, port)

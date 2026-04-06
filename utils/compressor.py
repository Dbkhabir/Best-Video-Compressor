import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional, Callable, Awaitable

log = logging.getLogger("vbot.compressor")

FFPROBE_TIMEOUT = 30
FFMPEG_LINE_TIMEOUT = 120
FFMPEG_WAIT_TIMEOUT = 60


async def get_video_duration(file_path: Path) -> float:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=FFPROBE_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            log.warning("ffprobe timed out for %s", file_path.name)
            return 0
        data = json.loads(stdout.decode())
        return float(data.get("format", {}).get("duration", 0))
    except Exception as e:
        log.warning("ffprobe failed: %s", e)
        return 0


async def get_video_info(file_path: Path) -> dict:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=FFPROBE_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            log.warning("ffprobe info timed out for %s", file_path.name)
            return {"duration": 0, "width": 0, "height": 0, "codec": ""}
        data = json.loads(stdout.decode())
        info = {"duration": 0, "width": 0, "height": 0, "codec": ""}
        fmt = data.get("format", {})
        info["duration"] = float(fmt.get("duration", 0))
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"] = stream.get("width", 0)
                info["height"] = stream.get("height", 0)
                info["codec"] = stream.get("codec_name", "")
                break
        return info
    except Exception as e:
        log.warning("ffprobe info failed: %s", e)
        return {"duration": 0, "width": 0, "height": 0, "codec": ""}


async def extract_thumbnail(file_path: Path, output_path: Path, time_pos: float = 1.0) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-ss", str(time_pos),
            "-i", str(file_path),
            "-vframes", "1",
            "-vf", "scale=320:-2",
            "-q:v", "5",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=FFPROBE_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False
        if not output_path.exists():
            return False
        if output_path.stat().st_size > 200 * 1024:
            tmp_thumb = output_path.with_name("thumb_tmp.jpg")
            proc2 = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", str(output_path),
                "-vf", "scale=160:-2",
                "-q:v", "8",
                str(tmp_thumb),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc2.communicate(), timeout=FFPROBE_TIMEOUT)
            except asyncio.TimeoutError:
                proc2.kill()
                await proc2.wait()
            if tmp_thumb.exists() and tmp_thumb.stat().st_size > 0:
                tmp_thumb.replace(output_path)
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception:
        return False


async def compress_video(
    input_path: Path,
    output_path: Path,
    crf: str = "28",
    preset: str = "medium",
    resolution: Optional[int] = None,
    cancel_event: Optional[asyncio.Event] = None,
    progress_callback: Optional[Callable[[float, float], Awaitable[None]]] = None,
) -> bool:
    duration = await get_video_duration(input_path)
    if duration <= 0:
        duration = 1.0

    vf_parts = []
    if resolution:
        vf_parts.append(f"scale=-2:{resolution}")

    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c:v", "libx264",
        "-crf", crf,
        "-preset", preset,
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
    ]

    if vf_parts:
        cmd.extend(["-vf", ",".join(vf_parts)])

    cmd.append(str(output_path))

    log.info("FFmpeg cmd: %s", " ".join(cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    time_pattern = re.compile(r"out_time_us=(\d+)")

    try:
        while True:
            if cancel_event and cancel_event.is_set():
                proc.kill()
                await proc.wait()
                return False

            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=FFMPEG_LINE_TIMEOUT)
            except asyncio.TimeoutError:
                log.warning("FFmpeg output stalled (no line for %ds), killing process", FFMPEG_LINE_TIMEOUT)
                proc.kill()
                await proc.wait()
                return False

            if not line:
                break

            decoded = line.decode("utf-8", errors="ignore").strip()
            match = time_pattern.search(decoded)
            if match and progress_callback:
                current_us = int(match.group(1))
                current_sec = current_us / 1_000_000
                pct = min((current_sec / duration) * 100, 99.9)
                try:
                    await progress_callback(pct, duration)
                except asyncio.CancelledError:
                    proc.kill()
                    await proc.wait()
                    return False
                except Exception as e:
                    log.debug("compress progress_callback error: %s", e)

    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        return False

    try:
        await asyncio.wait_for(proc.wait(), timeout=FFMPEG_WAIT_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("FFmpeg wait timed out, killing process")
        proc.kill()
        await proc.wait()
        return False

    if proc.returncode != 0:
        stderr_out = await proc.stderr.read()
        log.error("FFmpeg error (rc=%d): %s", proc.returncode, stderr_out.decode("utf-8", errors="ignore")[:500])
        return False

    if progress_callback:
        try:
            await progress_callback(100.0, duration)
        except Exception:
            pass

    return output_path.exists() and output_path.stat().st_size > 0

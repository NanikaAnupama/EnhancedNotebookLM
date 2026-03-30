"""
core.py — Video processing engine for the SLC pipeline.
All Pillow overlays, FFmpeg logic, OneDrive upload, and the main
process_single_job() orchestrator live here.
"""

import gc
import os
import base64
import subprocess
import tempfile
import time
import logging
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

import msal

from database import get_job, update_status

log = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
INTRO_TPL = BASE_DIR / "assets" / "intro_template.mp4"
SLC_LOGO  = BASE_DIR / "assets" / "slc_logo.png"

# ── Embedded SLC logo (base64) — written to assets/ on startup ───────────
_SLC_LOGO_B64 = "iVBORw0KGgoAAAANSUhEUgAAAHcAAABNCAYAAACc2PtBAAAtpElEQVR4nO29WY8lyZXv9ztm5mvsuWctXc1ukk1OX1KjucQVpAcBepAAfWJ9AAkC9HAx94ozHK69VFdlVVbusftiZnpwN0/PrC2bPcTVDHmAzIjwcHeLsGNn/x8LqWpHn4QPvwbAK7wAqNvz/DvO618iqvfKIR4Qh/LgpHded/67jzefCVT/ADT3e+e4vVF7z5VX773m3wupj5/yDpIPM/L7DPs+xvbJ37lG4e9d9zd6N5kfdvktkwNDgjTcldTbE5oH34jfvbV1n6lBOptRbpnb/H/YAhN/e9++tP97l1r4gcy9z4z+RPYZ30zkXbV8/9r3D6J6V/YYLHfH+BD9NTDyXdQx9522FfDthPbf97Q2sX+iuG7q+5MpuLvy2dpYj3qnalX+3ZbirVPfWjCB3Fvn37HPvnnT8fbi/PdGP1At39LbTHHvdHxoj3luFexb9C4G9zkh4eqPS243/v3Hf+eMBTDvk9j75O8xQflWIltG9L3nO2r4jpvrOsm5le53M/Itp+rOa6FbHm85d3fHda1H/tdIf560HC729FRxE1qIFzwC7Z+Tvjus6NvN22t6N265GI69/1F793yburetkwNDgjTcldTbE5oH34jfvbV1n6lBOptRbpnb/H/YAhN/e9++tP97l1r4gcy9z4z+RPYZ30zkXbV8/9r3D6J6V/YYLHfH+BD9NTDyXdQx9522FfDthPbf97Q2sX+iuG7q+5MpuLvy2dpYj3qnalX+3ZbirVPfWjCB3Fvn37HPvnnT8fbi/PdGP1At39LbTHHvdHxoj3luFexb9C4G9zkh4eqPS243/v3Hf+eMBTDvk9j75O8xQflWIltG9L3nO2r4jpvrOsm5le53M/Itp+rOa6FbHm85d3fHda1H/tdIf560HC729FRxE1qIFzwC7Z+Tvjus6NvN22t6N265GI69/1F793yburetkwNDgjTcldTbE5oH34jfvbV1n6lBOptRbpnb/H/YAhN/e9++tP97l1r4gcy9z4z+RPYZ30zkXbV8/9r3D6J6V/YYLHfH+BD9NTDyXdQx9522FfDthPbf97Q2sX+iuG7q+5MpuLvy2dpYj3qnalX+3ZbirVPfWjCB3Fvn37HPvnnT8fbi/PdGP1At39LbTHHvdHxoj3luFexb9C4G9zkh4eqPS243/v3Hf+eMBTDvk9j75O8xQflWIltG9L3nO2r4jpvrOsm5le53M/Itp+rOa6FbHm85d3fHda1H/tdIf560HC729FRxE1qIFzwC7Z+Tvjus6NvN22t6N265GI69/1F793yburetkwNDgjTcldTbE5oH34jfvbV1n6lBOptRbpnb/H/YAhN/e9++tP97l1r4gcy9z4z+RPYZ30zkXbV8/9r3D6J6V/YYLHfH+BD9NTDyXdQx9522FfDthPbf97Q2sX+iuG7q+5MpuLvy2dpYj3qnalX+3ZbirVPfWjCB3Fvn37HPvnnT8fbi/PdGP1At39LbTHHvdHxoj3luFexb9C4G9zkh4eqPS243/v3Hf+eMBTDvk9j75O8xQflWIltG9L3nO2r4jpvrOsm5le53M/Itp+rOa6FbHm85d3fHda1H/tdIf560HC729FRAAAAA="

TOKEN_CACHE_FILE = Path("/tmp/ms_token_cache.json")

# ── Watermark / badge cover constants ────────────────────────────────────
WM_BR_X, WM_BR_Y, WM_BR_W, WM_BR_H = 1655, 960, 240, 72
WM_TOP_X, WM_TOP_Y, WM_TOP_W, WM_TOP_H = 760, 48, 390, 72
BOX_RADIUS = 10
WM_EC_X, WM_EC_Y, WM_EC_W, WM_EC_H = 448, 310, 1024, 420
EC_RADIUS  = 14

# ── Microsoft OneDrive config ────────────────────────────────────────────
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID", "772dd850-50bd-4c97-9152-d1b3e78fb737")
MS_SCOPES    = ["https://graph.microsoft.com/Files.ReadWrite",
                "https://graph.microsoft.com/User.Read"]
ONEDRIVE_FOLDER_URL = os.environ.get(
    "ONEDRIVE_FOLDER_URL",
    "https://globaledulinkuk-my.sharepoint.com/:f:/g/personal/"
    "content_gamification_imperiallearning_co_uk/"
    "IgDpo-qQQhSNS5aOw2lBAFo-ASQb3KWLDkHS9kp6sIHuy0s?e=3Ualc4",
)
MS_AUTHORITY = os.environ.get(
    "MS_AUTHORITY",
    "https://login.microsoftonline.com/globaledulinkuk.onmicrosoft.com",
)

TEAL, WHITE = (96, 204, 190), (255, 255, 255)


def _ensure_assets():
    """Write embedded logo to disk if missing."""
    SLC_LOGO.parent.mkdir(parents=True, exist_ok=True)
    if not SLC_LOGO.exists() or SLC_LOGO.stat().st_size < 100:
        SLC_LOGO.write_bytes(base64.b64decode(_SLC_LOGO_B64))


_ensure_assets()


# ── Font helpers ─────────────────────────────────────────────────────────

def _font(name):
    for c in [
        str(BASE_DIR / "fonts" / name),
        f"/usr/share/fonts/truetype/google-fonts/{name}",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(c):
            return c
    return None


BOLD, MEDIUM = _font("Poppins-Bold.ttf"), _font("Poppins-Medium.ttf")


def _ft(path, size):
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


# ── Pillow PNG generators ────────────────────────────────────────────────

def _make_logo_composite(logo_path, box, W=1920, H=1080, bg=(249, 249, 249, 255)):
    brx, bry, brw, brh = box
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([brx, bry, brx + brw, bry + brh], radius=BOX_RADIUS, fill=bg)
    logo_h_px = brh - 12
    logo_img  = Image.open(str(logo_path)).convert("RGBA")
    ratio     = logo_img.width / logo_img.height
    logo_w_px = int(logo_h_px * ratio)
    if logo_w_px > brw - 12:
        logo_w_px = brw - 12
        logo_h_px = int(logo_w_px / ratio)
    logo_img = logo_img.resize((logo_w_px, logo_h_px), Image.LANCZOS)
    cx = brx + brw // 2; cy = bry + brh // 2
    logo_x = cx - logo_w_px // 2; logo_y = cy - logo_h_px // 2
    img.paste(logo_img, (logo_x, logo_y), logo_img)
    out = Path(str(logo_path)).parent / "logo_composite.png"
    img.save(str(out), "PNG")
    return out


def _make_box_png(boxes, path, W=1920, H=1080, colour=(255, 255, 255, 255)):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for (x, y, w, h, r) in boxes:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=colour)
    img.save(str(path), "PNG")
    return path


# ── Pillow text overlays ────────────────────────────────────────────────

def render_intro_overlay(course, unit_num, unit_title, W=1920, H=1080):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad  = W - 200
    csz  = 52; cfn = _ft(BOLD, csz)
    while csz > 28:
        bb = draw.textbbox((0, 0), course, font=cfn)
        if bb[2] - bb[0] <= pad:
            break
        csz -= 2; cfn = _ft(BOLD, csz)
    c_asc, c_desc = cfn.getmetrics(); c_h = c_asc + c_desc
    ufn  = _ft(BOLD, 28); utxt = unit_num.upper()
    bb   = draw.textbbox((0, 0), utxt, font=ufn)
    badge_w = bb[2] - bb[0] + 70; badge_h = 56
    has_title = bool(unit_title and unit_title.strip()); title_h = 0
    if has_title:
        tsz = 30; tfn = _ft(MEDIUM, tsz)
        while tsz > 20:
            bb = draw.textbbox((0, 0), unit_title, font=tfn)
            if bb[2] - bb[0] <= pad:
                break
            tsz -= 2; tfn = _ft(MEDIUM, tsz)
        t_asc, t_desc = tfn.getmetrics(); title_h = t_asc + t_desc
    gap1 = 45; gap2 = 25
    block_h = c_h + gap1 + badge_h + (gap2 + title_h if has_title else 0)
    start_y = (H // 2 - 60) - block_h // 2
    draw.text((W // 2, start_y + c_h // 2), course, fill=WHITE, font=cfn, anchor="mm")
    bx = (W - badge_w) // 2; by = start_y + c_h + gap1
    draw.rounded_rectangle([bx, by, bx + badge_w, by + badge_h], radius=14, fill=TEAL + (230,))
    draw.text((bx + badge_w // 2, by + badge_h // 2), utxt, fill=WHITE, font=ufn, anchor="mm")
    if has_title:
        ty2 = by + badge_h + gap2
        draw.text((W // 2, ty2 + title_h // 2), unit_title, fill=WHITE, font=tfn, anchor="mm")
    return img


def render_end_overlay(W=1920, H=1080):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fn   = _ft(BOLD, 42); bb = draw.textbbox((0, 0), "END", font=fn)
    bw, bh = bb[2] - bb[0] + 90, 72
    bx, by = (W - bw) // 2, (H - bh) // 2 - 20
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=16, fill=TEAL + (230,))
    draw.text((bx + bw // 2, by + bh // 2), "END", fill=WHITE, font=fn, anchor="mm")
    return img


# ── FFmpeg helpers ───────────────────────────────────────────────────────

def _ff(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        err = r.stderr.strip().split("\n")
        raise RuntimeError("\n".join(err[-6:]) if len(err) > 6 else r.stderr)
    return r


def _probe_resolution(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        w, h = r.stdout.strip().split(",")
        return (int(w), int(h))
    except Exception:
        return (1920, 1080)


def _probe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"Cannot read duration: {path}")
    return float(r.stdout.strip())


def _has_audio(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def _detect_end_card_start(path):
    total = _probe_duration(path)
    t = max(0.0, total - 20.0)
    while t < total - 1.0:
        fd, tf = tempfile.mkstemp(suffix=".jpg"); os.close(fd)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                 "-vframes", "1", tf],
                capture_output=True, timeout=8,
            )
            a = np.array(Image.open(tf))
            if (a.mean(axis=2) > 230).sum() / (a.shape[0] * a.shape[1]) > 0.95:
                return t
        except Exception:
            pass
        finally:
            try:
                os.unlink(tf)
            except OSError:
                pass
        t += 0.5
    return max(0.0, total - 9.0)


def _detect_top_watermark_end(path, max_scan=120.0):
    try:
        src_w, src_h = _probe_resolution(path)
    except Exception:
        src_w, src_h = 1920, 1080
    sx = src_w / 1920; sy = src_h / 1080
    rx = max(0, int(WM_TOP_X * sx)); ry = max(0, int(WM_TOP_Y * sy))
    rw = max(1, int(WM_TOP_W * sx)); rh = max(1, int(WM_TOP_H * sy))

    def _grab_region(t):
        fd, tf = tempfile.mkstemp(suffix=".jpg"); os.close(fd)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                 "-vframes", "1", tf],
                capture_output=True, timeout=8,
            )
            img = Image.open(tf).convert("RGB")
            return np.array(img)[ry:ry + rh, rx:rx + rw].astype(float)
        except Exception:
            return None
        finally:
            try:
                os.unlink(tf)
            except OSError:
                pass

    ref = _grab_region(0.0)
    if ref is None or ref.size == 0:
        return 0.0
    if (ref > 200).mean() < 0.60:
        return 0.0
    total = _probe_duration(path)
    scan_end = min(max_scan, total - 2.0)
    step = 0.5; t = step; last_t = 0.0
    while t <= scan_end:
        frame = _grab_region(t)
        if frame is not None and frame.size > 0:
            diff = np.abs(frame - ref).mean()
            if diff < 12:
                last_t = t
            else:
                return last_t + step
        t += step
    return min(last_t + step, max_scan)


def make_intro(course, unit_num, unit_title, tmp):
    png = str(tmp / "intro_overlay.png"); out = str(tmp / "intro.mp4")
    render_intro_overlay(course, unit_num, unit_title).save(png, "PNG")
    y = "if(lt(t\\,0.8)\\,300*pow(1-t/0.8\\,2)\\,0)"
    _ff(["ffmpeg", "-y", "-i", str(INTRO_TPL), "-loop", "1", "-i", png,
         "-filter_complex",
         f"[1:v]format=rgba[ovr];[0:v][ovr]overlay=x=0:y='{y}':shortest=1[out]",
         "-map", "[out]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
         "-r", "30", "-pix_fmt", "yuv420p", out], timeout=60)
    return Path(out)


def make_outro(tmp):
    png = str(tmp / "end_overlay.png"); out = str(tmp / "outro.mp4")
    render_end_overlay().save(png, "PNG")
    y = "if(lt(t\\,0.8)\\,250*pow(1-t/0.8\\,2)\\,0)"
    _ff(["ffmpeg", "-y", "-i", str(INTRO_TPL), "-loop", "1", "-i", png,
         "-filter_complex",
         f"[1:v]format=rgba[ovr];[0:v][ovr]overlay=x=0:y='{y}':shortest=1[out]",
         "-map", "[out]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
         "-r", "30", "-pix_fmt", "yuv420p", out], timeout=60)
    return Path(out)


def normalise(inp, out):
    ha = _has_audio(inp)
    cmd = ["ffmpeg", "-y", "-i", str(inp)]
    if not ha:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += [
        "-vf",
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
        "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-pix_fmt", "yuv420p",
    ]
    if not ha:
        cmd += ["-shortest"]
    cmd += [str(out)]
    _ff(cmd)
    return Path(out)


def remove_notebooklm_watermark(inp, out, src_resolution, tmp, progress_cb=None):
    inp_str, out_str = str(inp), str(out)
    if progress_cb:
        progress_cb("Detecting end-card start time…")
    ecs = _detect_end_card_start(inp_str)
    duration = _probe_duration(inp_str)
    trim_at = None
    if ecs < duration - 2.0:
        trim_at = ecs
        if progress_cb:
            progress_cb(f"Trimming end card at {ecs:.1f}s…")
    use_logo = SLC_LOGO.exists() and SLC_LOGO.stat().st_size > 500
    if progress_cb:
        progress_cb("Detecting top watermark duration…")
    top_end = _detect_top_watermark_end(inp_str)
    top_png = tmp / "wm_top.png"
    if top_end > 0.5:
        if progress_cb:
            progress_cb(f"   Badge visible until ~{top_end:.1f}s")
        _make_box_png(
            [(WM_TOP_X, WM_TOP_Y, WM_TOP_W, WM_TOP_H, BOX_RADIUS)],
            top_png, colour=(249, 249, 249, 255),
        )
        en_top = f"lte(t\\,{top_end:.2f})"
    else:
        if progress_cb:
            progress_cb("   No top badge detected — skipping")
        Image.new("RGBA", (1920, 1080), (0, 0, 0, 0)).save(str(top_png), "PNG")
        en_top = "0"
    if use_logo:
        comp_png = _make_logo_composite(
            logo_path=SLC_LOGO, box=(WM_BR_X, WM_BR_Y, WM_BR_W, WM_BR_H),
        )
        fc = (
            "[1:v]format=rgba[comp];[0:v][comp]overlay=x=0:y=0[v1];"
            "[2:v]format=rgba[top];"
            f"[v1][top]overlay=x=0:y=0:enable='{en_top}'[vout]"
        )
        cmd = ["ffmpeg", "-y", "-i", inp_str, "-i", str(comp_png), "-i", str(top_png)]
    else:
        br_png = tmp / "wm_br.png"
        _make_box_png(
            [(WM_BR_X, WM_BR_Y, WM_BR_W, WM_BR_H, BOX_RADIUS)],
            br_png, colour=(249, 249, 249, 255),
        )
        fc = (
            "[1:v]format=rgba[br];[0:v][br]overlay=x=0:y=0[v1];"
            "[2:v]format=rgba[top];"
            f"[v1][top]overlay=x=0:y=0:enable='{en_top}'[vout]"
        )
        cmd = ["ffmpeg", "-y", "-i", inp_str, "-i", str(br_png), "-i", str(top_png)]
    if trim_at is not None:
        cmd += [
            "-filter_complex", fc, "-map", "[vout]", "-map", "0:a",
            "-t", f"{trim_at:.2f}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-r", "30", "-pix_fmt", "yuv420p", out_str,
        ]
    else:
        cmd += [
            "-filter_complex", fc, "-map", "[vout]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-r", "30", "-pix_fmt", "yuv420p", "-shortest", out_str,
        ]
    _ff(cmd, timeout=max(900, int(duration * 25)))
    return Path(out)


def add_notebooklm_transition(intro, main, out, duration=1.0, direction="left"):
    tm = {"left": "wipeleft", "right": "wiperight", "up": "wipeup", "down": "wipedown"}
    wipe = tm.get(direction, "wipeleft")
    intro_d = _probe_duration(intro)
    half = max(0.25, min(duration / 2, intro_d - 0.05))
    cc = (
        "color=c=0x7B2CBF:s=1920x1080:r=30,"
        "drawbox=x=0:y=0:w=576:h=1080:color=0x7B2CBF:t=fill,"
        "drawbox=x=576:y=0:w=461:h=1080:color=0x4285F4:t=fill,"
        "drawbox=x=1037:y=0:w=346:h=1080:color=0x7EDFC3:t=fill,"
        "drawbox=x=1383:y=0:w=537:h=1080:color=0xB7E4C7:t=fill"
    )
    _ff([
        "ffmpeg", "-y", "-i", str(intro), "-i", str(main),
        "-f", "lavfi", "-t", f"{duration}", "-i", cc,
        "-f", "lavfi", "-t", f"{duration}", "-i", "anullsrc=r=48000:cl=stereo",
        "-filter_complex",
        "[0:v]fps=30,format=yuv420p,settb=AVTB[v0];"
        "[1:v]fps=30,format=yuv420p,settb=AVTB[v1];"
        "[2:v]fps=30,format=yuv420p,settb=AVTB[vc];"
        f"[v0][vc]xfade=transition={wipe}:duration={half}:offset={max(intro_d - half, 0):.3f}[vx];"
        f"[vx][v1]xfade=transition={wipe}:duration={half}:offset={intro_d:.3f}[vout];"
        f"[0:a][3:a]acrossfade=d={half}:c1=tri:c2=tri[ax];"
        f"[ax][1:a]acrossfade=d={half}:c1=tri:c2=tri[aout]",
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-r", "30", "-pix_fmt", "yuv420p", str(out),
    ], timeout=180)
    return Path(out)


def concat(parts, out, tmp):
    lst = tmp / "list.txt"
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{Path(p).resolve()}'\n")
    try:
        _ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c", "copy", str(out)])
    except RuntimeError:
        _ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
             "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p", str(out)])
    return Path(out)


# ── Download helper ──────────────────────────────────────────────────────

def download_video(url: str, temp_dir: Path) -> Path:
    """Stream-download an .mp4 from *url* into *temp_dir*, return local path."""
    dest = temp_dir / "raw.mp4"
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    return dest


# ── OneDrive upload (headless — uses token cache on disk) ────────────────

def _get_onedrive_token() -> str | None:
    """Try to acquire a cached OneDrive token silently. Returns None if unavailable."""
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_FILE.exists():
        try:
            cache.deserialize(TOKEN_CACHE_FILE.read_text())
        except Exception:
            return None
    app = msal.PublicClientApplication(MS_CLIENT_ID, authority=MS_AUTHORITY, token_cache=cache)
    accounts = app.get_accounts()
    if not accounts:
        return None
    result = app.acquire_token_silent(MS_SCOPES, account=accounts[0])
    if result and "access_token" in result:
        if cache.has_state_changed:
            TOKEN_CACHE_FILE.write_text(cache.serialize())
        return result["access_token"]
    return None


def onedrive_upload(file_path: str, filename: str) -> str | None:
    """Upload file at *file_path* to the department OneDrive folder.
    Returns the web URL on success, or None on failure.
    """
    token = _get_onedrive_token()
    if not token:
        log.warning("No OneDrive token available — skipping upload")
        return None

    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    folder_url = ONEDRIVE_FOLDER_URL

    # Resolve shared folder
    folder_id = None
    drive_prefix = "me/drive"
    if folder_url:
        b64 = base64.urlsafe_b64encode(folder_url.encode()).rstrip(b"=").decode()
        for ep in [
            f"https://graph.microsoft.com/v1.0/shares/u!{b64}/root?$select=id,name,webUrl,parentReference",
            f"https://graph.microsoft.com/v1.0/shares/u!{b64}/driveItem?$select=id,name,webUrl,parentReference",
        ]:
            try:
                sr = requests.get(ep, headers=h, timeout=20)
                if sr.status_code == 200:
                    item = sr.json()
                    folder_id = item["id"]
                    drv = item.get("parentReference", {}).get("driveId", "")
                    drive_prefix = f"drives/{drv}" if drv else "me/drive"
                    break
            except Exception:
                continue

    if not folder_id:
        log.warning("Could not resolve OneDrive folder — skipping upload")
        return None

    # Create upload session
    safe_name = filename.replace(" ", "_")
    session_url = (
        f"https://graph.microsoft.com/v1.0/{drive_prefix}/items/"
        f"{folder_id}:/{safe_name}:/createUploadSession"
    )
    r2 = requests.post(
        session_url, headers=h,
        json={"item": {"@microsoft.graph.conflictBehavior": "rename"}},
        timeout=30,
    )
    if r2.status_code not in (200, 201):
        log.error("Upload session creation failed: HTTP %s", r2.status_code)
        return None

    upload_url = r2.json().get("uploadUrl")
    if not upload_url:
        return None

    # Chunked upload
    CHUNK = 5 * 1024 * 1024
    data = Path(file_path).read_bytes()
    total = len(data); uploaded = 0; file_web_url = None
    while uploaded < total:
        chunk = data[uploaded:uploaded + CHUNK]
        chunk_end = uploaded + len(chunk) - 1
        r3 = requests.put(
            upload_url, data=chunk, timeout=180,
            headers={
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {uploaded}-{chunk_end}/{total}",
                "Content-Type": "video/mp4",
            },
        )
        if r3.status_code in (200, 201):
            try:
                file_web_url = r3.json().get("webUrl", "")
            except Exception:
                file_web_url = ""
        elif r3.status_code == 202:
            pass
        else:
            log.error("Upload failed at byte %d (HTTP %s)", uploaded, r3.status_code)
            return None
        uploaded += len(chunk)

    log.info("OneDrive upload complete: %s (%d MB)", filename, total // 1048576)
    return file_web_url or None


# ══════════════════════════════════════════════════════════════════════════
# Main orchestrator
# ══════════════════════════════════════════════════════════════════════════

def process_single_job(job_id: int):
    """Fetch job from DB, run the full pipeline, upload, update DB."""
    job = get_job(job_id)
    if job is None:
        log.error("Job %d not found", job_id)
        return

    update_status(job_id, "processing")
    log.info("Processing job %d: %s / %s", job_id, job["course_name"], job["unit_number"])

    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            # 1. Download
            log.info("  Downloading video…")
            raw = download_video(job["video_url"], tmp)
            src_res = _probe_resolution(str(raw))

            # 2. Build intro + outro + normalise (sequential to save RAM)
            log.info("  Building intro…")
            intro = make_intro(job["course_name"], job["unit_number"], "", tmp)
            log.info("  Building outro…")
            outro = make_outro(tmp)
            log.info("  Normalising…")
            norm = normalise(raw, tmp / "norm.mp4")

            # 3. Remove watermarks
            log.info("  Removing watermarks…")
            norm_clean = remove_notebooklm_watermark(
                norm, tmp / "norm_clean.mp4", src_res, tmp,
            )

            # 4. Transition
            log.info("  Adding transition…")
            with_trans = add_notebooklm_transition(
                intro, norm_clean, tmp / "intro_and_main.mp4",
            )

            # 5. Concat
            log.info("  Concatenating final…")
            final = concat([with_trans, outro], tmp / "final.mp4", tmp)
            final_path = str(final)

            # 6. Upload to OneDrive
            safec = job["course_name"][:30].replace(" ", "_")
            safeu = job["unit_number"].replace(" ", "_").replace("|", "")
            filename = f"SLC_Video_{safec}_{safeu}.mp4"

            log.info("  Uploading to OneDrive…")
            od_url = onedrive_upload(final_path, filename)

            update_status(
                job_id, "done",
                file_path=final_path,
                onedrive_url=od_url,
            )
            log.info("Job %d done. OneDrive URL: %s", job_id, od_url)

    except Exception as e:
        log.exception("Job %d failed", job_id)
        update_status(job_id, "failed", error_message=str(e))

    finally:
        gc.collect()

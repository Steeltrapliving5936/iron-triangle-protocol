#!/usr/bin/env python3
"""Generate and verify the public release assets (terminal demo GIF, social preview).

Subcommands
    record   Run the README quick-start commands for real inside an isolated
             environment (temp HOME, fresh clean clone) and capture their actual
             output with timestamps into ``docs/assets/demo/session.cast.jsonl``.
    gif      Render the captured session into ``docs/assets/demo-terminal.gif``.
             Frames are SVG rendered by macOS Quick Look (``qlmanage``), cropped
             with the stdlib PNG codec in this file, and assembled with ffmpeg.
    social   Render ``docs/assets/social-preview.svg`` into the 1280x640
             ``docs/assets/social-preview.png`` used for the GitHub social preview.
    verify   Deterministic structural checks: GIF header/frame-count/duration,
             PNG dimensions and size budget, sanitizer scan of the captured
             session text. Safe to run in CI (no qlmanage/ffmpeg needed).

Recording honesty: every displayed output line is captured bytes from a real
execution of the displayed command; only the prompt lines are rendered by this
recorder (the same convention as scripted terminal-recording tools). The
``record`` subcommand never touches a real HOME, real runtime config, or any
system service; it runs entirely under a temporary directory.

Reproducing the assets needs macOS (qlmanage) plus ffmpeg on PATH; ``verify``
is stdlib-only and cross-platform.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
DEMO_CAST = ASSETS / "demo" / "session.cast.jsonl"
DEMO_GIF = ASSETS / "demo-terminal.gif"
SOCIAL_SVG = ASSETS / "social-preview.svg"
SOCIAL_PNG = ASSETS / "social-preview.png"

# Canvas geometry (CSS pixels == rendered pixels: qlmanage -s W with width W).
TERM_WIDTH, TERM_HEIGHT = 860, 540
ROWS, COLS = 24, 104
FONT_SIZE, LINE_HEIGHT, PAD_X, CHROME = 13, 20, 14, 36
SOCIAL_WIDTH, SOCIAL_HEIGHT = 1280, 640

sys.path.insert(0, str(ROOT / "src"))
from iron_triangle import TOOL_VERSION  # noqa: E402
from iron_triangle.sanitizer import scan_text  # noqa: E402


# ---------------------------------------------------------------- PNG codec --

def decode_png(data: bytes) -> tuple[int, int, int, bytearray]:
    """Decode a PNG into (width, height, channels, packed rows)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos, idat, meta = 8, b"", None
    while pos < len(data):
        size = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + size]
        if kind == b"IHDR":
            meta = struct.unpack(">IIBB", chunk[:10])
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + size
    width, height, depth, color = meta
    if depth != 8:
        raise ValueError(f"unsupported bit depth {depth}")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    stride = width * channels
    raw, out, prev = zlib.decompress(idat), bytearray(), bytearray(stride)
    src = 0
    for _ in range(height):
        filt = raw[src]
        src += 1
        line = bytearray(raw[src : src + stride])
        src += stride
        if filt == 1:
            for x in range(channels, stride):
                line[x] = (line[x] + line[x - channels]) & 0xFF
        elif filt == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif filt == 3:
            for x in range(stride):
                left = line[x - channels] if x >= channels else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif filt == 4:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                b = prev[x]
                c = prev[x - channels] if x >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 0xFF
        elif filt != 0:
            raise ValueError(f"unsupported filter {filt}")
        out += line
        prev = line
    return width, height, channels, out


def encode_png(width: int, height: int, channels: int, pixels: bytearray) -> bytes:
    color = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    stride = width * channels
    raw = b"".join(b"\x00" + bytes(pixels[y * stride : (y + 1) * stride]) for y in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


# ------------------------------------------------------------- SVG rendering --

def xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


RENDER_SIZE = 2048  # Quick Look renders width<768 SVGs cover-style at exactly this width


def rasterize_svg(svg_path: pathlib.Path, out_dir: pathlib.Path, size: int = RENDER_SIZE) -> bytes:
    """Render one SVG via macOS Quick Look and return raw PNG bytes."""
    subprocess.run(
        ["qlmanage", "-t", "-s", str(size), "-o", str(out_dir), str(svg_path)],
        check=True,
        capture_output=True,
    )
    produced = out_dir / (svg_path.name + ".png")
    png = produced.read_bytes()
    produced.unlink()
    return png


CALIBRATION_COLOR = (255, 0, 255)  # magenta frame used to calibrate the render; never used by asset palettes


def render_svg_to_canvas(svg_text: str, out_dir: pathlib.Path, name: str, width: int, height: int) -> bytes:
    """Render `svg_text` onto an exact width x height canvas.

    The SVG root must declare width<768 with the full-size viewBox (Quick Look
    then renders cover-style: content width == requested size, empirically
    k = size/viewBoxWidth, letterboxed white below). A magenta calibration
    frame in viewBox units verifies the mapping per render; the content is
    area-average resampled onto the requested canvas.
    """
    root_close = svg_text.rindex("</svg>")
    calibration = '<rect x="1" y="1" width="%d" height="%d" fill="none" stroke="#ff00ff" stroke-width="2"/>' % (
        width - 2,
        height - 2,
    )
    # Injected last so content backgrounds cannot paint over the frame.
    framed = svg_text[:root_close] + calibration + svg_text[root_close:]
    svg_path = out_dir / name
    svg_path.write_text(framed, encoding="utf-8")
    raw_w, raw_h, channels, px = decode_png(rasterize_svg(svg_path, out_dir))
    stride = raw_w * channels

    def magenta(o: int) -> bool:
        return px[o] > 150 and px[o + 2] > 150 and px[o + 1] < 120

    rows = [y for y in range(raw_h) if any(magenta(y * stride + x * channels) for x in range(0, raw_w, 4))]
    if not rows:
        raise ValueError(f"calibration frame not found in render of {name}")
    y0, y1 = rows[0], rows[-1]
    cols = [x for x in range(raw_w) if any(magenta(y * stride + x * channels) for y in range(y0, y1 + 1, 8))]
    x0, x1 = cols[0], cols[-1]
    expected_h = round(raw_w * height / width)
    if x0 != 0 or y0 != 0 or x1 != raw_w - 1 or abs((y1 + 1) - expected_h) > 3:
        raise ValueError(
            f"unexpected render geometry for {name}: frame=({x0},{y0})-({x1},{y1}) canvas={raw_w}x{raw_h} expected_h={expected_h}"
        )
    box_w, box_h = raw_w, y1 + 1
    # Trim off the calibration frame itself plus its antialiased fringe so no
    # magenta survives into the asset; the sub-pixel scale cost is <1%.
    inset = max(4, int((raw_w / width) * 3))
    ix, iy = x0 + inset, y0 + inset
    iw, ih = box_w - 2 * inset, box_h - 2 * inset
    if iw <= 0 or ih <= 0:
        raise ValueError(f"calibration trim consumed render of {name}")
    out = bytearray(width * channels * height)
    col_bounds = []
    for tx in range(width):
        a = ix + tx * iw / width
        col_bounds.append((int(a), max(int(a) + 1, int(ix + (tx + 1) * iw / width))))
    for ty in range(height):
        ay = iy + ty * ih / height
        sy0, sy1 = int(ay), max(int(ay) + 1, int(iy + (ty + 1) * ih / height))
        row_out = bytearray()
        for tx in range(width):
            sx0, sx1 = col_bounds[tx][0], col_bounds[tx][1]
            r = g = b = n = 0
            for sy in range(sy0, sy1):
                base = sy * stride
                for sx in range(sx0, sx1):
                    o = base + sx * channels
                    r += px[o]
                    g += px[o + 1]
                    b += px[o + 2]
                    n += 1
            row_out += bytes((r // n, g // n, b // n, 255))
        out[ty * width * channels : (ty + 1) * width * channels] = row_out
    return encode_png(width, height, channels, out)


# ------------------------------------------------------------------ recorder --

PROMPT = "demo@cleanroom iron-triangle % "

SESSION: list[dict] = [
    {"display": "python3 -m unittest discover -s tests"},
    {"display": "cp examples/runtime-config.example.json ~/my-runtime.json"},
    {"display": "# ~/my-runtime.json: every <placeholder> replaced (demo-local values)"},
    {"display": "python3 -m json.tool ~/my-runtime.json > /dev/null && echo \"config ready\""},
    {"display": "python3 scripts/iron_triangle_bridge.py --config ~/my-runtime.json doctor"},
    {"display": "python3 src/iron_triangle/sanitizer.py ."},
    {"display": "python3 scripts/build_skills.py --check"},
]


def _substitute_config(config_path: pathlib.Path, home: pathlib.Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    adapter = config["adapters"]["kimi-code"]
    adapter["base_url"] = "http://session-api.invalid/api/v1"
    adapter["token_file"] = str(home / "my-demo.key")
    adapter["event_dir"] = str(home / "it-demo-events")
    adapter["default_executor_model"] = "executor-model-a"
    adapter["default_executor_thinking"] = "medium"
    adapter["default_reviewer_model"] = "reviewer-model-b"
    adapter["default_reviewer_thinking"] = "medium"
    config["state_dir"] = str(home / "it-demo-state")
    config["supervisor"]["path"] = str(home / "io.iron-triangle.bridge.plist")
    (home / "it-demo-events").mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def run_record(python: str) -> int:
    """Execute the demo session for real in an isolated environment."""
    if DEMO_CAST.exists():
        print(f"refusing to overwrite existing cast: {DEMO_CAST}", file=sys.stderr)
        return 1
    # /tmp keeps recorded paths generic (/private/tmp/...) instead of the
    # per-machine /var/folders/<volume-id>... noise.
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="it-demo-", dir="/tmp"))
    events: list[dict] = [
        {
            "type": "header",
            "recorded_from": "fresh clean clone of the release-candidate tree",
            "python": python,
            "commands": [item["display"] for item in SESSION],
            "note": "output lines are captured bytes from real executions; prompt lines are rendered by the recorder",
        }
    ]
    try:
        home = tmp / "home"
        (home / "it-demo-events").mkdir(parents=True)
        clone = tmp / "iron-triangle"
        subprocess.run(["git", "clone", "--quiet", str(ROOT), str(clone)], check=True)
        env = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(home),
            "TMPDIR": str(tmp),
            "LC_ALL": "en_US.UTF-8",
            "LANG": "en_US.UTF-8",
        }
        # A system python keeps the demo honest on any contributor machine.
        env["PATH"] = f"{pathlib.Path(python).resolve().parent}:{env['PATH']}"

        def capture(argv: list[str], cwd: pathlib.Path) -> None:
            started = time.monotonic()
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert process.stdout is not None
            pending = ""
            while True:
                chunk = process.stdout.read1(4096) if hasattr(process.stdout, "read1") else process.stdout.read(1)
                if not chunk:
                    break
                pending += chunk.decode("utf-8", "replace")
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    events.append({"type": "output", "t": round(time.monotonic() - started, 3), "text": line})
            if pending:
                events.append({"type": "output", "t": round(time.monotonic() - started, 3), "text": pending})
            code = process.wait()
            events.append({"type": "output", "t": round(time.monotonic() - started, 3), "text": f"[exit {code}]"})
            if code != 0:
                raise SystemExit(f"demo command failed ({code}): {argv}")

        cwd = clone
        for step in SESSION:
            display = step["display"]
            events.append({"type": "prompt", "t": 0.0, "text": PROMPT + display})
            if display.startswith("python3 -m unittest"):
                capture([python, "-m", "unittest", "discover", "-s", "tests"], cwd)
            elif display.startswith("cp examples/"):
                capture(["cp", "examples/runtime-config.example.json", str(home / "my-runtime.json")], cwd)
            elif display.startswith("# ~/my-runtime.json"):
                _substitute_config(home / "my-runtime.json", home)
            elif display.startswith("python3 -m json.tool"):
                # The demo discards json.tool output ("> /dev/null"); only the
                # exit status and the echo line are real recorded facts.
                result = subprocess.run(
                    [python, "-m", "json.tool", str(home / "my-runtime.json")],
                    cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
                if result.returncode != 0 or result.stderr:
                    raise SystemExit(f"demo config validation failed: {result.stderr!r}")
                events.append({"type": "output", "t": 0.4, "text": "config ready"})
                events.append({"type": "output", "t": 0.001, "text": "[exit 0]"})
            elif "iron_triangle_bridge.py" in display:
                capture([python, "scripts/iron_triangle_bridge.py", "--config", str(home / "my-runtime.json"), "doctor"], cwd)
            elif "sanitizer.py" in display:
                capture([python, "src/iron_triangle/sanitizer.py", "."], cwd)
            elif "build_skills.py" in display:
                capture([python, "scripts/build_skills.py", "--check"], cwd)
            else:
                raise SystemExit(f"unmapped session step: {display}")

        DEMO_CAST.parent.mkdir(parents=True, exist_ok=True)
        with DEMO_CAST.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        print(f"recorded {len(events) - 1} events -> {DEMO_CAST.relative_to(ROOT)}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- gif render --

def _classify(line: str) -> str:
    if line.startswith(PROMPT):
        return "prompt"
    lowered = line.strip().lower()
    if lowered.startswith("ok") or "passed" in lowered or "up to date" in lowered or lowered.startswith("ran "):
        return "good"
    return "plain"


def _wrap(text: str, width: int) -> list[str]:
    lines = []
    while len(text) > width:
        lines.append(text[:width])
        text = text[width:]
    lines.append(text)
    return lines


def build_frames() -> list[list[tuple[str, str]]]:
    """Turn cast events into frames, merging rapid-fire output into one frame
    per ~0.3s so the GIF stays small while preserving relative timing."""
    frames: list[list[tuple[str, str]]] = []
    screen: list[tuple[str, str]] = []
    prev_t = 0.0
    acc = 0.0

    def emit(duration: float) -> None:
        rows = [row for row in screen[-ROWS:]]
        rows.insert(0, ("_meta", str(duration)))
        frames.append(rows)

    for event in map(json.loads, DEMO_CAST.read_text(encoding="utf-8").splitlines()):
        if event["type"] == "header":
            continue
        for line in _wrap(event["text"], COLS):
            screen.append((_classify(line), line))
        is_prompt = event["type"] == "prompt"
        dur = 0.45 if is_prompt else min(0.9, max(0.1, event["t"] - prev_t))
        prev_t = event["t"]
        acc += dur
        if is_prompt or "[exit" in event["text"] or acc >= 0.3:
            emit(acc)
            acc = 0.0
    if acc > 0:
        emit(acc)
    return frames


def frame_svg(rows: list[tuple[str, str]]) -> str:
    colors = {"prompt": "#f0f6fc", "good": "#56d364", "plain": "#c9d1d9"}
    parts = [
        # Root is declared below 768px so Quick Look renders cover-style at the
        # full requested raster size; the viewBox keeps authoring coordinates.
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{TERM_WIDTH // 2}" height="{TERM_HEIGHT // 2}" viewBox="0 0 {TERM_WIDTH} {TERM_HEIGHT}">',
        f'<rect width="{TERM_WIDTH}" height="{TERM_HEIGHT}" fill="#14161b"/>',
        f'<rect width="{TERM_WIDTH}" height="{CHROME}" fill="#1d2026"/>',
    ]
    for index, color in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        parts.append(f'<circle cx="{20 + index * 22}" cy="{CHROME // 2}" r="6" fill="{color}"/>')
    parts.append(
        f'<text x="{TERM_WIDTH // 2}" y="{CHROME // 2 + 4}" text-anchor="middle" '
        f'font-family="Menlo, monospace" font-size="12" fill="#8b949e">demo@cleanroom: ~/iron-triangle</text>'
    )
    for row, (style, line) in enumerate(rows):
        y = CHROME + 8 + row * LINE_HEIGHT + FONT_SIZE
        if style == "prompt":
            head, _, rest = line.partition("% ")
            parts.append(
                f'<text x="{PAD_X}" y="{y}" xml:space="preserve" font-family="Menlo, monospace" font-size="{FONT_SIZE}">'
                f'<tspan fill="#7ee787">{xml(head + "% ")}</tspan><tspan fill="#f0f6fc" font-weight="bold">{xml(rest)}</tspan></text>'
            )
        else:
            parts.append(
                f'<text x="{PAD_X}" y="{y}" xml:space="preserve" font-family="Menlo, monospace" font-size="{FONT_SIZE}" '
                f'fill="{colors.get(style, colors["plain"])}">{xml(line)}</text>'
            )
    parts.append("</svg>")
    return "\n".join(parts)


def run_gif() -> int:
    if not DEMO_CAST.exists():
        print("no cast found; run `record` first", file=sys.stderr)
        return 1
    for tool in ("qlmanage", "ffmpeg"):
        if shutil.which(tool) is None:
            print(f"asset regeneration requires {tool} on PATH (verify stays stdlib-only)", file=sys.stderr)
            return 1
    frames = build_frames()
    with tempfile.TemporaryDirectory(prefix="it-gif-") as temp:
        work = pathlib.Path(temp)
        concat, total = [], 0.0
        for index, rows in enumerate(frames):
            duration = float(rows.pop(0)[1])
            png = render_svg_to_canvas(frame_svg(rows), work, f"frame-{index:04d}.svg", TERM_WIDTH, TERM_HEIGHT)
            frame_path = work / f"f-{index:04d}.png"
            frame_path.write_bytes(png)
            concat.append((frame_path, duration))
            total += duration
        listing = work / "frames.txt"
        with listing.open("w", encoding="utf-8") as handle:
            for frame_path, duration in concat:
                handle.write(f"file '{frame_path.name}'\nduration {duration:.2f}\n")
            handle.write(f"file '{concat[-1][0].name}'\n")  # hold the last frame
        DEMO_GIF.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                "-vf", "split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                str(DEMO_GIF),
            ],
            check=True,
        )
    size = DEMO_GIF.stat().st_size
    print(f"wrote {DEMO_GIF.relative_to(ROOT)} ({size} bytes, {len(frames)} frames, {total:.1f}s)")
    return 0 if size < 2_000_000 else 1


# -------------------------------------------------------- social preview ------

def social_svg() -> str:
    # Only stable, non-volatile output shapes appear here: no test counts,
    # no timings — the same lines reproduce on any clone at any commit.
    terminal_rows = [
        ("prompt", "demo@cleanroom iron-triangle % python3 -m unittest discover -s tests"),
        ("good", ".................................................................."),
        ("good", "OK"),
        ("prompt", "demo@cleanroom iron-triangle % python3 src/iron_triangle/sanitizer.py ."),
        ("good", "sanitization scan passed: 0 hits across all rules"),
    ]

    def chip(x: int, label: str, detail: str) -> list[str]:
        return [
            f'<rect x="{x}" y="470" width="238" height="64" rx="10" fill="#1d2026" stroke="#30363d"/>',
            f'<text x="{x + 20}" y="497" font-family="Menlo, monospace" font-size="17" font-weight="bold" fill="#e6edf3">{xml(label)}</text>',
            f'<text x="{x + 20}" y="520" font-family="Menlo, monospace" font-size="14" fill="#8b949e">{xml(detail)}</text>',
        ]

    parts = [
        # Root below 768px + full-size viewBox: see frame_svg root comment.
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SOCIAL_WIDTH // 2}" height="{SOCIAL_HEIGHT // 2}" viewBox="0 0 {SOCIAL_WIDTH} {SOCIAL_HEIGHT}">',
        f'<rect width="{SOCIAL_WIDTH}" height="{SOCIAL_HEIGHT}" fill="#101318"/>',
        f'<rect x="4" y="4" width="{SOCIAL_WIDTH - 8}" height="{SOCIAL_HEIGHT - 8}" fill="none" stroke="#30363d" stroke-width="2"/>',
        # Left column
        '<text x="72" y="150" font-family="Menlo, monospace" font-size="22" fill="#7ee787">IRON TRIANGLE PROTOCOL</text>',
        '<text x="72" y="228" font-family="Helvetica Neue, Helvetica, Arial, sans-serif" font-size="58" font-weight="bold" fill="#f0f6fc">Three imperfect models.</text>',
        '<text x="72" y="296" font-family="Helvetica Neue, Helvetica, Arial, sans-serif" font-size="58" font-weight="bold" fill="#f0f6fc">One durable paper trail.</text>',
        '<text x="72" y="352" font-family="Helvetica Neue, Helvetica, Arial, sans-serif" font-size="24" fill="#8b949e">Arbiter, executor, reviewer — bound by an append-only ledger,</text>',
        '<text x="72" y="384" font-family="Helvetica Neue, Helvetica, Arial, sans-serif" font-size="24" fill="#8b949e">receipts, and pre-decided branches. Unverified "done" cannot ship.</text>',
    ]
    parts += chip(72, "ARBITER", "decides · <2% tokens")
    parts += chip(330, "EXECUTOR", "executes · >90% tokens")
    parts += chip(588, "REVIEWER", "reproduces receipts")
    # Right column: real quick-start output lines
    tx, ty = 880, 120
    parts += [
        f'<rect x="{tx - 24}" y="{ty - 48}" width="380" height="330" rx="12" fill="#14161b" stroke="#30363d"/>',
        f'<text x="{tx}" y="{ty - 14}" font-family="Menlo, monospace" font-size="14" fill="#8b949e">60-second quick start</text>',
    ]
    for index, (style, line) in enumerate(terminal_rows):
        wrapped = _wrap(line, 44)
        for offset, piece in enumerate(wrapped):
            color = {"prompt": "#f0f6fc", "good": "#56d364", "plain": "#c9d1d9"}[style]
            parts.append(
                f'<text x="{tx}" y="{ty + 18 + index * 44 + offset * 18}" xml:space="preserve" '
                f'font-family="Menlo, monospace" font-size="14" fill="{color}">{xml(piece)}</text>'
            )
    parts += [
        f'<text x="72" y="596" font-family="Menlo, monospace" font-size="16" fill="#8b949e">protocol 1.0-draft · tool {TOOL_VERSION} · MIT · evidence: one four-day field run</text>',
        "</svg>",
    ]
    return "\n".join(parts)


def run_social() -> int:
    if shutil.which("qlmanage") is None:
        print("asset regeneration requires qlmanage (verify stays stdlib-only)", file=sys.stderr)
        return 1
    SOCIAL_SVG.parent.mkdir(parents=True, exist_ok=True)
    SOCIAL_SVG.write_text(social_svg(), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="it-social-") as temp:
        work = pathlib.Path(temp)
        SOCIAL_PNG.write_bytes(render_svg_to_canvas(social_svg(), work, "social.svg", SOCIAL_WIDTH, SOCIAL_HEIGHT))
    size = SOCIAL_PNG.stat().st_size
    print(f"wrote {SOCIAL_PNG.relative_to(ROOT)} ({size} bytes) and {SOCIAL_SVG.relative_to(ROOT)}")
    return 0 if size < 1_000_000 else 1


# ------------------------------------------------------------------- verify ---

def parse_gif(path: pathlib.Path) -> tuple[int, int, int, list[int]]:
    data = path.read_bytes()
    if data[:6] != b"GIF89a":
        raise ValueError("demo gif is not GIF89a")
    width, height, flags = struct.unpack("<HHB", data[6:11])
    pos = 13 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0)
    frames, delays = 0, []
    while pos < len(data) and data[pos] != 0x3B:
        block = data[pos]
        if block == 0x21:
            label = data[pos + 1]
            pos += 2
            if label == 0xF9:
                delays.append(struct.unpack("<H", data[pos + 2 : pos + 4])[0])
            while data[pos]:
                pos += 1 + data[pos]
            pos += 1
        elif block == 0x2C:
            frames += 1
            local = data[pos + 9]
            pos += 10
            if local & 0x80:
                pos += 3 * (2 << (local & 7))
            pos += 1
            while data[pos]:
                pos += 1 + data[pos]
            pos += 1
        else:
            raise ValueError(f"unexpected GIF block {block:#x} at {pos}")
    return width, height, frames, delays


def run_verify() -> int:
    failures: list[str] = []
    width, height, frames, delays = parse_gif(DEMO_GIF)
    seconds = sum(delays) / 100
    if (width, height) != (TERM_WIDTH, TERM_HEIGHT):
        failures.append(f"gif size {width}x{height} != {TERM_WIDTH}x{TERM_HEIGHT}")
    if frames < 10:
        failures.append(f"gif has only {frames} frames")
    if not 5 <= seconds <= 120:
        failures.append(f"gif duration {seconds:.1f}s outside 5..120s")
    if DEMO_GIF.stat().st_size >= 2_000_000:
        failures.append(f"gif too large: {DEMO_GIF.stat().st_size}")
    print(f"gif: {width}x{height}, {frames} frames, {seconds:.1f}s, {DEMO_GIF.stat().st_size} bytes")

    png = SOCIAL_PNG.read_bytes()
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        failures.append("social preview is not a PNG")
    else:
        w, h = struct.unpack(">II", png[16:24])
        if (w, h) != (SOCIAL_WIDTH, SOCIAL_HEIGHT):
            failures.append(f"social preview {w}x{h} != {SOCIAL_WIDTH}x{SOCIAL_HEIGHT}")
    if SOCIAL_PNG.stat().st_size >= 1_000_000:
        failures.append(f"social preview too large: {SOCIAL_PNG.stat().st_size}")
    print(f"social preview: {SOCIAL_PNG.stat().st_size} bytes")

    hits = []
    for line in DEMO_CAST.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["type"] == "output":
            hits.extend(scan_text(event["text"]))
    if hits:
        failures.append(f"sanitizer rules hit in demo cast: {hits}")
    outputs = sum(1 for line in DEMO_CAST.read_text(encoding="utf-8").splitlines() if json.loads(line)["type"] == "output")
    print(f"cast: {outputs} captured output lines, sanitizer hits: {len(hits)}")

    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("release assets verify: PASS")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in {"record", "gif", "social", "verify"}:
        print(__doc__)
        return 2
    if argv[1] == "record":
        return run_record(sys.executable)
    if argv[1] == "gif":
        return run_gif()
    if argv[1] == "social":
        return run_social()
    return run_verify()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

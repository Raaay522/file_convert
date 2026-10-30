"""JPG 轉 PDF：JPEG 原始資料直接嵌入 PDF，不重新壓縮、畫質不變。

python jpg_to_pdf.pyw                                  開視窗
python jpg_to_pdf.pyw a.jpg b.jpg 資料夾                開視窗並先加入圖片（把圖片拖到本檔圖示上也一樣）
python jpg_to_pdf.pyw a.jpg b.jpg --out 輸出.pdf        不開視窗，直接輸出
"""
import argparse
import io
import math
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFilter, ImageOps

A4 = (595.276, 841.890)  # pt
MM = 72 / 25.4
MAX_PAGE = 14400  # PDF 頁面邊長上限（pt）
MARGIN_MM = {"none": 0, "small": 10, "large": 20}
COLOR_SPACE = {"L": "DeviceGray", "RGB": "DeviceRGB", "CMYK": "DeviceCMYK"}
IMAGE_EXT = (".jpg", ".jpeg")


def natural_key(path):
    name = os.path.basename(path).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def expand(paths):
    """資料夾展開成其中的 JPG，依檔名自然排序。"""
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted((os.path.join(p, n) for n in os.listdir(p) if n.lower().endswith(IMAGE_EXT)),
                            key=natural_key)
        else:
            files.append(p)
    return [os.path.normpath(p) for p in files]


def read_jpeg(path):
    """回傳 JPEG 資料與嵌入需要的資訊；能直接嵌入就不重新壓縮。"""
    with Image.open(path) as im:
        orientation = im.getexif().get(0x0112, 1)
        dpi = im.info.get("dpi", (0, 0))[0]
        if im.format == "JPEG" and im.mode in COLOR_SPACE and orientation in (1, 3, 6, 8):
            with open(path, "rb") as f:
                data = f.read()
            adobe_cmyk = im.mode == "CMYK" and "adobe" in im.info
            return data, im.size, im.mode, adobe_cmyk, orientation, dpi
        # 鏡像方向或非 JPEG：轉正後以高畫質重新壓縮
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("L", "RGB"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=95)
        return buf.getvalue(), im.size, im.mode, False, 1, dpi


def page_geometry(dw, dh, dpi, page="a4", orient="auto", margin="none"):
    """依轉正後的圖片尺寸回傳頁面寬高與圖片位置（pt，原點在左下）。"""
    if page == "a4":
        portrait = dh >= dw if orient == "auto" else orient == "portrait"
        pw, ph = A4 if portrait else A4[::-1]
        m = MARGIN_MM[margin] * MM
        s = min((pw - 2 * m) / dw, (ph - 2 * m) / dh)
    else:
        s = 72 / (dpi if dpi and dpi >= 1 else 96)
        s = min(s, MAX_PAGE / max(dw, dh))
        pw, ph = dw * s, dh * s
    iw, ih = dw * s, dh * s
    return pw, ph, (pw - iw) / 2, (ph - ih) / 2, iw, ih


def image_matrix(orientation, x, y, iw, ih):
    return {
        1: (iw, 0, 0, ih, x, y),
        3: (-iw, 0, 0, -ih, x + iw, y + ih),
        6: (0, -ih, iw, 0, x, y + ih),
        8: (0, ih, -iw, 0, x + iw, y),
    }[orientation]


def num(v):
    return f"{v:.3f}".rstrip("0").rstrip(".") or "0"


def write_pdf(items, out, page="a4", orient="auto", margin="none", progress=None):
    """items：[(圖片路徑, 順時針旋轉角度)]，每張一頁。"""
    n = len(items)
    offsets = [0] * (3 + 3 * n)
    tmp = out + ".part"
    try:
        with open(tmp, "wb") as f:
            def put(i, head, stream=None):
                offsets[i] = f.tell()
                f.write(f"{i} 0 obj\n{head}\n".encode())
                if stream is not None:
                    f.write(b"stream\n" + stream + b"\nendstream\n")
                f.write(b"endobj\n")

            f.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
            put(1, "<< /Type /Catalog /Pages 2 0 R >>")
            kids = " ".join(f"{3 + 3 * i} 0 R" for i in range(n))
            put(2, f"<< /Type /Pages /Kids [{kids}] /Count {n} >>")
            for i, (path, rotate) in enumerate(items):
                try:
                    data, size, mode, adobe_cmyk, orientation, dpi = read_jpeg(path)
                except Exception as e:
                    raise RuntimeError(f"{os.path.basename(path)}：{e}") from e
                dw, dh = size[::-1] if orientation in (6, 8) else size
                pw, ph, x, y, iw, ih = page_geometry(dw, dh, dpi, page, orient, margin)
                p, c, m = 3 + 3 * i, 4 + 3 * i, 5 + 3 * i
                matrix = image_matrix(orientation, x, y, iw, ih)
                content = f"q {' '.join(num(v) for v in matrix)} cm /Im0 Do Q".encode()
                decode = " /Decode [1 0 1 0 1 0 1 0]" if adobe_cmyk else ""
                rot = f" /Rotate {rotate}" if rotate else ""
                put(p, f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {num(pw)} {num(ph)}]{rot} "
                       f"/Resources << /XObject << /Im0 {m} 0 R >> >> /Contents {c} 0 R >>")
                put(c, f"<< /Length {len(content)} >>", content)
                put(m, f"<< /Type /XObject /Subtype /Image /Width {size[0]} /Height {size[1]} "
                       f"/ColorSpace /{COLOR_SPACE[mode]} /BitsPerComponent 8{decode} "
                       f"/Filter /DCTDecode /Length {len(data)} >>", data)
                if progress:
                    progress(i + 1, n)
            xref = f.tell()
            f.write(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
            for off in offsets[1:]:
                f.write(f"{off:010d} 00000 n \n".encode())
            f.write(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def load_preview(path, box):
    """回傳轉正後的縮圖、轉正後的原圖尺寸與 DPI。"""
    with Image.open(path) as im:
        orientation = im.getexif().get(0x0112, 1)
        dpi = im.info.get("dpi", (0, 0))[0]
        w, h = im.size
        im.draft("RGB", (box, box))
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((box, box), Image.LANCZOS)
    return im, ((h, w) if orientation in (5, 6, 7, 8) else (w, h)), dpi


# ---------- 視窗 ----------

KAI, TIMES, SYMBOL = "標楷體", "Times New Roman", "Segoe UI Symbol"
C = {
    "bg": "#f3f5f8", "panel": "#ffffff", "line": "#dfe4ea", "well": "#e9edf2", "track": "#e6eaef",
    "ink": "#1d2733", "muted": "#475765", "off": "#778b9c", "warn": "#965b0c", "ok": "#297047",
    "accent": "#0a64d6", "accent_hover": "#0958bd", "accent_press": "#074ca3",
    "accent_off": "#a9bfd8", "hover": "#f1f4f7", "press": "#e3e8ee",
}


def runs(text):
    """依中文／英數切段，各段套各自字型。"""
    out = []
    for ch in text:
        cjk = ord(ch) >= 0x2E80
        if out and out[-1][0] == cjk:
            out[-1][1] += ch
        else:
            out.append([cjk, ch])
    return [(KAI if cjk else TIMES, s) for cjk, s in out]


def rounded(w, h, r, fill, outline=None, pad=0, blur=0, alpha=0, dy=0):
    """圓角矩形（4 倍取樣抗鋸齒），可帶柔和陰影；pad 是陰影預留的外圍。"""
    img = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    if alpha:
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([pad, pad + dy, pad + w - 1, pad + h - 1 + dy], r, fill=alpha)
        img = Image.new("RGBA", img.size, (20, 36, 52, 0))
        img.putalpha(mask.filter(ImageFilter.GaussianBlur(blur)))
    k = 4
    big = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle([0, 0, w * k - 1, h * k - 1], r * k, fill=fill, outline=outline,
                                          width=k if outline else 0)
    img.alpha_composite(big.resize((w, h), Image.LANCZOS), (pad, pad))
    return img


class Spring:
    """臨界阻尼彈簧：response 是到位所需的大約秒數，沒有固定時長，可隨時改目標。"""

    def __init__(self, value, response=0.35, damping=1.0):
        self.x = self.target = value
        self.v = 0.0
        w = 2 * math.pi / response
        self.k, self.c = w * w, 2 * damping * w

    def step(self, dt):
        self.v += (-self.k * (self.x - self.target) - self.c * self.v) * dt
        self.x += self.v * dt

    def settled(self):
        return abs(self.x - self.target) < 0.3 and abs(self.v) < 4

    def snap(self, value=None):
        if value is not None:
            self.target = value
        self.x, self.v = self.target, 0.0


class Mover:
    """canvas 上一組 tag 相同的物件，以兩條獨立彈簧（X、Y）移動。"""

    def __init__(self, canvas, tag, x, y, response=0.35):
        self.cv, self.tag = canvas, tag
        self.sx, self.sy = Spring(x, response), Spring(y, response)
        self.dx, self.dy = x, y

    def place(self, x, y):
        self.sx.snap(x)
        self.sy.snap(y)
        self.draw()

    def draw(self):
        self.cv.move(self.tag, self.sx.x - self.dx, self.sy.x - self.dy)
        self.dx, self.dy = self.sx.x, self.sy.x

    def tick(self, dt):
        n = max(1, math.ceil(dt * 240))
        for _ in range(n):
            self.sx.step(dt / n)
            self.sy.step(dt / n)
        done = self.sx.settled() and self.sy.settled()
        if done:
            self.sx.snap()
            self.sy.snap()
        self.draw()
        return not done


class Card(Mover):
    def __init__(self, canvas, tag, path, x, y):
        super().__init__(canvas, tag, x, y)
        self.path = path
        self.rotate = 0
        self.thumb = self.size = self.error = None
        self.dpi = 0
        self.future = None
        self.photo = None


def run_gui(initial):
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import filedialog
    from PIL import ImageTk

    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    root.title("JPG 轉 PDF")
    S = root.winfo_fpixels("1i") / 96

    def px(v):
        return max(1, round(v * S))

    fonts = {}

    def font(family, size, bold=False):
        key = (family, size, bold)
        if key not in fonts:
            fonts[key] = tkfont.Font(root, family=family, size=size, weight="bold" if bold else "normal")
        return fonts[key]

    def measure(text, size, bold=False):
        return sum(font(f, size, bold).measure(s) for f, s in runs(text))

    def fit(text, size, max_w, bold=False):
        """太長就從中間截斷，頭尾各留一半。"""
        if measure(text, size, bold) <= max_w:
            return text
        head, tail = text[:len(text) // 2], text[len(text) // 2:]
        while (head or tail) and measure(head + "…" + tail, size, bold) > max_w:
            if len(head) >= len(tail):
                head = head[:-1]
            else:
                tail = tail[1:]
        return head + "…" + tail

    def draw_text(cv, x, y, text, size, fill, tags=(), anchor="center", bold=False):
        """中英混排；y 是文字的垂直中線，各段對齊同一條基線。"""
        parts = [(font(f, size, bold), s) for f, s in runs(text)]
        if not parts:
            return 0
        widths = [f.measure(s) for f, s in parts]
        asc = max(f.metrics("ascent") for f, _ in parts)
        desc = max(f.metrics("descent") for f, _ in parts)
        base = y + (asc - desc) / 2
        x0 = {"center": x - sum(widths) / 2, "w": x, "e": x - sum(widths)}[anchor]
        for (f, s), w in zip(parts, widths):
            cv.create_text(x0, base - f.metrics("ascent"), text=s, font=f, fill=fill, anchor="nw", tags=tags)
            x0 += w
        return sum(widths)

    def photo(img):
        return ImageTk.PhotoImage(img, master=root)

    # ---------- 動畫 ----------
    anim = {"items": set(), "running": False, "last": 0.0}

    def kick(obj):
        anim["items"].add(obj)
        if not anim["running"]:
            anim["running"] = True
            anim["last"] = time.perf_counter()
            root.after(0, tick)

    def tick():
        now = time.perf_counter()
        dt = min(now - anim["last"], 1 / 30)
        anim["last"] = now
        for obj in list(anim["items"]):
            if not obj.tick(dt):
                anim["items"].discard(obj)
        if anim["items"]:
            root.after(8, tick)
        else:
            anim["running"] = False

    # ---------- 元件 ----------
    class TextLabel(tk.Canvas):
        def __init__(self, parent, text="", size=16, bold=False, fill=C["ink"], wrap=None):
            self.size, self.bold, self.fill, self.wrap = size, bold, fill, wrap
            self.line_h = font(TIMES, size, bold).metrics("linespace") + px(2)
            super().__init__(parent, bg=parent["bg"], highlightthickness=0, bd=0, height=self.line_h,
                             width=wrap or 1)
            self.set(text)

        def set(self, text, fill=None):
            self.delete("all")
            lines = []
            for para in text.split("\n"):
                line = ""
                for ch in para:
                    if self.wrap and line and measure(line + ch, self.size, self.bold) > self.wrap:
                        lines.append(line)
                        line = ""
                    line += ch
                lines.append(line)
            if not text:
                lines = []
            width = 1
            for i, line in enumerate(lines):
                width = max(width, draw_text(self, 0, (i + 0.5) * self.line_h, line, self.size,
                                             fill or self.fill, anchor="w", bold=self.bold))
            self.configure(height=max(1, len(lines)) * self.line_h if lines else 1,
                           width=self.wrap or math.ceil(width))

    class PillButton(tk.Canvas):
        """按下立刻有回饋；放開時游標還在按鈕上才執行，拖出去就取消。"""

        def __init__(self, parent, text, command, primary=False, width=None, height=40):
            self.command, self.primary, self.text = command, primary, text
            self.enabled, self.pressed, self.inside = True, False, False
            h = px(height)
            w = width or math.ceil(measure(text, 16, primary)) + px(36)
            super().__init__(parent, bg=parent["bg"], width=w, height=h, highlightthickness=0, bd=0,
                             cursor="hand2")
            r = px(10)
            if primary:
                fills = {"normal": C["accent"], "hover": C["accent_hover"], "press": C["accent_press"],
                         "off": C["accent_off"]}
                self.imgs = {k: photo(rounded(w, h, r, v)) for k, v in fills.items()}
            else:
                fills = {"normal": "#ffffff", "hover": C["hover"], "press": C["press"], "off": "#ffffff"}
                self.imgs = {k: photo(rounded(w, h, r, v, outline=C["line"])) for k, v in fills.items()}
            self.bg_item = self.create_image(0, 0, anchor="nw", image=self.imgs["normal"])
            self.w, self.h = w, h
            self.set_text(text)
            self.bind("<ButtonPress-1>", self.on_press)
            self.bind("<ButtonRelease-1>", self.on_release)
            self.bind("<Enter>", lambda e: self.hover(True))
            self.bind("<Leave>", lambda e: self.hover(False))

        def text_color(self):
            if self.primary:
                return "#ffffff"
            return C["ink"] if self.enabled else C["off"]

        def set_text(self, text):
            self.text = text
            self.delete("label")
            draw_text(self, self.w / 2, self.h / 2, text, 16, self.text_color(), tags=("label",),
                      bold=self.primary)

        def paint(self):
            state = ("off" if not self.enabled else "press" if self.pressed and self.inside
                     else "hover" if self.inside else "normal")
            self.itemconfigure(self.bg_item, image=self.imgs[state])

        def set_enabled(self, enabled):
            if enabled != self.enabled:
                self.enabled = enabled
                self.configure(cursor="hand2" if enabled else "arrow")
                self.set_text(self.text)
                self.paint()

        def hover(self, inside):
            self.inside = inside
            self.paint()

        def on_press(self, e):
            self.pressed = self.enabled
            self.paint()

        def on_release(self, e):
            fire = self.pressed and 0 <= e.x < self.w and 0 <= e.y < self.h
            self.pressed = False
            self.paint()
            if fire:
                self.command()

    class Segmented(tk.Canvas):
        """分段選擇：白色滑塊以彈簧移到選中的那一格。"""

        def __init__(self, parent, width, options, value, command):
            self.options, self.command = options, command
            self.enabled = True
            h, self.pad = px(40), px(3)
            super().__init__(parent, bg=parent["bg"], width=width, height=h, highlightthickness=0, bd=0,
                             cursor="hand2")
            self.w, self.h = width, h
            self.seg = (width - 2 * self.pad) / len(options)
            self.track = photo(rounded(width, h, px(10), C["track"]))
            self.create_image(0, 0, anchor="nw", image=self.track)
            sp = px(6)
            self.pill_pad = sp
            self.pill = photo(rounded(round(self.seg), h - 2 * self.pad, px(8), "#ffffff", pad=sp,
                                      blur=px(3), alpha=46, dy=px(1)))
            self.index = [v for v, _ in options].index(value)
            x0 = self.pad + self.index * self.seg - sp
            self.create_image(x0, self.pad - sp, anchor="nw", image=self.pill, tags=("pill",))
            self.mover = Mover(self, "pill", x0, 0, response=0.3)
            for i, (_, label) in enumerate(options):
                draw_text(self, self.pad + (i + 0.5) * self.seg, h / 2, label, 16, C["ink"], tags=(f"t{i}",))
            self.recolor()
            self.bind("<ButtonPress-1>", self.on_press)

        def recolor(self):
            for i in range(len(self.options)):
                color = C["off"] if not self.enabled else C["ink"] if i == self.index else C["muted"]
                self.itemconfigure(f"t{i}", fill=color)

        def on_press(self, e):
            if not self.enabled:
                return
            i = min(len(self.options) - 1, max(0, int((e.x - self.pad) // self.seg)))
            if i == self.index:
                return
            self.index = i
            self.recolor()
            self.mover.sx.target = self.pad + i * self.seg - self.pill_pad
            kick(self.mover)
            self.command(self.options[i][0])

        def set_enabled(self, enabled):
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
            self.itemconfigure("pill", state="normal" if enabled else "hidden")
            self.recolor()

    # ---------- 版面 ----------
    root.configure(bg=C["bg"])
    root.geometry(f"{px(1120)}x{px(740)}")
    root.minsize(px(760), px(520))

    side_w = px(300)
    side = tk.Frame(root, bg=C["panel"], width=side_w)
    side.pack(side="right", fill="y")
    side.pack_propagate(False)
    tk.Frame(root, bg=C["line"], width=1).pack(side="right", fill="y")
    main = tk.Frame(root, bg=C["bg"])
    main.pack(side="left", fill="both", expand=True)

    head = tk.Frame(main, bg=C["bg"])
    head.pack(fill="x", padx=px(24), pady=(px(20), px(6)))
    TextLabel(head, "JPG 轉 PDF", 22, bold=True).pack(side="left")
    count = TextLabel(head, "", 16, fill=C["muted"])
    count.pack(side="left", padx=px(12))

    grid = tk.Canvas(main, bg=C["bg"], highlightthickness=0, bd=0, yscrollincrement=1)
    grid.pack(fill="both", expand=True)

    state = {"page": "a4", "orient": "auto", "margin": "none", "busy": False, "out": None,
             "progress": None, "result": None, "drops": [], "laid_out": False}
    cards = []
    ids = iter(range(1, 10 ** 9))

    # 卡片尺寸
    CW, CH, SH = px(176), px(214), px(20)
    INSET = px(10)
    WELL = CW - 2 * INSET
    BOX = WELL - px(20)
    GAP, PAD = px(18), px(24)
    imgs = {
        "card": photo(rounded(CW, CH, px(14), "#ffffff", pad=SH, blur=px(5), alpha=30, dy=px(2))),
        "hover": photo(rounded(CW, CH, px(14), "#ffffff", pad=SH, blur=px(7), alpha=46, dy=px(3))),
        "lifted": photo(rounded(CW, CH, px(14), "#ffffff", pad=SH, blur=px(11), alpha=70, dy=px(8))),
        "well": photo(rounded(WELL, WELL, px(10), C["well"])),
        "zone": None,
    }
    BADGE = px(34)
    imgs["badge"] = photo(rounded(BADGE, px(22), px(11), C["well"]))

    # ---------- 設定欄 ----------
    inner = tk.Frame(side, bg=C["panel"])
    inner.pack(fill="both", expand=True, padx=px(24), pady=px(24))
    inner_w = side_w - 2 * px(24)
    segs = {}

    def set_option(key, value):
        state[key] = value
        for k in ("orient", "margin"):
            segs[k].set_enabled(state["page"] == "a4")
        for c in cards:
            refresh_preview(c)

    for key, title, options in (
            ("page", "頁面大小", [("a4", "A4"), ("original", "原圖大小")]),
            ("orient", "方向", [("auto", "自動"), ("portrait", "直式"), ("landscape", "橫式")]),
            ("margin", "邊界", [("none", "無"), ("small", "小"), ("large", "大")])):
        TextLabel(inner, title, 16, bold=True).pack(anchor="w", pady=(0, px(8)))
        segs[key] = Segmented(inner, inner_w, options, state[key], lambda v, k=key: set_option(k, v))
        segs[key].pack(anchor="w", pady=(0, px(22)))

    convert_btn = PillButton(inner, "轉換成 PDF", lambda: convert(), primary=True, width=inner_w, height=48)
    convert_btn.pack(side="bottom")
    result_box = tk.Frame(inner, bg=C["panel"])
    result_box.pack(side="bottom", fill="x", pady=(0, px(12)))
    status = TextLabel(result_box, "", 16, fill=C["muted"], wrap=inner_w)
    status.pack(anchor="w")
    open_btn = PillButton(result_box, "開啟 PDF", lambda: os.startfile(state["out"]), width=inner_w)

    def set_status(text, color=C["muted"]):
        status.set(text, color)

    sort_btn = PillButton(head, "依檔名排序", lambda: sort_by_name())
    add_btn = PillButton(head, "加入圖片", lambda: add_dialog())
    add_btn.pack(side="right")
    sort_btn.pack(side="right", padx=(0, px(8)))

    # ---------- 格狀排列 ----------
    def metrics():
        w = grid.winfo_width()
        cols = max(1, (w - 2 * PAD + GAP) // (CW + GAP))
        left = (w - (cols * CW + (cols - 1) * GAP)) / 2
        return cols, left

    def slot(i):
        cols, left = metrics()
        return left + (i % cols) * (CW + GAP), PAD + (i // cols) * (CH + GAP)

    def slot_index(cx, cy):
        cols, left = metrics()
        col = min(cols - 1, max(0, round((cx - left - CW / 2) / (CW + GAP))))
        row = max(0, round((cy - PAD - CH / 2) / (CH + GAP)))
        return min(len(cards) - 1, row * cols + col)

    def relayout(skip=None):
        snap = not state["laid_out"]
        state["laid_out"] = grid.winfo_width() > 1
        for i, c in enumerate(cards):
            grid.itemconfigure(c.tag + "_no", text=str(i + 1))
            if c is skip:
                continue
            x, y = slot(i)
            if snap:
                c.place(x, y)
            else:
                c.sx.target, c.sy.target = x, y
                kick(c)
        cols, _ = metrics()
        rows = math.ceil(len(cards) / cols)
        height = 2 * PAD + rows * CH + max(0, rows - 1) * GAP
        grid.configure(scrollregion=(0, 0, grid.winfo_width(), max(height, grid.winfo_height())))
        count.set(f"{len(cards)} 張" if cards else "")
        convert_btn.set_enabled(bool(cards) and not state["busy"])
        sort_btn.set_enabled(len(cards) > 1)
        draw_empty()
        update_scrollbar()

    def draw_empty():
        grid.delete("empty")
        if cards:
            return
        w, h = grid.winfo_width(), grid.winfo_height()
        zw, zh = min(px(520), w - 2 * PAD), px(280)
        if zw < px(200):
            return
        if not imgs["zone"] or imgs["zone"].width() != zw:
            imgs["zone"] = photo(rounded(zw, zh, px(18), "#ffffff", outline=C["line"]))
            imgs["zone_hover"] = photo(rounded(zw, zh, px(18), "#f7faff", outline="#b9cde6"))
            imgs["plus"] = photo(rounded(px(64), px(64), px(32), C["accent"]))
        cx, cy = w / 2, grid.canvasy(0) + h / 2 - px(20)
        grid.create_image(cx, cy, image=imgs["zone"], tags=("empty", "empty_bg"))
        grid.create_image(cx, cy - px(56), image=imgs["plus"], tags=("empty",))
        grid.create_text(cx, cy - px(58), text="+", font=font(TIMES, 30), fill="#ffffff", tags=("empty",))
        draw_text(grid, cx, cy + px(20), "選擇圖片", 22, C["ink"], tags=("empty",), bold=True)
        draw_text(grid, cx, cy + px(58), "或拖曳到這裡", 13, C["muted"], tags=("empty",))

    def update_scrollbar():
        """捲動指示條，以及內容捲到標題列下方時的淡出邊。"""
        grid.delete("sbar")
        top, bottom = grid.yview()
        if bottom - top >= 1:
            return
        h = grid.winfo_height()
        x = grid.winfo_width() - px(8)
        y0 = grid.canvasy(0)
        if top > 0:
            if imgs.get("fade_w") != grid.winfo_width():
                fade = Image.new("RGBA", (grid.winfo_width(), px(18)), C["bg"])
                fade.putalpha(Image.linear_gradient("L").rotate(180).resize(fade.size))
                imgs["fade"], imgs["fade_w"] = photo(fade), grid.winfo_width()
            grid.create_image(0, y0, anchor="nw", image=imgs["fade"], tags=("sbar",))
        grid.create_rectangle(x, y0 + px(6) + top * (h - px(12)), x + px(4), y0 + px(6) + bottom * (h - px(12)),
                              fill="#b8c2cc", outline="", tags=("sbar",))

    def make_card(path):
        tag = f"c{next(ids)}"
        x, y = slot(len(cards))
        c = Card(grid, tag, path, x, y)
        grid.create_image(x - SH, y - SH, anchor="nw", image=imgs["card"], tags=(tag, tag + "_base"))
        grid.create_image(x + INSET, y + INSET, anchor="nw", image=imgs["well"], tags=(tag,))
        c.page_item = grid.create_image(x + CW / 2, y + INSET + WELL / 2, tags=(tag,))
        line_y = y + INSET + WELL + (CH - INSET - WELL) / 2
        grid.create_image(x + INSET, line_y, anchor="w", image=imgs["badge"], tags=(tag,))
        grid.create_text(x + INSET + BADGE / 2, line_y, text="", font=font(TIMES, 13), fill=C["muted"],
                         tags=(tag, tag + "_no"))
        name = os.path.basename(path)
        name_w = CW - 2 * INSET - BADGE - px(8)
        draw_text(grid, x + INSET + BADGE + px(8), line_y, fit(name, 13, name_w),
                  13, C["ink"], tags=(tag,), anchor="w")
        r = px(13)
        for kind, cx, symbol in (("rot", x + CW - INSET - px(48), "↻"), ("del", x + CW - INSET - px(18), "✕")):
            cy = y + INSET + px(18)
            grid.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#ffffff", outline=C["line"], state="hidden",
                             tags=(tag, tag + "_ctl", tag + "_" + kind, tag + "_" + kind + "_bg"))
            grid.create_text(cx, cy, text=symbol, font=font(SYMBOL, 11), fill=C["ink"], state="hidden",
                             tags=(tag, tag + "_ctl", tag + "_" + kind))
        c.future = pool.submit(load_preview, path, 2 * BOX)
        return c

    def compose(c):
        """依目前設定畫出這張的 PDF 頁面縮圖。"""
        pw, ph, x, y, iw, ih = page_geometry(*c.size, c.dpi, state["page"], state["orient"], state["margin"])
        s = BOX / max(pw, ph)
        page = Image.new("RGB", (max(1, round(pw * s)), max(1, round(ph * s))), "white")
        page.paste(c.thumb.resize((max(1, round(iw * s)), max(1, round(ih * s))), Image.LANCZOS),
                   (round(x * s), round((ph - y - ih) * s)))
        if c.rotate:
            page = page.transpose({90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
                                   270: Image.Transpose.ROTATE_90}[c.rotate])
        ImageDraw.Draw(page).rectangle([0, 0, page.width - 1, page.height - 1], outline="#c9d1da")
        return page

    def refresh_preview(c):
        if c.thumb is not None:
            c.photo = photo(compose(c))
            grid.itemconfigure(c.page_item, image=c.photo)

    def poll_previews():
        pending = False
        for c in cards:
            if c.future is None:
                continue
            if not c.future.done():
                pending = True
                continue
            try:
                c.thumb, c.size, c.dpi = c.future.result()
                refresh_preview(c)
            except Exception:
                c.error = True
                draw_text(grid, c.dx + CW / 2, c.dy + INSET + WELL / 2, "無法讀取", 16, C["warn"], tags=(c.tag,))
            c.future = None
        if pending:
            root.after(40, poll_previews)

    def add_files(paths):
        files = expand(paths)
        keep = [p for p in files if p.lower().endswith(IMAGE_EXT) and os.path.isfile(p)]
        have = {c.path for c in cards}
        new = sorted({p for p in keep if p not in have}, key=natural_key)
        for p in new:
            cards.append(make_card(p))
        skipped = len(files) - len(keep)
        set_status(f"略過 {skipped} 個非 JPG 檔案" if skipped else "", C["warn"])
        relayout()
        poll_previews()

    def add_dialog():
        chosen = filedialog.askopenfilenames(
            parent=root, title="選擇圖片", filetypes=[("JPG", "*.jpg *.jpeg"), ("所有檔案", "*.*")],
            initialdir=os.path.dirname(cards[-1].path) if cards else None)
        if chosen:
            add_files(chosen)

    def sort_by_name():
        cards.sort(key=lambda c: natural_key(c.path))
        relayout()

    def remove(c):
        grid.delete(c.tag)
        anim["items"].discard(c)
        cards.remove(c)
        hover["card"] = None
        relayout()

    def rotate(c):
        c.rotate = (c.rotate + 90) % 360
        refresh_preview(c)

    # ---------- 滑鼠 ----------
    hover = {"card": None}
    drag = {}
    press = {}

    def canvas_xy(e):
        return grid.canvasx(e.x), grid.canvasy(e.y)

    def card_at(x, y):
        for c in reversed(cards):
            if c.dx <= x < c.dx + CW and c.dy <= y < c.dy + CH:
                return c
        return None

    def control_at():
        item = grid.find_withtag("current")
        tags = grid.gettags(item[0]) if item else ()
        for c in cards:
            for kind in ("rot", "del"):
                if c.tag + "_" + kind in tags:
                    return c, kind
        return None

    def set_hover(c):
        old = hover["card"]
        if old is c:
            return
        if old is not None and old in cards:
            grid.itemconfigure(old.tag + "_ctl", state="hidden")
            grid.itemconfigure(old.tag + "_base", image=imgs["card"])
        hover["card"] = c
        if c is not None:
            grid.itemconfigure(c.tag + "_ctl", state="normal")
            grid.itemconfigure(c.tag + "_base", image=imgs["hover"])

    def paint_control(target, shade):
        if target:
            c, kind = target
            grid.itemconfigure(c.tag + "_" + kind + "_bg", fill=shade)

    def on_motion(e):
        if drag:
            return
        x, y = canvas_xy(e)
        set_hover(card_at(x, y))
        ctl = control_at()
        for c in cards:
            for kind in ("rot", "del"):
                grid.itemconfigure(c.tag + "_" + kind + "_bg", fill="#ffffff")
        paint_control(ctl, C["hover"])
        over_empty = "empty" in grid.gettags("current")
        if imgs["zone"] is not None:
            grid.itemconfigure("empty_bg", image=imgs["zone_hover" if over_empty else "zone"])
        grid.configure(cursor="hand2" if ctl or over_empty else "fleur" if hover["card"] else "")

    def on_press(e):
        x, y = canvas_xy(e)
        ctl = control_at()
        if ctl:
            press["ctl"] = ctl
            paint_control(ctl, C["press"])
            return
        if "empty" in grid.gettags("current"):
            press["empty"] = True
            return
        c = card_at(x, y)
        if c:
            drag.update(card=c, grab=(x - c.dx, y - c.dy), start=(e.x, e.y), active=False,
                        history=[(time.perf_counter(), c.dx, c.dy)], pointer=(e.x, e.y))

    def drag_to(wx, wy):
        c = drag["card"]
        x, y = grid.canvasx(wx) - drag["grab"][0], grid.canvasy(wy) - drag["grab"][1]
        c.place(x, y)
        drag["history"] = (drag["history"] + [(time.perf_counter(), x, y)])[-6:]
        i = slot_index(x + CW / 2, y + CH / 2)
        if cards.index(c) != i:
            cards.remove(c)
            cards.insert(i, c)
            relayout(skip=c)
        update_scrollbar()

    class AutoScroll:
        """拖到上下邊緣時捲動，越靠邊越快。"""
        acc = 0.0

        def tick(self, dt):
            if not drag.get("active"):
                return False
            wy, h, edge = drag["pointer"][1], grid.winfo_height(), px(56)
            speed = (-(edge - wy) if wy < edge else (wy - (h - edge)) if wy > h - edge else 0) / edge * px(900)
            if not speed:
                return False
            self.acc += speed * dt
            n = int(self.acc)
            self.acc -= n
            if n:
                grid.yview_scroll(n, "units")
                drag_to(*drag["pointer"])
                update_scrollbar()
            return True

    autoscroll = AutoScroll()

    def on_drag(e):
        if "ctl" in press:
            paint_control(press["ctl"], C["press"] if control_at() == press["ctl"] else "#ffffff")
            return
        if not drag:
            return
        drag["pointer"] = (e.x, e.y)
        if not drag["active"]:
            if math.dist(drag["start"], (e.x, e.y)) < px(6):
                return
            c = drag["card"]
            drag["active"] = True
            anim["items"].discard(c)
            set_hover(None)
            grid.tag_raise(c.tag)
            grid.itemconfigure(c.tag + "_base", image=imgs["lifted"])
            grid.configure(cursor="fleur")
        drag_to(e.x, e.y)
        kick(autoscroll)

    def on_release(e):
        if "ctl" in press:
            ctl = press.pop("ctl")
            paint_control(ctl, "#ffffff")
            if control_at() == ctl:
                (rotate if ctl[1] == "rot" else remove)(ctl[0])
            return
        if press.pop("empty", False):
            if "empty" in grid.gettags("current"):
                add_dialog()
            return
        if not drag:
            return
        c, active, history = drag["card"], drag["active"], drag["history"]
        drag.clear()
        if not active:
            return
        # 放開時延續拖曳速度，再由彈簧帶回格子
        now = time.perf_counter()
        recent = [h for h in history if now - h[0] < 0.1] or history[-1:]
        t0, x0, y0 = recent[0]
        t1, x1, y1 = history[-1]
        if t1 > t0:
            c.sx.v, c.sy.v = (x1 - x0) / (t1 - t0), (y1 - y0) / (t1 - t0)
        c.sx.target, c.sy.target = slot(cards.index(c))
        grid.itemconfigure(c.tag + "_base", image=imgs["card"])
        kick(c)
        on_motion(e)

    def on_wheel(e):
        if root.winfo_containing(e.x_root, e.y_root) is not grid:
            return
        grid.yview_scroll(int(-e.delta / 120 * px(60)), "units")
        update_scrollbar()
        draw_empty()

    grid.bind("<Motion>", on_motion)
    grid.bind("<Leave>", lambda e: None if drag else set_hover(None))
    grid.bind("<ButtonPress-1>", on_press)
    grid.bind("<B1-Motion>", on_drag)
    grid.bind("<ButtonRelease-1>", on_release)
    grid.bind("<Configure>", lambda e: relayout())
    root.bind_all("<MouseWheel>", on_wheel)
    root.bind("<Control-o>", lambda e: add_dialog())

    # ---------- 轉換 ----------
    def convert():
        if not cards or state["busy"]:
            return
        if any(c.error for c in cards):
            set_status("有圖片無法讀取，請先移除", C["warn"])
            return
        first = os.path.dirname(cards[0].path)
        out = filedialog.asksaveasfilename(
            parent=root, title="輸出 PDF", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialdir=first, initialfile=(os.path.basename(first) or "output") + ".pdf")
        if not out:
            return
        out = os.path.normpath(out)
        items = [(c.path, c.rotate) for c in cards]
        options = (state["page"], state["orient"], state["margin"])
        state.update(busy=True, result=None, progress=(0, len(items)))
        convert_btn.set_enabled(False)
        open_btn.pack_forget()
        set_status("")

        def work():
            try:
                write_pdf(items, out, *options, progress=lambda i, n: state.update(progress=(i, n)))
                state["result"] = ("ok", out, len(items))
            except Exception as e:
                state["result"] = ("error", str(e), 0)

        threading.Thread(target=work, daemon=True).start()
        poll_convert()

    def poll_convert():
        if state["result"] is None:
            i, n = state["progress"]
            convert_btn.set_text(f"轉換中 {i}/{n}")
            root.after(50, poll_convert)
            return
        kind, value, n = state["result"]
        state["busy"] = False
        convert_btn.set_text("轉換成 PDF")
        convert_btn.set_enabled(bool(cards))
        if kind == "ok":
            state["out"] = value
            set_status(f"已輸出 {n} 頁：{os.path.basename(value)}", C["ok"])
            open_btn.pack(anchor="w", pady=(px(10), 0))
        else:
            set_status(f"失敗：{value}", C["warn"])

    # ---------- 從檔案總管拖檔進來 ----------
    def enable_drop():
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return
        user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_void_p)
        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = (ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                           wintypes.LPARAM)
        shell32.DragQueryFileW.argtypes = (ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT)
        shell32.DragFinish.argtypes = (ctypes.c_void_p,)
        shell32.DragAcceptFiles.argtypes = (wintypes.HWND, wintypes.BOOL)
        hooks = []
        for hwnd in {int(root.wm_frame(), 16), root.winfo_id(), grid.winfo_id()}:
            def proc(h, msg, wp, lp, old=[None]):
                if msg == 0x0233:  # WM_DROPFILES
                    paths = []
                    for i in range(shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)):
                        size = shell32.DragQueryFileW(wp, i, None, 0) + 1
                        buf = ctypes.create_unicode_buffer(size)
                        shell32.DragQueryFileW(wp, i, buf, size)
                        paths.append(buf.value)
                    shell32.DragFinish(wp)
                    state["drops"].append(paths)  # 交給 Tk 事件迴圈處理，不在視窗程序裡呼叫 Tk
                    return 0
                return user32.CallWindowProcW(old[0], h, msg, wp, lp)

            callback = WNDPROC(proc)
            proc.__defaults__[0][0] = user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(callback, ctypes.c_void_p))
            shell32.DragAcceptFiles(hwnd, True)
            hooks.append(callback)
        root._drop_hooks = hooks

    def poll_drops():
        while state["drops"]:
            add_files(state["drops"].pop(0))
        root.after(100, poll_drops)

    pool = ThreadPoolExecutor(max_workers=4)
    root.update_idletasks()
    enable_drop()
    poll_drops()
    root.after(30, lambda: add_files(initial))

    def close():
        pool.shutdown(wait=False, cancel_futures=True)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.app = {"cards": cards, "state": state, "grid": grid, "set_option": set_option, "add_files": add_files,
                "segs": segs, "relayout": relayout}
    return root


def main():
    parser = argparse.ArgumentParser(description="JPG 轉 PDF")
    parser.add_argument("files", nargs="*", help="圖片或資料夾，依給定順序成頁")
    parser.add_argument("--out", help="輸出 PDF 路徑；有給就不開視窗")
    parser.add_argument("--page", choices=["a4", "original"], default="a4", help="a4：放進 A4；original：原圖大小")
    parser.add_argument("--orient", choices=["auto", "portrait", "landscape"], default="auto",
                        help="A4 方向；auto 依圖片直橫")
    parser.add_argument("--margin", choices=list(MARGIN_MM), default="none", help="A4 邊界：無、10 mm、20 mm")
    args = parser.parse_args()
    files = expand(args.files)
    if args.out:
        if not files:
            sys.exit("沒有圖片")
        write_pdf([(p, 0) for p in files], args.out, args.page, args.orient, args.margin)
        print(f"已輸出 {len(files)} 頁：{args.out}")
    else:
        run_gui(files).mainloop()


if __name__ == "__main__":
    main()

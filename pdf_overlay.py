"""PDF の上に PNG を重ねて保存するGUIツール"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from io import BytesIO
import os

try:
    import fitz  # PyMuPDF
    from PIL import Image, ImageTk
except ImportError as e:
    import sys
    import subprocess
    print(f"依存ライブラリが不足しています: {e}")
    print("pip install PyMuPDF Pillow を実行してください")
    sys.exit(1)


class PDFOverlayTool:
    HANDLE_SIZE = 8

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PDF PNG オーバーレイツール")
        self.root.geometry("1000x780")
        self.root.minsize(700, 500)

        self.pdf_doc: fitz.Document | None = None
        self.pdf_path: str | None = None
        self.png_path: str | None = None
        self.current_page = 0

        # PDF描画スケール (表示用)
        self.display_scale = 1.5

        # PNGのPDF座標系での位置・サイズ
        self.png_x = 50.0
        self.png_y = 50.0
        self.png_w = 100.0
        self.png_h = 100.0

        # ドラッグ状態
        self._drag_mode: str | None = None  # "move" | "resize"
        self._drag_ox = 0.0
        self._drag_oy = 0.0

        # tkinter画像参照 (GC防止)
        self._pdf_photo: ImageTk.PhotoImage | None = None
        self._png_photo: ImageTk.PhotoImage | None = None
        self._png_pil: Image.Image | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ---- ツールバー ----
        bar = ttk.Frame(self.root, padding=(6, 4))
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(bar, text="📄 PDFを開く", command=self._open_pdf).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="🖼 PNGを開く", command=self._open_png).pack(side=tk.LEFT, padx=3)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(bar, text="◀", width=3, command=self._prev_page).pack(side=tk.LEFT)
        self._page_lbl = ttk.Label(bar, text="  —  ", width=12, anchor="center")
        self._page_lbl.pack(side=tk.LEFT)
        ttk.Button(bar, text="▶", width=3, command=self._next_page).pack(side=tk.LEFT)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(bar, text="💾 保存", command=self._save_pdf).pack(side=tk.LEFT, padx=3)

        # ---- プロパティパネル ----
        prop = ttk.LabelFrame(self.root, text="PNG 位置・サイズ（PDF座標 pt）", padding=(8, 4))
        prop.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0, 4))

        fields = [("X:", "_x_var", 70), ("Y:", "_y_var", 70),
                  ("幅:", "_w_var", 70), ("高さ:", "_h_var", 70)]
        for label, attr, default in fields:
            ttk.Label(prop, text=label).pack(side=tk.LEFT)
            var = tk.StringVar(value=str(default))
            setattr(self, attr, var)
            ent = ttk.Entry(prop, textvariable=var, width=7)
            ent.pack(side=tk.LEFT, padx=(0, 8))
            ent.bind("<Return>", self._on_field_change)
            ent.bind("<FocusOut>", self._on_field_change)

        ttk.Separator(prop, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self._apply_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(prop, text="全ページに適用して保存", variable=self._apply_all).pack(side=tk.LEFT)

        # ---- キャンバス ----
        cf = ttk.Frame(self.root)
        cf.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        self.canvas = tk.Canvas(cf, bg="#888", cursor="arrow")
        vsb = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self.canvas.yview)
        hsb = ttk.Scrollbar(cf, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_hover)

        # ---- ステータスバー ----
        self._status = tk.StringVar(value="PDFを開いてください")
        ttk.Label(self.root, textvariable=self._status, relief=tk.SUNKEN,
                  anchor=tk.W, padding=(4, 2)).pack(side=tk.BOTTOM, fill=tk.X)

    # ------------------------------------------------------------------
    # ファイル操作
    # ------------------------------------------------------------------

    def _open_pdf(self):
        path = filedialog.askopenfilename(
            title="PDFを選択", filetypes=[("PDF", "*.pdf"), ("すべて", "*.*")]
        )
        if not path:
            return
        self.pdf_doc = fitz.open(path)
        self.pdf_path = path
        self.current_page = 0
        self._render()
        self._status.set(f"PDF: {os.path.basename(path)}  ({len(self.pdf_doc)} ページ)")

    def _open_png(self):
        path = filedialog.askopenfilename(
            title="画像を選択",
            filetypes=[("画像", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("すべて", "*.*")]
        )
        if not path:
            return
        self._png_pil = Image.open(path).convert("RGBA")
        self.png_path = path

        # デフォルトサイズをPDF幅の1/5に
        if self.pdf_doc:
            page = self.pdf_doc[self.current_page]
            target_w = page.rect.width / 5
            ratio = target_w / self._png_pil.width
            self.png_w = target_w
            self.png_h = self._png_pil.height * ratio
        else:
            self.png_w = self._png_pil.width / 4
            self.png_h = self._png_pil.height / 4

        self._sync_fields()
        self._render()
        self._status.set(f"PNG: {os.path.basename(path)}  (元サイズ {self._png_pil.width}×{self._png_pil.height}px)")

    def _save_pdf(self):
        if not self.pdf_doc:
            messagebox.showerror("エラー", "PDFを開いてください")
            return
        if not self.png_path:
            messagebox.showerror("エラー", "PNGを開いてください")
            return

        save_path = filedialog.asksaveasfilename(
            title="保存先を選択",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile=f"overlay_{os.path.basename(self.pdf_path)}",
        )
        if not save_path:
            return

        output = fitz.open(self.pdf_path)
        pages = range(len(output)) if self._apply_all.get() else [self.current_page]
        rect = fitz.Rect(self.png_x, self.png_y,
                         self.png_x + self.png_w, self.png_y + self.png_h)

        for pn in pages:
            output[pn].insert_image(rect, filename=self.png_path)

        output.save(save_path, garbage=4, deflate=True)
        output.close()

        messagebox.showinfo("保存完了", f"保存しました:\n{save_path}")
        self._status.set(f"保存完了: {os.path.basename(save_path)}")

    # ------------------------------------------------------------------
    # ページ操作
    # ------------------------------------------------------------------

    def _prev_page(self):
        if self.pdf_doc and self.current_page > 0:
            self.current_page -= 1
            self._render()

    def _next_page(self):
        if self.pdf_doc and self.current_page < len(self.pdf_doc) - 1:
            self.current_page += 1
            self._render()

    # ------------------------------------------------------------------
    # 描画
    # ------------------------------------------------------------------

    def _render(self):
        if not self.pdf_doc:
            return

        page = self.pdf_doc[self.current_page]
        mat = fitz.Matrix(self.display_scale, self.display_scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(BytesIO(pix.tobytes("ppm")))

        cw, ch = img.width, img.height
        self.canvas.config(width=cw, height=ch)
        self.canvas.configure(scrollregion=(0, 0, cw, ch))

        self._pdf_photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._pdf_photo, tags="pdf_bg")

        if self._png_pil:
            self._draw_png_overlay()

        total = len(self.pdf_doc)
        self._page_lbl.config(text=f"  {self.current_page + 1} / {total}  ")

    def _draw_png_overlay(self):
        s = self.display_scale
        dx = int(self.png_x * s)
        dy = int(self.png_y * s)
        dw = max(1, int(self.png_w * s))
        dh = max(1, int(self.png_h * s))

        resized = self._png_pil.resize((dw, dh), Image.LANCZOS)
        self._png_photo = ImageTk.PhotoImage(resized)

        self.canvas.delete("png_layer")
        self.canvas.create_image(dx, dy, anchor=tk.NW,
                                  image=self._png_photo, tags="png_layer")
        # 枠線
        self.canvas.create_rectangle(dx, dy, dx + dw, dy + dh,
                                      outline="#e63", width=2, tags="png_layer")
        # リサイズハンドル（右下）
        hs = self.HANDLE_SIZE
        self.canvas.create_rectangle(
            dx + dw - hs, dy + dh - hs, dx + dw, dy + dh,
            fill="#e63", outline="white", tags="png_layer",
        )

    # ------------------------------------------------------------------
    # マウスイベント
    # ------------------------------------------------------------------

    def _canvas_pos(self, event):
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def _hit_handle(self, cx, cy):
        s = self.display_scale
        dx = self.png_x * s
        dy = self.png_y * s
        dw = self.png_w * s
        dh = self.png_h * s
        hs = self.HANDLE_SIZE
        return (dx + dw - hs <= cx <= dx + dw and
                dy + dh - hs <= cy <= dy + dh)

    def _hit_overlay(self, cx, cy):
        s = self.display_scale
        dx = self.png_x * s
        dy = self.png_y * s
        return (dx <= cx <= dx + self.png_w * s and
                dy <= cy <= dy + self.png_h * s)

    def _on_hover(self, event):
        if not self._png_pil:
            return
        cx, cy = self._canvas_pos(event)
        if self._hit_handle(cx, cy):
            self.canvas.config(cursor="bottom_right_corner")
        elif self._hit_overlay(cx, cy):
            self.canvas.config(cursor="fleur")
        else:
            self.canvas.config(cursor="arrow")

    def _on_press(self, event):
        if not self._png_pil:
            return
        cx, cy = self._canvas_pos(event)
        s = self.display_scale

        if self._hit_handle(cx, cy):
            self._drag_mode = "resize"
            self._drag_ox = cx
            self._drag_oy = cy
        elif self._hit_overlay(cx, cy):
            self._drag_mode = "move"
            self._drag_ox = cx - self.png_x * s
            self._drag_oy = cy - self.png_y * s

    def _on_motion(self, event):
        if not self._drag_mode:
            return
        cx, cy = self._canvas_pos(event)
        s = self.display_scale

        if self._drag_mode == "move":
            self.png_x = (cx - self._drag_ox) / s
            self.png_y = (cy - self._drag_oy) / s
        elif self._drag_mode == "resize":
            dx = (cx - self._drag_ox) / s
            dy = (cy - self._drag_oy) / s
            self.png_w = max(10.0, self.png_w + dx)
            self.png_h = max(10.0, self.png_h + dy)
            self._drag_ox = cx
            self._drag_oy = cy

        self._sync_fields()
        self._draw_png_overlay()
        self._status.set(
            f"PNG  x={self.png_x:.1f}  y={self.png_y:.1f}  "
            f"幅={self.png_w:.1f}  高さ={self.png_h:.1f}  (pt)"
        )

    def _on_release(self, event):
        self._drag_mode = None

    # ------------------------------------------------------------------
    # フィールド同期
    # ------------------------------------------------------------------

    def _sync_fields(self):
        self._x_var.set(f"{self.png_x:.1f}")
        self._y_var.set(f"{self.png_y:.1f}")
        self._w_var.set(f"{self.png_w:.1f}")
        self._h_var.set(f"{self.png_h:.1f}")

    def _on_field_change(self, _event=None):
        try:
            self.png_x = float(self._x_var.get())
            self.png_y = float(self._y_var.get())
            self.png_w = max(1.0, float(self._w_var.get()))
            self.png_h = max(1.0, float(self._h_var.get()))
        except ValueError:
            return
        if self._png_pil:
            self._draw_png_overlay()


# ------------------------------------------------------------------
# エントリーポイント
# ------------------------------------------------------------------

def main():
    root = tk.Tk()
    PDFOverlayTool(root)
    root.mainloop()


if __name__ == "__main__":
    main()

"""A window whose "buttons" are drawn on a canvas: accessibility APIs see one opaque pane,
so hosted desktop execution must fall back to OCR. Synthetic; no data leaves the window."""

import sys
import tkinter as tk

title = sys.argv[1] if len(sys.argv) > 1 else "Jev Canvas Fixture"
root = tk.Tk()
root.title(title)
root.geometry("520x360+200+200")
canvas = tk.Canvas(root, width=520, height=360, bg="white", highlightthickness=0)
canvas.pack()
canvas.create_text(260, 40, text="Arcade Menu", font=("Segoe UI", 22, "bold"))
status = canvas.create_text(260, 320, text="Status: waiting", font=("Segoe UI", 14))
BUTTONS = [("Start game", 110), ("Settings", 170), ("High scores", 230)]
for label, y in BUTTONS:
    canvas.create_rectangle(160, y - 22, 360, y + 22, fill="#dde6ff", outline="#335")
    canvas.create_text(260, y, text=label, font=("Segoe UI", 16))


def on_click(event):
    for label, y in BUTTONS:
        if 160 <= event.x <= 360 and y - 22 <= event.y <= y + 22:
            canvas.itemconfigure(status, text=f"Status: opened {label}")


canvas.bind("<Button-1>", on_click)
root.mainloop()

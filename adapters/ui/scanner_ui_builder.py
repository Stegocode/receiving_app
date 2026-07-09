"""
Owns: Tkinter panel construction for ReceivingUI — builds the left status panel
      and the right scan panel. Called once during ReceivingUI._build_ui().
Must not: import services, adapters.db, adapters.sink, adapters.source, sqlite3.
May import: tkinter, adapters.ui.scan_states, adapters.ui.blocking_states.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext
from typing import Any

from adapters.ui import blocking_states, scan_states
from adapters.ui.scan_states import (
    C_ACCENT,
    C_DIM,
    C_IDLE,
    C_INPUT_BG,
    C_LEFT,
    C_LOG_BG,
    C_WHITE,
    F_LABEL,
    F_LOG,
    F_PO_ENTRY,
    F_PO_LIST,
    F_SECONDARY,
    F_SECTION,
    F_STATE,
    F_TITLE,
)


def build_left(ui: Any, parent: Any) -> None:
    """Build the left (status/PO) panel. Sets: _po_var, _po_input, _log_widget, _po_list."""
    p = parent
    tk.Label(p, text="RECEIVING SCANNER", bg=C_LEFT, fg=C_ACCENT, font=F_TITLE, pady=8).pack(
        fill="x", padx=12, pady=(10, 0)
    )
    tk.Frame(p, bg=C_ACCENT, height=2).pack(fill="x", padx=12)
    po_wrap = tk.Frame(p, bg=C_LEFT)
    po_wrap.pack(fill="x", padx=12, pady=(10, 0))
    tk.Label(po_wrap, text="Add PO #(s)", bg=C_LEFT, fg=C_WHITE, font=F_LABEL).pack(anchor="w")
    tk.Label(
        po_wrap,
        text="comma-separated  e.g. 11782, 11783",
        bg=C_LEFT,
        fg=C_DIM,
        font=("Arial", 10),
    ).pack(anchor="w")
    row = tk.Frame(po_wrap, bg=C_LEFT)
    row.pack(fill="x")
    ui._po_var = tk.StringVar()
    ui._po_input = tk.Entry(
        row,
        textvariable=ui._po_var,
        bg=C_INPUT_BG,
        fg=C_WHITE,
        insertbackground=C_WHITE,
        font=F_PO_ENTRY,
        relief="flat",
        bd=4,
    )
    ui._po_input.pack(side="left", fill="x", expand=True)
    ui._po_input.bind("<Return>", ui._on_po_submit)
    tk.Button(
        row,
        text="Go",
        command=ui._on_po_submit,
        bg=C_ACCENT,
        fg=C_WHITE,
        font=F_LABEL,
        relief="flat",
        padx=10,
        cursor="hand2",
    ).pack(side="left", padx=(4, 0))
    tk.Frame(p, bg="#4A6278", height=1).pack(fill="x", padx=12, pady=8)
    tk.Label(p, text="STATUS LOG", bg=C_LEFT, fg=C_DIM, font=F_SECTION).pack(fill="x", padx=12)
    ui._log_widget = scrolledtext.ScrolledText(
        p,
        state="disabled",
        wrap="word",
        bg=C_LOG_BG,
        fg=C_WHITE,
        font=F_LOG,
        relief="flat",
        bd=0,
    )
    ui._log_widget.pack(fill="both", expand=True, padx=12, pady=(2, 4))
    tk.Frame(p, bg="#4A6278", height=1).pack(fill="x", padx=12, pady=(0, 4))
    tk.Label(p, text="TODAY'S POs", bg=C_LEFT, fg=C_DIM, font=F_SECTION).pack(fill="x", padx=12)
    ui._po_list = tk.Text(
        p,
        state="disabled",
        wrap="none",
        bg=C_LOG_BG,
        fg=C_DIM,
        font=F_PO_LIST,
        relief="flat",
        bd=0,
        height=5,
    )
    ui._po_list.pack(fill="x", padx=12, pady=(2, 10))


def build_right(ui: Any, parent: Any) -> None:
    """Build the right (scan) panel. Sets: _center, _state_lbl, _sec_lbl, _reset_btn."""
    p = parent
    ui._center = tk.Frame(p, bg=C_IDLE)
    ui._center.place(relx=0.5, rely=0.40, anchor="center")
    ui._state_lbl = tk.Label(
        ui._center,
        text="ADD PO TO BEGIN",
        font=F_STATE,
        bg=C_IDLE,
        fg=C_WHITE,
        wraplength=700,
        justify="center",
    )
    ui._state_lbl.pack()
    ui._sec_lbl = tk.Label(
        ui._center,
        text="Enter PO number(s) on the left",
        font=F_SECONDARY,
        bg=C_IDLE,
        fg=C_DIM,
        wraplength=700,
        justify="center",
    )
    ui._sec_lbl.pack(pady=(14, 0))
    ui._reset_btn = tk.Button(
        p,
        text="Reset",
        command=ui._set_idle,
        bg="#922B21",
        fg=C_WHITE,
        font=("Arial", 14),
        relief="flat",
        padx=18,
        pady=10,
        cursor="hand2",
    )
    scan_states.build_manual_frame(ui, p)
    blocking_states.build_needs_model_frame(ui, p)

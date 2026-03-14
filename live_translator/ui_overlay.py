import tkinter as tk
import webbrowser
from typing import Callable


CHANNEL_URL = "https://www.youtube.com/@criando_com_ia_of"
ACCENT_COLORS = ("#4f6586", "#6ea8ff", "#90d4ff", "#6ea8ff")
TRANSLATING_FRAMES = (
    "Captando áudio ao vivo...",
    "Transcrevendo em tempo real...",
    "Traduzindo para português...",
    "Gerando voz com fluidez...",
)


class OverlayUI:
    def __init__(
        self,
        root: tk.Tk,
        on_play: Callable[[], None],
        on_stop: Callable[[], None],
        on_config: Callable[[], None],
        on_close: Callable[[], None],
    ) -> None:
        self.root = root
        self.on_play = on_play
        self.on_stop = on_stop
        self.on_config = on_config
        self.on_close = on_close

        self.status_var = tk.StringVar(value="Tudo pronto. Pressione PLAY para começar.")
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self.play_button: tk.Button | None = None
        self.stop_button: tk.Button | None = None
        self.config_button: tk.Button | None = None
        self.credit_orb_label: tk.Label | None = None
        self.credit_name_label: tk.Label | None = None
        self._credit_color_index = 0
        self._credit_anim_job: str | None = None
        self._status_anim_job: str | None = None
        self._status_anim_index = 0

        self._build()

    def _build(self) -> None:
        self.root.title("LiveTradutor")
        self.root.geometry("330x165+40+40")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#202225")
        self.root.bind("<Map>", self._on_map)

        container = tk.Frame(self.root, bg="#202225", bd=1, relief="solid")
        container.pack(fill="both", expand=True)

        top_bar = tk.Frame(container, bg="#202225")
        top_bar.pack(fill="x", padx=6, pady=(4, 0))

        title = tk.Label(
            top_bar,
            text="LiveTradutor",
            fg="#f0f0f0",
            bg="#202225",
            font=("Segoe UI", 10, "bold"),
        )
        title.pack(side="left")

        control_box = tk.Frame(top_bar, bg="#202225")
        control_box.pack(side="right")

        minimize_btn = tk.Button(
            control_box,
            text="_",
            width=2,
            command=self._minimize_window,
            bg="#2e3442",
            fg="#d8d8d8",
            relief="flat",
            activebackground="#3a4151",
        )
        minimize_btn.pack(side="left", padx=(0, 4))

        close_btn = tk.Button(
            control_box,
            text="X",
            width=2,
            command=self.on_close,
            bg="#6d2f2f",
            fg="#ffffff",
            relief="flat",
            activebackground="#8d3f3f",
        )
        close_btn.pack(side="left")

        button_row = tk.Frame(container, bg="#202225")
        button_row.pack(pady=(8, 4))

        self.play_button = tk.Button(
            button_row,
            text="PLAY",
            width=7,
            command=self.on_play,
            bg="#2f8f2f",
            fg="#ffffff",
            relief="flat",
            activebackground="#3fa53f",
        )
        self.play_button.pack(side="left", padx=4)

        self.stop_button = tk.Button(
            button_row,
            text="STOP",
            width=7,
            command=self.on_stop,
            bg="#aa3131",
            fg="#ffffff",
            relief="flat",
            activebackground="#c63a3a",
        )
        self.stop_button.pack(side="left", padx=4)

        self.config_button = tk.Button(
            button_row,
            text="CONFIG",
            width=7,
            command=self.on_config,
            bg="#3f4f73",
            fg="#ffffff",
            relief="flat",
            activebackground="#556799",
        )
        self.config_button.pack(side="left", padx=4)

        status_label = tk.Label(
            container,
            textvariable=self.status_var,
            fg="#e0e0e0",
            bg="#202225",
            font=("Segoe UI", 9),
        )
        status_label.pack(pady=(6, 8))

        credit_row = tk.Frame(container, bg="#202225")
        credit_row.pack(pady=(0, 6))

        self.credit_orb_label = tk.Label(
            credit_row,
            text="•",
            fg=ACCENT_COLORS[0],
            bg="#202225",
            font=("Segoe UI", 9, "bold"),
        )
        self.credit_orb_label.pack(side="left", padx=(0, 5))

        credit_prefix = tk.Label(
            credit_row,
            text="Criado por ",
            fg="#c5cad3",
            bg="#202225",
            font=("Segoe UI", 8),
        )
        credit_prefix.pack(side="left")

        self.credit_name_label = tk.Label(
            credit_row,
            text="CriandoComIA",
            fg="#8ecbff",
            bg="#202225",
            cursor="hand2",
            font=("Bahnschrift SemiBold", 9, "bold"),
        )
        self.credit_name_label.pack(side="left")
        self.credit_name_label.bind("<Button-1>", lambda _event: webbrowser.open_new_tab(CHANNEL_URL))

        for widget in (self.root, container, top_bar, title):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._on_drag)

        self._apply_running_state(False)
        self._start_credit_animation()
        self.set_status("Idle")

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_offset_x = event.x_root - self.root.winfo_x()
        self._drag_offset_y = event.y_root - self.root.winfo_y()

    def _on_drag(self, event: tk.Event) -> None:
        x = event.x_root - self._drag_offset_x
        y = event.y_root - self._drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def _minimize_window(self) -> None:
        self.root.overrideredirect(False)
        self.root.iconify()

    def _on_map(self, _event: tk.Event) -> None:
        self.root.after(10, self._restore_borderless)

    def _restore_borderless(self) -> None:
        if self.root.state() == "normal":
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)

    def set_status(self, status: str) -> None:
        probe = status.strip().lower()
        if probe.startswith("error"):
            self._stop_status_animation()
            self.status_var.set("Não foi possível traduzir agora.")
            self._apply_running_state(False)
            return

        if "running" in probe or "traduzindo" in probe:
            self._apply_running_state(True)
            self._start_status_animation()
            return

        if "configuração salva" in probe or "configuracao salva" in probe:
            self._apply_running_state(False)
            self._stop_status_animation()
            self.status_var.set("Configuração salva com sucesso.")
            return

        if "stopped" in probe:
            self._apply_running_state(False)
            self._stop_status_animation()
            self.status_var.set("Tradução pausada. Pressione PLAY para retomar.")
            return

        self._stop_status_animation()
        self._apply_running_state(False)
        self.status_var.set("Tudo pronto. Pressione PLAY para começar.")

    def _apply_running_state(self, is_running: bool) -> None:
        if self.play_button is not None:
            self.play_button.configure(state="disabled" if is_running else "normal")
        if self.stop_button is not None:
            self.stop_button.configure(state="normal" if is_running else "disabled")
        if self.config_button is not None:
            self.config_button.configure(state="normal")

    def _start_credit_animation(self) -> None:
        if self.credit_orb_label is None:
            return
        self._animate_credit()

    def _animate_credit(self) -> None:
        if self.credit_orb_label is None:
            return
        self._credit_color_index = (self._credit_color_index + 1) % len(ACCENT_COLORS)
        self.credit_orb_label.configure(fg=ACCENT_COLORS[self._credit_color_index])
        self._credit_anim_job = self.root.after(650, self._animate_credit)

    def _start_status_animation(self) -> None:
        if self._status_anim_job is not None:
            return
        self._status_anim_index = 0
        self._animate_status()

    def _animate_status(self) -> None:
        self.status_var.set(TRANSLATING_FRAMES[self._status_anim_index % len(TRANSLATING_FRAMES)])
        self._status_anim_index += 1
        self._status_anim_job = self.root.after(540, self._animate_status)

    def _stop_status_animation(self) -> None:
        if self._status_anim_job is not None:
            self.root.after_cancel(self._status_anim_job)
            self._status_anim_job = None

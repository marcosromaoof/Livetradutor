import tkinter as tk
import time
from tkinter import messagebox, ttk

from live_translator.flow_logger import flow_log, get_log_path, setup_flow_logger
from live_translator.pipeline import LiveTranslatorPipeline
from live_translator.runtime_settings import (
    RuntimeSettings,
    clear_runtime_api_keys,
    load_runtime_settings,
    save_runtime_settings,
)
from live_translator.translator import (
    build_translator,
    detect_provider_from_key,
    fetch_deepseek_models,
    fetch_gemini_models,
    fetch_groq_models,
)
from live_translator.trace_logs import get_ai_log_path, get_stt_log_path, setup_trace_loggers
from live_translator.ui_overlay import OverlayUI


def main() -> None:
    setup_flow_logger()
    setup_trace_loggers()
    flow_log("app", "startup", log_file=get_log_path())
    flow_log("app", "trace_logs", stt_log=get_stt_log_path(), ai_log=get_ai_log_path())
    print(f"Flow log: {get_log_path()}")
    print(f"STT trace log: {get_stt_log_path()}")
    print(f"AI trace log: {get_ai_log_path()}")
    root = tk.Tk()

    ui_ref: dict[str, OverlayUI] = {}
    settings_ref: dict[str, RuntimeSettings] = {"settings": load_runtime_settings()}

    def set_status(status: str) -> None:
        def update() -> None:
            if "ui" in ui_ref:
                ui_ref["ui"].set_status(status)

        root.after(0, update)

    def set_error(message: str) -> None:
        flow_log("app", "error", message=message)
        print(message)
        probe = message.strip().lower()
        fatal_markers = (
            "deepgram connection failure",
            "deepgram api key missing",
            "audio capture failed",
            "piper process failure",
            "audio playback failure",
            "all translation providers failed",
        )
        if any(marker in probe for marker in fatal_markers):
            set_status("Error")

    pipeline = LiveTranslatorPipeline(
        runtime_settings=settings_ref["settings"],
        on_status=set_status,
        on_error=set_error,
    )

    def on_play() -> None:
        flow_log("app", "play_clicked")
        pipeline.start()

    def on_stop() -> None:
        flow_log("app", "stop_clicked")
        pipeline.stop()

    def shutdown(_event=None) -> None:
        flow_log("app", "shutdown")
        pipeline.stop()
        root.destroy()

    def on_config() -> None:
        settings = settings_ref["settings"]

        window = tk.Toplevel(root)
        window.title("Configuração do LiveTradutor")
        window.geometry("760x580")
        window.resizable(False, False)
        window.attributes("-topmost", True)
        window.configure(bg="#181a20")

        provider_options = {
            "Gemini": "gemini",
            "Groq": "groq",
            "DeepSeek": "deepseek",
        }
        provider_labels = {code: label for label, code in provider_options.items()}

        provider_display_var = tk.StringVar(
            value=provider_labels.get(settings.normalized_provider(), "Gemini")
        )
        fallback_var = tk.BooleanVar(value=settings.fallback_enabled)
        deepgram_key_var = tk.StringVar(value=settings.deepgram_api_key)
        groq_key_var = tk.StringVar(value=settings.groq_api_key)
        groq_model_var = tk.StringVar(value=settings.groq_model)
        gemini_key_var = tk.StringVar(value=settings.gemini_api_key)
        gemini_model_var = tk.StringVar(value=settings.gemini_model)
        deepseek_key_var = tk.StringVar(value=settings.deepseek_api_key)
        deepseek_model_var = tk.StringVar(value=settings.deepseek_model)
        info_var = tk.StringVar(value="")

        container = tk.Frame(window, bg="#181a20")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        title_row = tk.Frame(container, bg="#181a20")
        title_row.pack(fill="x", pady=(0, 8))

        tk.Label(
            title_row,
            text="Configuração de Provedores e Modelos",
            bg="#181a20",
            fg="#f2f6ff",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).pack(side="left")

        top_row = tk.Frame(container, bg="#181a20")
        top_row.pack(fill="x", pady=(0, 10))
        top_row.columnconfigure(1, weight=1)

        tk.Label(
            top_row,
            text="Provedor principal",
            bg="#181a20",
            fg="#d7e1f5",
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        ttk.Combobox(
            top_row,
            textvariable=provider_display_var,
            values=list(provider_options.keys()),
            state="readonly",
            width=22,
        ).grid(row=0, column=1, sticky="w")

        tk.Checkbutton(
            top_row,
            text="Fallback automático se o principal falhar",
            variable=fallback_var,
            onvalue=True,
            offvalue=False,
            bg="#181a20",
            fg="#d7e1f5",
            activebackground="#181a20",
            activeforeground="#d7e1f5",
            selectcolor="#181a20",
        ).grid(row=0, column=2, sticky="e", padx=(12, 0))

        deepgram_row = tk.Frame(container, bg="#181a20")
        deepgram_row.pack(fill="x", pady=(0, 10))
        deepgram_row.columnconfigure(1, weight=1)

        tk.Label(
            deepgram_row,
            text="Deepgram API Key",
            bg="#181a20",
            fg="#d7e1f5",
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        tk.Entry(
            deepgram_row,
            textvariable=deepgram_key_var,
            show="*",
        ).grid(row=0, column=1, sticky="ew")

        providers_row = tk.Frame(container, bg="#181a20")
        providers_row.pack(fill="both", expand=True)
        providers_row.columnconfigure(0, weight=1)
        providers_row.columnconfigure(1, weight=1)

        def _section_frame(parent: tk.Frame, title: str, accent: str) -> tk.Frame:
            section = tk.Frame(
                parent,
                bg="#202430",
                highlightthickness=1,
                highlightbackground=accent,
                bd=0,
            )
            tk.Label(
                section,
                text=title,
                bg="#202430",
                fg=accent,
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            ).pack(fill="x", padx=10, pady=(8, 6))
            return section

        gemini_section = _section_frame(providers_row, "Gemini", "#86b8ff")
        gemini_section.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 8))

        tk.Label(gemini_section, text="Chave da API", bg="#202430", fg="#d7e1f5", anchor="w").pack(
            fill="x", padx=10
        )
        tk.Entry(gemini_section, textvariable=gemini_key_var, show="*").pack(fill="x", padx=10, pady=(2, 8))
        tk.Label(gemini_section, text="Modelo", bg="#202430", fg="#d7e1f5", anchor="w").pack(fill="x", padx=10)
        gemini_model_row = tk.Frame(gemini_section, bg="#202430")
        gemini_model_row.pack(fill="x", padx=10, pady=(2, 10))
        gemini_model_row.columnconfigure(0, weight=1)
        gemini_model_box = ttk.Combobox(gemini_model_row, textvariable=gemini_model_var)
        gemini_model_box.grid(row=0, column=0, sticky="ew")
        tk.Button(
            gemini_model_row,
            text="Buscar modelos",
            width=14,
            command=lambda: fetch_models("gemini"),
            bg="#3f4f73",
            fg="#ffffff",
            relief="flat",
        ).grid(row=0, column=1, padx=(8, 0))

        groq_section = _section_frame(providers_row, "Groq", "#9dd59d")
        groq_section.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 8))

        tk.Label(groq_section, text="Chave da API", bg="#202430", fg="#d7e1f5", anchor="w").pack(fill="x", padx=10)
        tk.Entry(groq_section, textvariable=groq_key_var, show="*").pack(fill="x", padx=10, pady=(2, 8))
        tk.Label(groq_section, text="Modelo", bg="#202430", fg="#d7e1f5", anchor="w").pack(fill="x", padx=10)
        groq_model_row = tk.Frame(groq_section, bg="#202430")
        groq_model_row.pack(fill="x", padx=10, pady=(2, 10))
        groq_model_row.columnconfigure(0, weight=1)
        groq_model_box = ttk.Combobox(groq_model_row, textvariable=groq_model_var)
        groq_model_box.grid(row=0, column=0, sticky="ew")
        tk.Button(
            groq_model_row,
            text="Buscar modelos",
            width=14,
            command=lambda: fetch_models("groq"),
            bg="#3f4f73",
            fg="#ffffff",
            relief="flat",
        ).grid(row=0, column=1, padx=(8, 0))

        deepseek_section = _section_frame(providers_row, "DeepSeek", "#f3b176")
        deepseek_section.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 8))

        tk.Label(deepseek_section, text="Chave da API", bg="#202430", fg="#d7e1f5", anchor="w").pack(
            fill="x", padx=10
        )
        tk.Entry(deepseek_section, textvariable=deepseek_key_var, show="*").pack(fill="x", padx=10, pady=(2, 8))
        tk.Label(deepseek_section, text="Modelo", bg="#202430", fg="#d7e1f5", anchor="w").pack(fill="x", padx=10)
        deepseek_model_row = tk.Frame(deepseek_section, bg="#202430")
        deepseek_model_row.pack(fill="x", padx=10, pady=(2, 10))
        deepseek_model_row.columnconfigure(0, weight=1)
        deepseek_model_box = ttk.Combobox(deepseek_model_row, textvariable=deepseek_model_var)
        deepseek_model_box.grid(row=0, column=0, sticky="ew")
        tk.Button(
            deepseek_model_row,
            text="Buscar modelos",
            width=14,
            command=lambda: fetch_models("deepseek"),
            bg="#3f4f73",
            fg="#ffffff",
            relief="flat",
        ).grid(row=0, column=1, padx=(8, 0))

        tk.Label(
            container,
            textvariable=info_var,
            bg="#181a20",
            fg="#b8d5ff",
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(2, 8))

        button_row = tk.Frame(container, bg="#181a20")
        button_row.pack(fill="x")

        def _provider_label(provider: str) -> str:
            return provider_labels.get(provider, provider)

        def _selected_provider_code() -> str:
            label = provider_display_var.get().strip()
            return provider_options.get(label, "gemini")

        def _get_key(provider: str) -> str:
            if provider == "gemini":
                return gemini_key_var.get().strip()
            if provider == "groq":
                return groq_key_var.get().strip()
            return deepseek_key_var.get().strip()

        def _set_key(provider: str, value: str) -> None:
            if provider == "gemini":
                gemini_key_var.set(value)
            elif provider == "groq":
                groq_key_var.set(value)
            else:
                deepseek_key_var.set(value)

        def _validate_key(provider: str, token: str) -> str | None:
            probe = token.strip()
            if not probe:
                return f"Chave {_provider_label(provider)} vazia."
            detected = detect_provider_from_key(probe)
            if detected is None:
                return "Formato de chave nao reconhecido para os provedores suportados."
            if detected != provider:
                return (
                    f"Essa chave parece ser {_provider_label(detected)}, "
                    f"nao {_provider_label(provider)}."
                )
            return None

        def _auto_route_key(provider: str) -> tuple[str, str]:
            token = _get_key(provider)
            if not token:
                return provider, ""

            detected = detect_provider_from_key(token)
            if detected is None or detected == provider:
                return provider, token

            destination_key = _get_key(detected)
            if not destination_key:
                _set_key(detected, token)
                _set_key(provider, "")
                info_var.set(
                    f"Chave movida automaticamente para {_provider_label(detected)}."
                )
                return detected, token
            return provider, token

        def _auto_route_all_keys() -> None:
            for provider in ("gemini", "groq", "deepseek"):
                _auto_route_key(provider)

        def _apply_models(provider: str, models: list[str]) -> None:
            if provider == "gemini":
                gemini_model_box["values"] = models
                if models and (not gemini_model_var.get().strip() or gemini_model_var.get().strip() not in models):
                    gemini_model_var.set(models[0])
                return
            if provider == "groq":
                groq_model_box["values"] = models
                if models and (not groq_model_var.get().strip() or groq_model_var.get().strip() not in models):
                    groq_model_var.set(models[0])
                return
            deepseek_model_box["values"] = models
            if models and (not deepseek_model_var.get().strip() or deepseek_model_var.get().strip() not in models):
                deepseek_model_var.set(models[0])

        def fetch_models(provider: str) -> bool:
            try:
                provider, token = _auto_route_key(provider)
                issue = _validate_key(provider, token)
                if issue:
                    info_var.set(issue)
                    return False

                fetchers = {
                    "gemini": fetch_gemini_models,
                    "groq": fetch_groq_models,
                    "deepseek": fetch_deepseek_models,
                }
                models = fetchers[provider](token)
                _apply_models(provider, models)
                info_var.set(f"Carregados {len(models)} modelos do {_provider_label(provider)}.")
                return True
            except Exception as exc:
                info_var.set(f"Falha ao buscar modelos: {exc}")
                return False

        def _build_candidate_settings(primary_provider: str, enable_fallback: bool) -> RuntimeSettings:
            return RuntimeSettings(
                provider=primary_provider.strip().lower() or "gemini",
                fallback_enabled=bool(enable_fallback),
                deepgram_api_key=deepgram_key_var.get().strip(),
                groq_api_key=groq_key_var.get().strip(),
                groq_model=groq_model_var.get().strip() or "llama-3.1-8b-instant",
                gemini_api_key=gemini_key_var.get().strip(),
                gemini_model=gemini_model_var.get().strip() or "gemini-2.0-flash",
                deepseek_api_key=deepseek_key_var.get().strip(),
                deepseek_model=deepseek_model_var.get().strip() or "deepseek-chat",
            )

        def _clear_key_vars() -> None:
            deepgram_key_var.set("")
            groq_key_var.set("")
            gemini_key_var.set("")
            deepseek_key_var.set("")

        def test_primary() -> None:
            original_provider = _selected_provider_code()
            selected_provider, _ = _auto_route_key(original_provider)
            if selected_provider != original_provider:
                provider_display_var.set(_provider_label(selected_provider))
            issue = _validate_key(selected_provider, _get_key(selected_provider))
            if issue:
                info_var.set(issue)
                return
            candidate_settings = _build_candidate_settings(selected_provider, enable_fallback=False)
            errors: list[str] = []
            translator = build_translator(candidate_settings, on_error=errors.append)
            sample_text = "This is a real-time translator connectivity test."

            started_at = time.perf_counter()
            translated = translator.translate(sample_text)
            elapsed = time.perf_counter() - started_at

            if translated:
                info_var.set(
                    f"Teste {_provider_label(selected_provider)}: OK em {elapsed:.2f}s | "
                    f"{translated[:72]}"
                )
                return

            if errors:
                info_var.set(
                    f"Teste {_provider_label(selected_provider)}: falhou em {elapsed:.2f}s | {errors[-1]}"
                )
            else:
                info_var.set(
                    f"Teste {_provider_label(selected_provider)}: sem resposta em {elapsed:.2f}s."
                )

        def test_all_without_fallback() -> None:
            results: list[str] = []
            for provider in ("gemini", "groq", "deepseek"):
                provider, _ = _auto_route_key(provider)
                issue = _validate_key(provider, _get_key(provider))
                if issue:
                    results.append(f"{_provider_label(provider)}: chave inválida")
                    continue
                candidate_settings = _build_candidate_settings(provider, enable_fallback=False)
                errors: list[str] = []
                translator = build_translator(candidate_settings, on_error=errors.append)
                started_at = time.perf_counter()
                translated = translator.translate("Please translate this sentence to Portuguese.")
                elapsed = time.perf_counter() - started_at
                if translated:
                    results.append(f"{_provider_label(provider)}: ok {elapsed:.2f}s")
                else:
                    err = errors[-1] if errors else "sem retorno"
                    results.append(f"{_provider_label(provider)}: falha {elapsed:.2f}s ({err})")
            info_var.set(" | ".join(results))

        def fetch_all() -> None:
            _auto_route_all_keys()
            messages: list[str] = []
            for provider in ("gemini", "groq", "deepseek"):
                ok = fetch_models(provider)
                messages.append(f"{_provider_label(provider)}: {'ok' if ok else 'falha'}")
            info_var.set(" | ".join(messages))

        def auto_fetch_on_open() -> None:
            _auto_route_all_keys()
            messages: list[str] = []
            attempts = [
                ("gemini", bool(gemini_key_var.get().strip())),
                ("groq", bool(groq_key_var.get().strip())),
                ("deepseek", bool(deepseek_key_var.get().strip())),
            ]
            for provider, can_fetch in attempts:
                if not can_fetch:
                    messages.append(f"{_provider_label(provider)}: sem chave")
                    continue
                ok = fetch_models(provider)
                messages.append(f"{_provider_label(provider)}: {'ok' if ok else 'falha'}")
            info_var.set(" | ".join(messages))

        def save_and_apply() -> None:
            _auto_route_all_keys()
            new_settings = _build_candidate_settings(
                _selected_provider_code(),
                enable_fallback=fallback_var.get(),
            )
            save_runtime_settings(new_settings)
            settings_ref["settings"] = new_settings
            pipeline.update_runtime_settings(new_settings)
            set_status("Configuracao salva")
            window.destroy()

        def clear_keys_securely() -> None:
            confirmed = messagebox.askyesno(
                "Limpar chaves",
                "Deseja apagar TODAS as chaves de API deste computador?",
                parent=window,
            )
            if not confirmed:
                return

            try:
                clear_runtime_api_keys()
                _clear_key_vars()
                cleaned_settings = _build_candidate_settings(
                    _selected_provider_code(),
                    enable_fallback=fallback_var.get(),
                )
                save_runtime_settings(cleaned_settings)
                settings_ref["settings"] = cleaned_settings
                pipeline.update_runtime_settings(cleaned_settings)
                info_var.set("Chaves apagadas com sucesso (cofre seguro limpo).")
                set_status("Configuracao salva")
            except Exception as exc:
                info_var.set(f"Falha ao limpar chaves: {exc}")

        tk.Button(
            button_row,
            text="Buscar Todos",
            width=12,
            command=fetch_all,
            bg="#3f4f73",
            fg="#ffffff",
            relief="flat",
        ).pack(side="left", padx=4)

        tk.Button(
            button_row,
            text="Testar Principal",
            width=12,
            command=test_primary,
            bg="#266c8c",
            fg="#ffffff",
            relief="flat",
        ).pack(side="left", padx=4)

        tk.Button(
            button_row,
            text="Testar Todos",
            width=10,
            command=test_all_without_fallback,
            bg="#2b5f83",
            fg="#ffffff",
            relief="flat",
        ).pack(side="left", padx=4)

        tk.Button(
            button_row,
            text="Limpar Chaves",
            width=10,
            command=clear_keys_securely,
            bg="#7a4a24",
            fg="#ffffff",
            relief="flat",
        ).pack(side="left", padx=4)

        tk.Button(
            button_row,
            text="Salvar",
            width=10,
            command=save_and_apply,
            bg="#2f8f2f",
            fg="#ffffff",
            relief="flat",
            activebackground="#3fa53f",
        ).pack(side="left", padx=4)

        tk.Button(
            button_row,
            text="Cancelar",
            width=10,
            command=window.destroy,
            bg="#5a5a5a",
            fg="#ffffff",
            relief="flat",
        ).pack(side="left", padx=4)

        info_var.set(
            "Chaves em cofre criptografado local (Deepgram + provedores de traducao)."
        )
        window.after(200, auto_fetch_on_open)

    ui = OverlayUI(
        root,
        on_play=on_play,
        on_stop=on_stop,
        on_config=on_config,
        on_close=shutdown,
    )
    ui_ref["ui"] = ui
    ui.set_status("Idle")

    root.bind("<Escape>", shutdown)
    root.bind("<Button-3>", shutdown)
    root.protocol("WM_DELETE_WINDOW", shutdown)

    root.mainloop()


if __name__ == "__main__":
    main()

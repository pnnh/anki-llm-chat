"""Settings dialog for Card Assistant."""

from aqt import mw
from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QThread,
    QVBoxLayout,
    pyqtSignal,
)

from .api_client import fetch_models, test_connection


class _BgWorker(QThread):
    """Run a callable in the background and deliver the result."""
    done = pyqtSignal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        result = self._fn()
        if not self._cancelled:
            self.done.emit(result)

MODULE = __name__.split(".")[0]


class ConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Card Assistant \u2014 Settings")
        self.setMinimumWidth(500)
        self._bg: _BgWorker | None = None
        self._build_ui()
        self._load()

    def done(self, result):
        """Cancel any background thread before closing the dialog."""
        if self._bg is not None:
            self._bg.cancel()
            try:
                self._bg.done.disconnect()
            except (TypeError, RuntimeError):
                pass
            # Thread will finish on its own; prevent parent-destroy crash
            self._bg.setParent(None)
            self._bg = None
        super().done(result)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Provider selector
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["OpenRouter", "Ollama", "Gemini"])
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Provider:", self.provider_combo)

        # API Key (OpenRouter only)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-or-...")
        self._api_key_label = QLabel("API Key:")
        form.addRow(self._api_key_label, self.api_key_edit)

        # Ollama URL (Ollama only)
        self.ollama_url_edit = QLineEdit()
        self.ollama_url_edit.setPlaceholderText("http://localhost:11434")
        self._ollama_url_label = QLabel("Ollama URL:")
        form.addRow(self._ollama_url_label, self.ollama_url_edit)

        # Gemini API Key (Gemini only)
        self.gemini_key_edit = QLineEdit()
        self.gemini_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key_edit.setPlaceholderText("AIza...")
        self._gemini_key_label = QLabel("Gemini API Key:")
        form.addRow(self._gemini_key_label, self.gemini_key_edit)

        # Model row
        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setMinimumWidth(300)
        model_row.addWidget(self.model_combo)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_models)
        model_row.addWidget(self.refresh_btn)
        form.addRow("Model:", model_row)

        # Test Connection row
        test_row = QHBoxLayout()
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._test_connection)
        test_row.addWidget(self.test_btn)
        self.test_status = QLabel("")
        self.test_status.setWordWrap(True)
        test_row.addWidget(self.test_status, stretch=1)
        form.addRow("", test_row)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setMaximumHeight(120)
        self.prompt_edit.setStyleSheet("font-family: monospace;")
        form.addRow("System Prompt:", self.prompt_edit)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(64, 16384)
        self.max_tokens_spin.setSingleStep(128)
        form.addRow("Max Tokens:", self.max_tokens_spin)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(2)
        form.addRow("Temperature:", self.temp_spin)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 24)
        form.addRow("Font Size:", self.font_size_spin)

        self.panel_width_spin = QSpinBox()
        self.panel_width_spin.setRange(200, 1000)
        self.panel_width_spin.setSingleStep(50)
        form.addRow("Panel Width:", self.panel_width_spin)

        layout.addLayout(form)

        # Word Preview section
        preview_group = QGroupBox("Word Preview")
        preview_form = QFormLayout(preview_group)
        self.preview_enabled_check = QCheckBox("Enable preview pane")
        preview_form.addRow("", self.preview_enabled_check)
        self.preview_url_edit = QLineEdit()
        self.preview_url_edit.setPlaceholderText("http://example.com/search?word={word}")
        preview_form.addRow("URL Template:", self.preview_url_edit)
        self.preview_field_edit = QLineEdit()
        self.preview_field_edit.setPlaceholderText("Front")
        preview_form.addRow("Field Name:", self.preview_field_edit)
        layout.addWidget(preview_group)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _on_provider_changed(self):
        selected = self.provider_combo.currentText()

        # Save current combo text to the outgoing provider before switching
        current_model = self.model_combo.currentText().strip()
        if hasattr(self, "_active_provider"):
            if self._active_provider == "openrouter":
                self._openrouter_model = current_model
            elif self._active_provider == "ollama":
                self._ollama_model = current_model
            elif self._active_provider == "gemini":
                self._gemini_model = current_model

        # Update active provider and load its saved model
        provider_map = {"OpenRouter": "openrouter", "Ollama": "ollama", "Gemini": "gemini"}
        self._active_provider = provider_map.get(selected, "openrouter")
        model_map = {
            "openrouter": self._openrouter_model,
            "ollama": self._ollama_model,
            "gemini": self._gemini_model,
        }
        incoming = model_map.get(self._active_provider, "")
        self.model_combo.clear()
        if incoming:
            self.model_combo.addItem(incoming)
        self.model_combo.setCurrentText(incoming)

        is_openrouter = selected == "OpenRouter"
        is_ollama = selected == "Ollama"
        is_gemini = selected == "Gemini"

        self.api_key_edit.setVisible(is_openrouter)
        self._api_key_label.setVisible(is_openrouter)
        self.ollama_url_edit.setVisible(is_ollama)
        self._ollama_url_label.setVisible(is_ollama)
        self.gemini_key_edit.setVisible(is_gemini)
        self._gemini_key_label.setVisible(is_gemini)
        self.test_status.setText("")

    def _load(self):
        conf = mw.addonManager.getConfig(MODULE) or {}

        # Load per-provider models (fall back to legacy "model" key)
        legacy = conf.get("model", "")
        self._openrouter_model = conf.get("openrouter_model", legacy or "deepseek/deepseek-v3.2")
        self._ollama_model = conf.get("ollama_model", "")
        self._gemini_model = conf.get("gemini_model", "gemini-2.5-flash")

        provider = conf.get("provider", "openrouter")
        self._active_provider = provider

        # Populate combo with the active provider's model
        model_map = {
            "openrouter": self._openrouter_model,
            "ollama": self._ollama_model,
            "gemini": self._gemini_model,
        }
        active_model = model_map.get(provider, self._openrouter_model)
        self.model_combo.clear()
        if active_model:
            self.model_combo.addItem(active_model)
        self.model_combo.setCurrentText(active_model)

        provider_labels = {"ollama": "Ollama", "gemini": "Gemini"}
        self.provider_combo.setCurrentText(
            provider_labels.get(provider, "OpenRouter")
        )

        self.api_key_edit.setText(conf.get("api_key", ""))
        self.ollama_url_edit.setText(
            conf.get("ollama_url", "http://localhost:11434")
        )
        self.gemini_key_edit.setText(conf.get("gemini_api_key", ""))

        self.prompt_edit.setPlainText(conf.get("system_prompt", ""))
        self.max_tokens_spin.setValue(conf.get("max_tokens", 1024))
        self.temp_spin.setValue(conf.get("temperature", 0.7))
        self.font_size_spin.setValue(conf.get("font_size", 12))
        self.panel_width_spin.setValue(conf.get("panel_width", 400))

        self.preview_enabled_check.setChecked(conf.get("preview_enabled", False))
        self.preview_url_edit.setText(conf.get("preview_url", ""))
        self.preview_field_edit.setText(conf.get("preview_field", "Front"))

        # Set initial visibility
        self._on_provider_changed()

    def _current_provider(self):
        text = self.provider_combo.currentText()
        return {"Ollama": "ollama", "Gemini": "gemini"}.get(text, "openrouter")

    def _refresh_models(self):
        provider = self._current_provider()
        api_key = self.api_key_edit.text().strip()
        ollama_url = self.ollama_url_edit.text().strip() or "http://localhost:11434"
        gemini_key = self.gemini_key_edit.text().strip()

        if provider == "openrouter" and not api_key:
            return
        if provider == "gemini" and not gemini_key:
            return

        self.refresh_btn.setText("Loading...")
        self.refresh_btn.setEnabled(False)

        current = self.model_combo.currentText()

        def _fetch():
            return fetch_models(api_key, provider=provider, ollama_url=ollama_url,
                                gemini_api_key=gemini_key)

        def _on_done(models):
            self.model_combo.clear()
            if models:
                self.model_combo.addItems(models)
            if current:
                self.model_combo.setCurrentText(current)
            self.refresh_btn.setText("Refresh")
            self.refresh_btn.setEnabled(True)
            self._bg = None

        self._bg = _BgWorker(_fetch, self)
        self._bg.done.connect(_on_done)
        self._bg.start()

    def _test_connection(self):
        provider = self._current_provider()
        api_key = self.api_key_edit.text().strip()
        ollama_url = self.ollama_url_edit.text().strip() or "http://localhost:11434"
        gemini_key = self.gemini_key_edit.text().strip()

        self.test_btn.setEnabled(False)
        self.test_status.setText("Testing...")
        self.test_status.setStyleSheet("color: #888;")

        model = self.model_combo.currentText().strip()

        def _test():
            return test_connection(api_key, provider=provider, ollama_url=ollama_url,
                                   model=model, gemini_api_key=gemini_key)

        def _on_done(result):
            ok, message = result
            if ok:
                self.test_status.setStyleSheet("color: #2e7d32;")
            else:
                self.test_status.setStyleSheet("color: #c62828;")
            self.test_status.setText(message)
            self.test_btn.setEnabled(True)
            self._bg = None

        self._bg = _BgWorker(_test, self)
        self._bg.done.connect(_on_done)
        self._bg.start()

    def _save(self):
        conf = mw.addonManager.getConfig(MODULE) or {}
        conf["provider"] = self._current_provider()
        conf["api_key"] = self.api_key_edit.text().strip()
        conf["ollama_url"] = self.ollama_url_edit.text().strip() or "http://localhost:11434"
        conf["gemini_api_key"] = self.gemini_key_edit.text().strip()
        # Save per-provider models
        active_model = self.model_combo.currentText().strip()
        all_models = {
            "openrouter": self._openrouter_model,
            "ollama": self._ollama_model,
            "gemini": self._gemini_model,
        }
        all_models[self._active_provider] = active_model
        conf["openrouter_model"] = all_models["openrouter"]
        conf["ollama_model"] = all_models["ollama"]
        conf["gemini_model"] = all_models["gemini"]
        conf.pop("model", None)
        conf["system_prompt"] = self.prompt_edit.toPlainText()
        conf["max_tokens"] = self.max_tokens_spin.value()
        conf["temperature"] = self.temp_spin.value()
        conf["font_size"] = self.font_size_spin.value()
        conf["panel_width"] = self.panel_width_spin.value()
        conf["preview_enabled"] = self.preview_enabled_check.isChecked()
        conf["preview_url"] = self.preview_url_edit.text().strip()
        conf["preview_field"] = self.preview_field_edit.text().strip() or "Front"
        mw.addonManager.writeConfig(MODULE, conf)
        self.accept()

"""Chat panel – dockable side panel with streaming markdown chat."""

import datetime
import os
import urllib.parse

from aqt import mw
from aqt.qt import (
    QColor,
    QDockWidget,
    QEvent,
    QHBoxLayout,
    QLineEdit,
    QPalette,
    QPushButton,
    QSplitter,
    QTimer,
    QUrl,
    QVBoxLayout,
    QWidget,
    Qt,
)

try:
    from aqt.qt import QWebEngineView
except ImportError:
    from PyQt6.QtWebEngineWidgets import QWebEngineView

from .api_client import StreamWorker
from .card_context import clean_field

_ADDON_DIR = os.path.dirname(__file__)

MODULE = __name__.split(".")[0]

# ---------------------------------------------------------------------------
# Qt stylesheet – mirrors Anki's native light UI
# ---------------------------------------------------------------------------

_STYLE = """
QDockWidget, QDockWidget > QWidget {{
    background-color: #ffffff;
    border: none;
}}
QWidget#chatContainer {{
    background-color: #ffffff;
}}
QWidget#inputBar {{
    background-color: #f5f5f5;
    border-top: 1px solid #c4c4c4;
}}
QLineEdit#chatInput {{
    background-color: #ffffff;
    color: #333;
    border: 1px solid #ccc;
    border-radius: 4px;
    padding: 6px 8px;
    font-size: {font_size}px;
}}
QLineEdit#chatInput:focus {{
    border-color: #4a90d9;
}}
QPushButton#sendBtn {{
    background-color: #333;
    color: #fff;
    border: none;
    min-width: 30px; max-width: 30px;
    min-height: 30px; max-height: 30px;
    border-radius: 15px;
    font-size: 16px;
    padding: 0;
}}
QPushButton#sendBtn:hover {{ background-color: #1a1a1a; }}
QWidget#titleBar {{
    background-color: #ffffff;
    border: none;
}}
QDockWidget::separator {{
    background: #fff; width: 0; height: 0;
}}
QPushButton#toggleBtn, QPushButton#expandBtn {{
    background-color: #333;
    color: #fff;
    border: none;
    min-width: 22px; max-width: 22px;
    min-height: 22px; max-height: 22px;
    border-radius: 11px;
    font-size: 11px;
    padding: 0; padding-bottom: 1px;
}}
QPushButton#toggleBtn:hover, QPushButton#expandBtn:hover {{
    background-color: #1a1a1a;
}}
QPushButton#settingsBtn {{
    background-color: transparent;
    color: #999;
    border: none;
    font-size: 16px;
    padding: 0;
}}
QPushButton#settingsBtn:hover {{ color: #555; }}
QSplitter::handle:vertical {{
    background-color: #d4d4d4;
}}
"""

# ---------------------------------------------------------------------------
# Chat HTML – markdown-it for rendering, minimal JS interface
# ---------------------------------------------------------------------------

_CHAT_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="markdown-it.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:-apple-system,"Segoe UI","Helvetica Neue",sans-serif;
  font-size:FONT_SIZEpx; color:#333; background:#fff;
  padding:12px; line-height:1.5;
}
.msg{margin-bottom:12px}
.msg.user{color:#555;padding:8px 12px;background:#f5f5f5;border-radius:8px}
.msg.assistant{padding:4px 0}
.msg.assistant p{margin:4px 0}
.msg.assistant code{
  background:#f0f0f0;padding:1px 5px;border-radius:3px;
  font-family:"SF Mono",Menlo,Monaco,Consolas,monospace;font-size:.9em;
}
.msg.assistant pre{
  background:#f6f6f6;border-radius:6px;padding:10px 12px;
  overflow-x:auto;margin:8px 0;
}
.msg.assistant pre code{background:none;padding:0;font-size:.88em;line-height:1.45}
.msg.assistant blockquote{
  border-left:3px solid #ddd;padding-left:10px;color:#666;margin:6px 0;
}
.msg.assistant ul,.msg.assistant ol{padding-left:20px;margin:4px 0}
.msg.assistant h1,.msg.assistant h2,.msg.assistant h3{
  margin:8px 0 4px;font-size:1em;font-weight:600;
}
.msg.system{color:#aaa;font-style:italic;font-size:.9em}
#welcome{
  display:flex;flex-direction:column;align-items:center;
  justify-content:center;height:80vh;color:#bbb;user-select:none;
}
#welcome .provider-name{
  font-size:.8em;color:#bbb;margin-bottom:2px;
  text-transform:uppercase;letter-spacing:.05em;
}
#welcome .model-name{
  font-size:.85em;color:#aaa;margin-bottom:6px;
  font-family:"SF Mono",Menlo,Monaco,Consolas,monospace;
}
#welcome .hint{font-size:.9em;color:#bbb}
.cursor{
  display:inline-block;width:2px;height:1em;background:#333;
  animation:blink 1s step-end infinite;
  vertical-align:text-bottom;margin-left:1px;
}
@keyframes blink{50%{opacity:0}}
</style></head><body>
<div id="welcome">
  <div class="provider-name" id="providerName">PROVIDER_NAME</div>
  <div class="model-name" id="modelName">MODEL_NAME</div>
  <div class="hint">Ask me anything about your flashcard</div>
</div>
<div id="chat"></div>
<script>
const md=markdownit({html:false,linkify:true,breaks:true});
const chat=document.getElementById("chat");
const welcome=document.getElementById("welcome");
let block=null, raw="", active=false;

function scrollBottom(){window.scrollTo(0,document.body.scrollHeight)}

function setModel(n){document.getElementById("modelName").textContent=n}
function setProvider(n){document.getElementById("providerName").textContent=n}

function addUser(t){
  welcome.style.display="none";
  const d=document.createElement("div");d.className="msg user";
  d.textContent=t;chat.appendChild(d);scrollBottom();
}
function addSystem(t){
  const d=document.createElement("div");d.className="msg system";
  d.textContent=t;chat.appendChild(d);scrollBottom();
}
function startAssistant(){
  raw="";active=true;
  block=document.createElement("div");block.className="msg assistant";
  block.innerHTML='<span class="cursor"></span>';
  chat.appendChild(block);scrollBottom();
}
function appendChunk(t){
  raw+=t;
  if(block){block.innerHTML=md.render(raw)+'<span class="cursor"></span>';scrollBottom()}
}
function finishAssistant(){
  active=false;
  if(block){block.innerHTML=md.render(raw);scrollBottom()}
  block=null;raw="";
}
function clearChat(){
  chat.innerHTML="";block=null;raw="";active=false;
  welcome.style.display="flex";
}
</script></body></html>"""


# ---------------------------------------------------------------------------
# JS string escaping
# ---------------------------------------------------------------------------

def _js(s):
    """Escape *s* for safe embedding in a JS double-quoted string literal."""
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("<", "\\x3c")
        .replace(">", "\\x3e")
    )


_PREVIEW_EMPTY_HTML = (
    '<html><body style="margin:0;padding:0;background:#fff;"></body></html>'
)


# ---------------------------------------------------------------------------
# ChatPanel
# ---------------------------------------------------------------------------

class ChatPanel(QDockWidget):
    """Dockable chat panel that streams LLM responses about the current card."""

    def __init__(self, parent=None):
        super().__init__("Card Assistant", parent or mw)
        self.setObjectName("CardAssistant")
        self.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)

        self._build_title_bar()
        self._force_white_background()

        self._messages: list[dict] = []
        self._card_context = ""
        self._worker: StreamWorker | None = None
        self._streaming = False
        self._web_ready = False
        self._collapsed = False
        self._expanded_width: int | None = None
        self._current_card = None
        self._preview_loading_real_url: bool = False
        self._preview_last_url: str = ""

        self._build_ui()
        self._apply_style()

    # -- config helper -----------------------------------------------------

    def _conf(self):
        return mw.addonManager.getConfig(MODULE) or {}

    @staticmethod
    def _active_model(conf):
        """Return the model string for the currently active provider."""
        provider = conf.get("provider", "openrouter")
        if provider == "ollama":
            return conf.get("ollama_model", "")
        if provider == "gemini":
            return conf.get("gemini_model", "gemini-2.5-flash")
        return conf.get("openrouter_model", conf.get("model", "deepseek/deepseek-v3.2"))

    @staticmethod
    def _provider_label(provider):
        return {"ollama": "Ollama", "gemini": "Gemini"}.get(provider, "OpenRouter")

    # -- construction ------------------------------------------------------

    def _build_title_bar(self):
        bar = QWidget()
        bar.setObjectName("titleBar")
        bar.setFixedHeight(34)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 6, 6, 6)

        self._settings_btn = QPushButton("\u2699")
        self._settings_btn.setObjectName("settingsBtn")
        self._settings_btn.setFixedSize(22, 22)
        self._settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(self._settings_btn)

        layout.addStretch()

        self._toggle_btn = QPushButton("\u2715")
        self._toggle_btn.setObjectName("toggleBtn")
        self._toggle_btn.clicked.connect(self._toggle_collapse)
        layout.addWidget(self._toggle_btn)

        self.setTitleBarWidget(bar)

    def _force_white_background(self):
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

    def _build_ui(self):
        container = QWidget()
        container.setObjectName("chatContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        conf = self._conf()

        # Vertical splitter: preview (top) + chat (bottom)
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setHandleWidth(3)
        self._splitter.setChildrenCollapsible(True)
        layout.addWidget(self._splitter, stretch=1)

        # Top pane: word preview web view
        self._preview_web = QWebEngineView()
        self._preview_web.setHtml(_PREVIEW_EMPTY_HTML)
        self._preview_web.loadFinished.connect(self._on_preview_load)
        self._splitter.addWidget(self._preview_web)

        # Bottom pane: markdown chat web view
        provider = conf.get("provider", "openrouter")
        provider_label = self._provider_label(provider)
        chat_html = (
            _CHAT_HTML
            .replace("FONT_SIZE", str(conf.get("font_size", 12)))
            .replace("PROVIDER_NAME", provider_label)
            .replace("MODEL_NAME", self._active_model(conf))
        )
        self._web = QWebEngineView()
        self._web.setHtml(chat_html, QUrl.fromLocalFile(_ADDON_DIR + "/"))
        self._web.loadFinished.connect(self._on_web_ready)
        self._splitter.addWidget(self._web)

        # Apply initial preview visibility
        self._update_preview_visibility(conf)

        # Bottom input bar (outside splitter, always visible)
        self._input_bar = QWidget()
        self._input_bar.setObjectName("inputBar")
        row = QHBoxLayout(self._input_bar)
        row.setContentsMargins(9, 0, 9, 0)
        row.setSpacing(6)

        self._input = QLineEdit()
        self._input.setObjectName("chatInput")
        self._input.setPlaceholderText("Ask about this card\u2026")
        self._input.returnPressed.connect(self._on_send)
        self._input.installEventFilter(self)
        row.addWidget(self._input, stretch=1)

        self._send_btn = QPushButton("\u2191")
        self._send_btn.setObjectName("sendBtn")
        self._send_btn.clicked.connect(self._on_send)
        row.addWidget(self._send_btn)

        layout.addWidget(self._input_bar)
        self.setWidget(container)

    def _update_preview_visibility(self, conf):
        """Show or hide the preview pane based on config."""
        enabled = conf.get("preview_enabled", False)
        self._preview_web.setVisible(enabled)
        if enabled:
            # Defer sizing until Qt has performed layout
            QTimer.singleShot(0, self._fix_splitter_sizes)
            QTimer.singleShot(300, self._fix_splitter_sizes)

    def _fix_splitter_sizes(self):
        """Set splitter proportions after the widget has been laid out."""
        total = self._splitter.height()
        if total > 50:
            preview = total // 3
            self._splitter.setSizes([preview, total - preview])

    def _on_preview_load(self, ok: bool):
        """Called when the preview pane finishes loading a URL or HTML.

        Only acts on intentional URL navigations (flagged by _load_preview).
        Sub-resource failures (CSS, images) do not replace the page.
        """
        if not self._preview_loading_real_url:
            # setHtml loads (empty placeholder etc.) – ignore completely
            return
        self._preview_loading_real_url = False
        if not ok:
            self._log_preview_error(
                f"Failed to load URL: {self._preview_last_url}"
            )

    def _log_preview_error(self, msg: str):
        """Append a preview error entry to Logs.txt in the add-on directory."""
        try:
            log_path = os.path.join(_ADDON_DIR, "Logs.txt")
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"[{timestamp}] {msg}\n")
        except Exception:
            pass  # never surface a logging failure into Anki

    def _apply_style(self):
        conf = self._conf()
        self.setStyleSheet(_STYLE.format(font_size=conf.get("font_size", 12)))
        if not self._collapsed:
            self.setMinimumWidth(280)
            self.setMaximumWidth(800)
            self.resize(conf.get("panel_width", 400), self.height())

    # -- event filter (keep keys in input, not Anki shortcuts) -------------

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().eventFilter(obj, event)

    # -- web bridge --------------------------------------------------------

    def _on_web_ready(self, ok):
        self._web_ready = ok

    def _js(self, code):
        if self._web_ready:
            self._web.page().runJavaScript(code)

    # -- settings ----------------------------------------------------------

    def _open_settings(self):
        from .config_dialog import ConfigDialog
        if ConfigDialog(self).exec():
            self._apply_style()
            conf = self._conf()
            fs = conf.get("font_size", 12)
            self._js(f"document.body.style.fontSize='{fs}px';")
            model = self._active_model(conf)
            self._js(f'setModel("{_js(model)}");')
            provider = conf.get("provider", "openrouter")
            provider_label = self._provider_label(provider)
            self._js(f'setProvider("{_js(provider_label)}");')
            self._update_preview_visibility(conf)
            if not self._collapsed:
                self._load_preview(self._current_card, conf)

    # -- collapse / expand -------------------------------------------------

    def _toggle_collapse(self):
        if self._collapsed:
            self._collapsed = False
            self._js("document.body.style.visibility='visible';")
            self._settings_btn.show()
            self._input.show()
            self._send_btn.show()
            conf = self._conf()
            self._update_preview_visibility(conf)
            self.setMinimumWidth(280)
            self.setMaximumWidth(800)
            w = self._expanded_width or conf.get("panel_width", 400)
            self.resize(w, self.height())
            self._toggle_btn.setText("\u2715")
            self._toggle_btn.setObjectName("toggleBtn")
            self._toggle_btn.setStyle(self._toggle_btn.style())
        else:
            self._expanded_width = self.width()
            self._collapsed = True
            self._js("document.body.style.visibility='hidden';")
            self._settings_btn.hide()
            self._input.hide()
            self._send_btn.hide()
            self._preview_web.setVisible(False)
            self.setMinimumWidth(34)
            self.setMaximumWidth(34)
            self._toggle_btn.setText("\u276E")
            self._toggle_btn.setObjectName("expandBtn")
            self._toggle_btn.setStyle(self._toggle_btn.style())

    # -- bottom-bar height sync --------------------------------------------

    def sync_bottom_height(self):
        """Match the input bar height to Anki's reviewer bottom bar."""
        def _sync():
            try:
                if mw.state != "review":
                    return
                h = mw.reviewer.bottom.web.height()
                if h > 0:
                    self._input_bar.setFixedHeight(h)
            except (AttributeError, RuntimeError):
                pass
        _sync()
        QTimer.singleShot(100, _sync)
        QTimer.singleShot(300, _sync)

    # -- card context ------------------------------------------------------

    def on_new_card(self, context: str, card=None):
        """New card shown – clear chat, update context, load word preview."""
        self._card_context = context
        self._current_card = card
        self._cancel_stream()
        self._messages.clear()
        self._js("clearChat();")
        conf = self._conf()
        model = self._active_model(conf)
        self._js(f'setModel("{_js(model)}");')
        provider = conf.get("provider", "openrouter")
        provider_label = self._provider_label(provider)
        self._js(f'setProvider("{_js(provider_label)}");')
        self._load_preview(card, conf)

    def on_answer_shown(self, context: str):
        """Answer revealed – update context, keep chat history."""
        self._card_context = context

    def _load_preview(self, card, conf):
        """Navigate the preview pane to the configured URL for the current word."""
        if not conf.get("preview_enabled", False) or card is None:
            return

        url_template = conf.get("preview_url", "").strip()
        # Support comma-separated list of field names; try each in order
        raw_field_conf = (conf.get("preview_field", "") or "").strip()
        candidate_fields = [f.strip() for f in raw_field_conf.split(",") if f.strip()]
        if not url_template:
            self._log_preview_error(
                "No URL template configured. Open Settings and set a Preview URL."
            )
            return

        # Extract the target field value and clean it to plain text
        field_names = []
        field_map = {}
        try:
            note = card.note()
            model_obj = note.model()
            field_names = [f["name"] for f in model_obj.get("flds", [])]
            field_map = dict(zip(field_names, note.fields))
        except Exception as e:
            self._log_preview_error(f"Failed to read card fields: {e}")
            return

        # Try each candidate field in order
        word = ""
        for candidate in candidate_fields:
            if candidate in field_map:
                word = clean_field(field_map[candidate])
                if word:
                    break

        # Fall back to the first field if nothing found
        if not word and field_names:
            word = clean_field(field_map.get(field_names[0], ""))

        if not word:
            available = ", ".join(field_names) if field_names else "(none)"
            tried = ", ".join(candidate_fields) if candidate_fields else "(none)"
            self._log_preview_error(
                f"No usable value found in fields: {tried}. "
                f"Available fields: {available}"
            )
            return

        # Build the final URL by substituting the {word} placeholder
        encoded = urllib.parse.quote(word, safe="")
        url = url_template.replace("{word}", encoded)
        self._preview_loading_real_url = True
        self._preview_last_url = url
        self._preview_web.load(QUrl(url))

    # -- send / stream -----------------------------------------------------

    def _on_send(self):
        if self._streaming:
            self._cancel_stream()
            return

        text = self._input.text().strip()
        if not text:
            return

        # Clean up any lingering worker from a previous request
        if self._worker is not None:
            self._cleanup_worker()

        self._input.clear()
        self._js(f'addUser("{_js(text)}");')
        self._messages.append({"role": "user", "content": text})

        conf = self._conf()

        # Build message list: system prompt + card context + conversation
        messages = []
        prompt = conf.get("system_prompt", "")
        if prompt:
            messages.append({"role": "system", "content": prompt})
        if self._card_context:
            messages.append({
                "role": "system",
                "content": f"Current card:\n{self._card_context}",
            })
        messages.extend(self._messages)

        self._js("startAssistant();")
        self._set_streaming(True)

        self._worker = StreamWorker(
            api_key=conf.get("api_key", ""),
            model=self._active_model(conf),
            messages=messages,
            max_tokens=conf.get("max_tokens", 1024),
            temperature=conf.get("temperature", 0.7),
            provider=conf.get("provider", "openrouter"),
            ollama_url=conf.get("ollama_url", "http://localhost:11434"),
            gemini_api_key=conf.get("gemini_api_key", ""),
        )
        self._worker.chunk_received.connect(self._on_chunk)
        self._worker.stream_finished.connect(self._on_finished)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _on_chunk(self, text):
        self._js(f'appendChunk("{_js(text)}");')

    def _on_finished(self, full):
        self._js("finishAssistant();")
        self._set_streaming(False)
        if full:
            self._messages.append({"role": "assistant", "content": full})
        self._cleanup_worker()

    def _on_error(self, msg):
        self._js("finishAssistant();")
        self._set_streaming(False)
        self._js(f'addSystem("{_js(msg)}");')
        self._cleanup_worker()

    def _set_streaming(self, active):
        self._streaming = active
        if active:
            self._send_btn.setText("\u25A0")
            self._send_btn.setStyleSheet(
                "background-color:#d93025;color:#fff;border:none;"
                "min-width:30px;max-width:30px;min-height:30px;max-height:30px;"
                "border-radius:15px;font-size:12px;padding:0;"
            )
            self._input.setEnabled(False)
        else:
            self._send_btn.setText("\u2191")
            self._send_btn.setStyleSheet("")
            self._input.setEnabled(True)
            self._input.setFocus()

    def _cleanup_worker(self):
        """Disconnect signals and wait for the worker thread to finish."""
        w = self._worker
        if w is None:
            return
        self._worker = None
        try:
            w.chunk_received.disconnect(self._on_chunk)
            w.stream_finished.disconnect(self._on_finished)
            w.error_occurred.disconnect(self._on_error)
        except (TypeError, RuntimeError):
            pass
        if w.isRunning():
            w.wait(3000)  # wait up to 3 s

    def _cancel_stream(self):
        if self._worker and self._streaming:
            self._worker.cancel()
            self._cleanup_worker()
            self._js("finishAssistant();")
            self._set_streaming(False)
            self._js('addSystem("(stopped)");')

    def cleanup(self):
        """Cancel stream and reset state (called when leaving review)."""
        self._cancel_stream()
        self._messages.clear()
        self._js("clearChat();")
        self._card_context = ""
        self._current_card = None
        self._preview_web.setHtml(_PREVIEW_EMPTY_HTML)

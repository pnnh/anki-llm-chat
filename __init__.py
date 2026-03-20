"""Card Assistant – Anki add-on that provides an LLM chat panel for reviewing.

Connects to OpenRouter (any model) and streams responses about the
current flashcard. Works with any note type – text fields are extracted
automatically; media references (images, audio, video) are stripped.
"""

from aqt import gui_hooks, mw
from aqt.qt import QAction, Qt

from .card_context import extract_context


def _setup():
    from .chat_panel import ChatPanel

    panel = ChatPanel(mw)
    mw._card_assistant_panel = panel
    mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, panel)
    panel.hide()

    # -- reviewer hooks ----------------------------------------------------

    def on_question(card):
        panel.on_new_card(extract_context(card, answer_shown=False), card=card)
        panel.sync_bottom_height()

    def on_answer(card):
        panel.on_answer_shown(extract_context(card, answer_shown=True))
        panel.sync_bottom_height()

    def on_state_change(new_state, _old_state):
        if new_state == "review":
            panel.show()
        else:
            panel.cleanup()
            panel.hide()

    def on_review_end():
        panel.cleanup()

    def on_profile_close():
        panel.cleanup()

    gui_hooks.reviewer_did_show_question.append(on_question)
    gui_hooks.reviewer_did_show_answer.append(on_answer)
    gui_hooks.state_did_change.append(on_state_change)
    gui_hooks.reviewer_will_end.append(on_review_end)
    gui_hooks.profile_will_close.append(on_profile_close)

    # -- menu toggle -------------------------------------------------------

    action = QAction("Card Assistant", mw)
    action.setCheckable(True)
    action.setChecked(False)
    action.toggled.connect(lambda on: panel.show() if on else panel.hide())
    panel.visibilityChanged.connect(action.setChecked)
    mw.form.menuTools.addAction(action)

    # -- add-on manager config button --------------------------------------

    def on_config():
        from .config_dialog import ConfigDialog
        ConfigDialog(mw).exec()

    mw.addonManager.setConfigAction(__name__.split(".")[0], on_config)


gui_hooks.main_window_did_init.append(_setup)

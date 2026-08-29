"""Issue #101: Die Vorschau-Zeile unter "Neuer Dateiname" erscheint nur, wenn
der endgueltige Name vom Eingetippten abweicht."""


def _panel(qtbot):
    from src.gui import detail_panel as dp
    panel = dp.DetailPanel()
    qtbot.addWidget(panel)
    panel.show()
    return panel


def test_preview_hidden_when_name_is_unchanged(qtbot):
    panel = _panel(qtbot)
    panel.name_input.setText("2013-02-25_Rechnung_Notar_Eisenburger")
    assert panel.preview_label.isHidden()
    assert panel.warning_label.isHidden()
    assert panel.get_new_name() == "2013-02-25_Rechnung_Notar_Eisenburger.pdf"


def test_preview_hidden_when_empty(qtbot):
    panel = _panel(qtbot)
    panel.name_input.setText("abc")
    panel.name_input.setText("")
    assert panel.preview_label.isHidden()
    assert panel.warning_label.isHidden()


def test_preview_shown_when_characters_are_replaced(qtbot):
    panel = _panel(qtbot)
    panel.name_input.setText("Rechnung: Müller/2024")
    assert not panel.preview_label.isHidden()
    assert panel.preview_label.text() == "Rechnung_Mueller_2024.pdf"
    assert "Wird ersetzt" in panel.warning_label.text()

    # Zurueck auf einen sauberen Namen -> Zeile verschwindet wieder
    panel.name_input.setText("Rechnung_Mueller_2024")
    assert panel.preview_label.isHidden()


def test_preview_shown_for_email(qtbot):
    panel = _panel(qtbot)
    panel.name_input.setText("Meldung kathrin.haerle@web.de")
    assert not panel.preview_label.isHidden()
    assert "Kathrin" in panel.preview_label.text()


def test_move_only_toggle_is_gone(qtbot):
    panel = _panel(qtbot)
    assert not hasattr(panel, "move_only_toggle")
    assert not hasattr(panel, "hint_label")

"""Issue #106: Rangfolge der Vorschlagsarten (reine Logik, ohne Qt)."""
from src.core.filename_placeholders import PRESETS
from src.core.suggestion_order import (
    KIND_AUTO,
    KIND_CATEGORY_NUMBER,
    KIND_DATE,
    KIND_DATE_CATEGORY,
    KIND_KI,
    KIND_LEARNED,
    KIND_OTHER,
    default_order,
    effective_order,
    kind_from_reason,
    pattern_kind,
    promote,
    sort_by_kind,
)

RECHNUNGEN = "{datum}_{kategorie}_{kontakt}_{betreff}"
AKTEN = "{initialen}_{aktenzeichen}_{datum}_{betreff}_{kontakt}"
BUERO = "{initialen} {datum}-{betreff}"


def test_kind_from_reason_covers_all_sources():
    assert kind_from_reason("KI-Vorschlag") == KIND_KI
    assert kind_from_reason("KI (gecacht): Vorschlag") == KIND_KI
    assert kind_from_reason("KI: Rechnung erkannt") == KIND_KI
    assert kind_from_reason("Gelernt: ähnlich zu alt.pdf") == KIND_LEARNED
    assert kind_from_reason("Automatisch erkannt") == KIND_AUTO
    assert kind_from_reason("Datum + Kategorie (Rechnung)") == KIND_DATE_CATEGORY
    assert kind_from_reason("Kategorie + Nummer") == KIND_CATEGORY_NUMBER
    assert kind_from_reason("Nur Datum") == KIND_DATE
    assert kind_from_reason("") == KIND_OTHER
    assert kind_from_reason("Irgendwas") == KIND_OTHER


def test_default_order_ki_then_patterns_then_analysis():
    order = default_order("")
    presets = [pattern_kind(p) for _n, p in PRESETS if p]
    assert order[0] == KIND_KI
    assert order[1:1 + len(presets)] == presets
    assert order[1 + len(presets):] == [
        KIND_LEARNED, KIND_AUTO, KIND_DATE_CATEGORY, KIND_CATEGORY_NUMBER, KIND_DATE, KIND_OTHER,
    ]


def test_default_order_puts_settings_pattern_first_among_patterns():
    # Vorlage aus den Einstellungen rueckt vor die anderen Vorlagen
    order = default_order(BUERO)
    assert order[:2] == [KIND_KI, pattern_kind(BUERO)]
    assert order.count(pattern_kind(BUERO)) == 1
    # Eigenes Muster, das keiner Vorlage entspricht, ebenso
    order = default_order("{jahr}_{kontakt}")
    assert order[:3] == [KIND_KI, pattern_kind("{jahr}_{kontakt}"), pattern_kind(RECHNUNGEN)]


def test_effective_order_merges_saved_with_defaults():
    saved = [pattern_kind(AKTEN), KIND_AUTO, "", 42, KIND_AUTO]
    order = effective_order(saved, "")
    assert order[:2] == [pattern_kind(AKTEN), KIND_AUTO]
    assert order.count(KIND_AUTO) == 1
    assert set(default_order("")) <= set(order)
    assert effective_order(None, "") == default_order("")


def test_promote_moves_kind_to_top_and_shifts_rest_down():
    order = [KIND_KI, pattern_kind(RECHNUNGEN), pattern_kind(AKTEN), KIND_AUTO]
    assert promote(order, pattern_kind(AKTEN)) == [
        pattern_kind(AKTEN), KIND_KI, pattern_kind(RECHNUNGEN), KIND_AUTO,
    ]
    # Bereits oben: unveraendert
    assert promote(order, KIND_KI) == order
    # Unbekannte Art wird vorne angehaengt
    assert promote(order, "neu")[0] == "neu"


def test_sort_by_kind_is_stable_and_puts_unknown_last():
    items = [("c", KIND_AUTO), ("a1", KIND_KI), ("x", "fremd"), ("a2", KIND_KI), ("b", KIND_LEARNED)]
    order = [KIND_AUTO, KIND_KI, KIND_LEARNED]
    assert [o for o, _k in sort_by_kind(items, order)] == ["c", "a1", "a2", "b", "x"]


def test_default_order_includes_saved_custom_patterns_after_builtin():
    custom = [("Mieter", "{jahr}_{kontakt}_Miete")]
    order = default_order("", custom)
    presets = [pattern_kind(p) for _n, p in PRESETS if p]
    assert order[1:1 + len(presets)] == presets
    assert order[1 + len(presets)] == pattern_kind("{jahr}_{kontakt}_Miete")
    assert pattern_kind("{jahr}_{kontakt}_Miete") in effective_order(None, "", custom)


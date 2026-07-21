from src.score.align import align


def _row(label, **extra):
    return {"raw_label": label, **extra}


def test_matched_missing_and_extra():
    gold = [_row("A"), _row("B")]
    outputs = [_row("A"), _row("C")]
    result = align(outputs, gold)

    assert [k for k, _, _ in result.matched] == ["A"]
    assert result.missing_in_outputs == ["B"]
    assert result.extra_in_outputs == ["C"]


def test_duplicate_output_keys_flagged():
    gold = [_row("A")]
    outputs = [_row("A"), _row("A")]
    result = align(outputs, gold)
    assert result.duplicate_output_keys == ["A"]


def test_near_miss_when_decoder_alters_label():
    # An output whose raw_label differs only by whitespace/case from a gold key.
    gold = [_row("Fjernvarme Energi")]
    outputs = [_row("fjernvarme  energi")]
    result = align(outputs, gold)
    assert result.extra_in_outputs == ["fjernvarme  energi"]
    assert result.near_miss_keys == [("fjernvarme  energi", "Fjernvarme Energi")]

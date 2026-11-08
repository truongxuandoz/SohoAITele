from soho.money import extract_money_tokens, format_money, parse_money


def test_thousand_separators():
    assert parse_money("1.480.000") == 1_480_000
    assert parse_money("1,480,000") == 1_480_000
    assert parse_money("1480000") == 1_480_000
    assert parse_money("7.527.967") == 7_527_967


def test_shorthand_units():
    assert parse_money("159k") == 159_000
    assert parse_money("500 nghìn") == 500_000
    assert parse_money("70k") == 70_000
    assert parse_money("1tr2") == 1_200_000
    assert parse_money("2tr5") == 2_500_000
    assert parse_money("1,5tr") == 1_500_000
    assert parse_money("2 triệu") == 2_000_000
    assert parse_money("1 tỷ") == 1_000_000_000


def test_with_currency_suffix():
    assert parse_money("990.000đ") == 990_000
    assert parse_money("159.000 vnđ") == 159_000
    assert parse_money("500000 đồng") == 500_000


def test_noise_and_none():
    assert parse_money("") is None
    assert parse_money("p304 tt") is None
    assert parse_money(None) is None
    assert parse_money("14/8") != 14


def test_extract_multiple():
    got = extract_money_tokens("chi 159k cước hotline, thu 1tr2 hoàn ứng")
    assert 159_000 in got and 1_200_000 in got


def test_format():
    assert format_money(1480000) == "1.480.000"
    assert format_money(None) == ""

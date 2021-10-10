from botutils.stringutils import parse_number, Number


def test_parse_number():
    """
    Test cases for `botutils.stringutils.parse_number`
    """
    cases = [
        ("4", Number(4, "")),
        ("4.0", Number(4.0, "")),
        ("4.0 cans", Number(4.0, "cans")),
        (".0 foo", Number(0.0, "foo")),
        (".0    \nfoo", Number(0.0, "foo")),
        (".3cm", Number(0.3, "cm")),
        ("-.3cm", Number(-0.3, "cm")),
        ("3 3", Number(3, "3")),
        ("-1.3", Number(-1.3, "")),
        ("-4 foos", Number(-4, "foos")),
        ("4.03 cans", Number(4.03, "cans")),
        ("400.6491 cans", Number(400.6491, "cans")),
        ("403 cans", Number(403, "cans")),
        (".6491 foos", Number(.6491, "foos")),

        # Negative cases
        ("cm", ValueError),
        ("", ValueError),
        (" ", ValueError),
    ]
    errors = []
    for s, expected in cases:
        try:
            result = parse_number(s)
        except ValueError:
            result = ValueError
        if result != expected:
            errors.append("{}: expected {}, got {}".format(s, expected, result))

    if errors:
        assert False, "\n".join([""] + errors)

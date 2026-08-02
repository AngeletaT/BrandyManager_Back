def normalize_tax_id(value):
    return "".join(str(value or "").strip().upper().split())


def normalize_country_code(value):
    return str(value or "").strip().upper()

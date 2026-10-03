from app.errors.normalizer import normalize_code
def test_normalizes_common_variants():
    assert normalize_code(" err-5021 ")=="ERR-5021"
    assert normalize_code("Error-5021")=="ERR-5021"
    assert normalize_code("sql_1045")=="SQL-1045"

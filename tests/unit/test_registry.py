from app.registry.txt_registry import TxtRegistry
def test_registry_atomic_add(tmp_path):
    registry=TxtRegistry(tmp_path/"codes.txt"); registry.add_codes({"err-1","ERR-2"}); registry.add_codes({"ERROR-1"})
    assert registry.get_all_codes()=={"ERR-1","ERR-2"}

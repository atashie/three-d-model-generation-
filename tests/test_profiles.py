from tdmg.profiles import load_printer, printer_ids


def test_bambu_a1_profile():
    p = load_printer("bambu-a1")
    assert p.build_volume_mm == (256, 256, 256)
    assert p.nozzle_diameter_mm == 0.4
    mm = p.multi_material
    assert mm is not None and mm.default_max_filaments == 4
    # Files are AMS-agnostic: the profile records units as facts, and the default palette
    # fits the smallest of them (AMS lite, 4 slots).
    assert any(u.name == "AMS lite" and u.slots == 4 for u in mm.units)


def test_every_profile_cites_sources():
    for pid in printer_ids():
        assert load_printer(pid).sources, pid

from tdmg.profiles import load_printer, printer_ids


def test_bambu_a1_profile():
    p = load_printer("bambu-a1")
    assert p.build_volume_mm == (256, 256, 256)
    assert p.nozzle_diameter_mm == 0.4
    assert p.multi_material is not None and p.multi_material.max_filaments == 4
    # Which AMS unit is attached is an assumption until the owner confirms it.
    assert p.multi_material.confirmed is False and p.assumptions


def test_every_profile_cites_sources():
    for pid in printer_ids():
        assert load_printer(pid).sources, pid

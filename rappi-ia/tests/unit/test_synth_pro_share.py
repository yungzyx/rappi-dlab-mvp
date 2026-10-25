"""La marca Rappi Pro de las personas simuladas (events/synth.py: draw_pro): un supuesto propio, coherente con la
combinación de grupos del arquetipo y fuera del sorteo de la conducta."""

from rappi_ia.events.synth import ARCHETYPES, PRO_SHARE, draw_pro


def test_pro_is_reproducible_and_more_common_when_combining_groups():
    assert [draw_pro(7, n, "rest") for n in range(50)] == [draw_pro(7, n, "rest") for n in range(50)]
    shares = {}
    for archetype in ("rest", "rest+turbo", "rest+turbo+retail"):
        shares[archetype] = sum(draw_pro(7, n, archetype) for n in range(4000)) / 4000
    assert shares["rest"] < shares["rest+turbo"] < shares["rest+turbo+retail"]
    for archetype, share in shares.items():
        assert abs(share - PRO_SHARE[len(archetype.split("+"))]) < 0.03


def test_every_archetype_has_a_share():
    assert {len(archetype.split("+")) for archetype in ARCHETYPES} <= set(PRO_SHARE)

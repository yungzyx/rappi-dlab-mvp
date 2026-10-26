"""El reparto de la suite en partes para el CI (`RAPPI_IA_TEST_SHARD`, tests/conftest.py)."""

from conftest import shard_files


def test_every_file_goes_to_exactly_one_part_and_the_parts_are_even():
    weights = {f"tests/integration/test_{n}.py": float(n % 7 + 1) for n in range(30)}
    weights |= {f"tests/unit/test_{n}.py": 0.5 for n in range(10)}

    shards = shard_files(weights, 3)

    assert set().union(*shards) == set(weights)
    assert sum(len(s) for s in shards) == len(weights)
    loads = [sum(weights[path] for path in shard) for shard in shards]
    assert max(loads) - min(loads) <= max(weights.values())
    assert shard_files(dict(reversed(weights.items())), 3) == shards  # estable: no depende del orden de colección

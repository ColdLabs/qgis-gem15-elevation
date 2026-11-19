import os

import pytest

from gem15_elevation_downloader import cells
from gem15_elevation_downloader.cells import Cell

DATA = os.path.join(os.path.dirname(__file__), 'data')


# Each pair was listed in Google's bucket on 2026-11-19.
@pytest.mark.parametrize(
    'cell, group, cell_id',
    [
        (Cell(-9, 41), 'p40_m10', 'wm9s41'),
        (Cell(30, -1), 'm10_p30', 'w30sm1'),
        (Cell(140, -31), 'm40_p140', 'w140sm31'),
        (Cell(0, 5), 'p0_p0', 'w0s5'),
        (Cell(0, 50), 'p50_p0', 'w0s50'),
    ],
)
def test_names_match_the_bucket(cell, group, cell_id):
    assert (cell.group, cell.id) == (group, cell_id)


def test_porto_is_in_one_cell():
    assert cells.cells_in_bbox(-8.62, 41.13, -8.58, 41.16) == [Cell(-9, 41)]


def test_item_url_of_porto():
    assert Cell(-9, 41).item_url == (
        'https://storage.googleapis.com/climate-and-sustainability/gem-15/'
        'stac/gem-15/p40_m10/wm9s41/wm9s41.json'
    )


def test_bbox_over_a_corner_lists_four_cells():
    assert cells.cells_in_bbox(-0.5, -0.5, 0.5, 0.5) == [
        Cell(-1, -1),
        Cell(0, -1),
        Cell(-1, 0),
        Cell(0, 0),
    ]


def test_cell_edges_belong_to_the_cell_to_the_north_east():
    assert cells.cells_in_bbox(-9, 41, -9, 41) == [Cell(-9, 41)]


def test_latitude_is_limited_to_coverage():
    found = cells.cells_in_bbox(10, -80, 10, 89)
    assert found[0] == Cell(10, -60)
    assert found[-1] == Cell(10, 83)


def test_east_edge_of_the_world_is_cell_179():
    assert cells.cells_in_bbox(179.5, 0.5, 180, 0.5) == [Cell(179, 0)]


@pytest.mark.parametrize(
    'lon, lat, epsg',
    [(-8.6, 41.15, 32629), (-8.6, -41.15, 32729), (180, 0, 32660),
     (-180, 0, 32601), (3, 0, 32631)],
)
def test_utm_epsg(lon, lat, epsg):
    assert cells.utm_epsg(lon, lat) == epsg


def test_parse_the_real_porto_item():
    with open(os.path.join(DATA, 'wm9s41.json'), encoding='utf-8') as f:
        item = cells.parse_item(f.read())
    base = (
        'https://storage.googleapis.com/climate-and-sustainability/gem-15/'
        'p40_m10/wm9s41/'
    )
    assert item == (
        base + 'dsm/zall/mosaic.tif', base + 'dtm/zall/mosaic.tif', 32629
    )


@pytest.mark.parametrize('text', ['<html>', '{}', '{"assets": {}}'])
def test_parse_rejects_what_is_not_an_item(text):
    with pytest.raises(cells.BadItem):
        cells.parse_item(text)

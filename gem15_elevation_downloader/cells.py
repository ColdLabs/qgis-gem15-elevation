"""GEM-15 cells: one 1-degree square per STAC item, named after its
south-west corner.

Cell wm9s41 covers longitude -9 to -8 and latitude 41 to 42; it sits in the
10-degree group p40_m10 (latitude first). Negative numbers are written with
an m, positive ones with nothing in a cell id and with a p in a group id."""

import json
import math
from collections import namedtuple

STAC_ROOT = (
    'https://storage.googleapis.com/climate-and-sustainability/gem-15/stac/'
    'gem-15'
)
# Google's coverage: 60 S to 84 N.
SOUTH, NORTH = -60, 84


class BadItem(Exception):
    pass


def _cell_number(n):
    return 'm{}'.format(-n) if n < 0 else str(n)


def _group_number(n):
    return 'm{}'.format(-n) if n < 0 else 'p{}'.format(n)


class Cell(namedtuple('Cell', 'lon lat')):
    """The cell whose south-west corner is (lon, lat), in whole degrees."""

    @property
    def id(self):
        return 'w{}s{}'.format(_cell_number(self.lon), _cell_number(self.lat))

    @property
    def group(self):
        return '{}_{}'.format(
            _group_number(self.lat // 10 * 10),
            _group_number(self.lon // 10 * 10),
        )

    @property
    def bounds(self):
        return (self.lon, self.lat, self.lon + 1, self.lat + 1)

    @property
    def item_url(self):
        return '{}/{}/{}/{}.json'.format(
            STAC_ROOT, self.group, self.id, self.id
        )


def cells_in_bbox(xmin, ymin, xmax, ymax):
    """Every cell that touches the bbox (EPSG:4326), west to east and south
    to north, limited to Google's latitude coverage."""
    west = max(-180, math.floor(xmin))
    east = min(179, math.floor(xmax))
    south = max(SOUTH, math.floor(ymin))
    north = min(NORTH - 1, math.floor(ymax))
    return [
        Cell(lon, lat)
        for lat in range(south, north + 1)
        for lon in range(west, east + 1)
    ]


def utm_epsg(lon, lat):
    """The WGS 84 / UTM zone EPSG code for a point."""
    zone = min(60, int((lon + 180) // 6) + 1)
    return (32600 if lat >= 0 else 32700) + zone


Item = namedtuple('Item', 'dsm_url dtm_url epsg')


def parse_item(text):
    """The DSM and DTM URLs and the EPSG code of a STAC item."""
    try:
        item = json.loads(text)
        assets = item['assets']
        return Item(
            assets['dsm']['href'],
            assets['dtm']['href'],
            int(item['properties']['proj:epsg']),
        )
    except (ValueError, KeyError, TypeError) as e:
        raise BadItem('not a GEM-15 item: {!r}'.format(e))

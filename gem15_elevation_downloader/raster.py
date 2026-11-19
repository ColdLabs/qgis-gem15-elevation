"""Clip GEM-15 COGs with GDAL, which reads only the blocks it needs over
HTTP range requests."""

import uuid

from osgeo import gdal

# Every GEM-15 cell sits on a 15 m grid in its UTM zone.
PIXEL_M = 15
TAGS = {
    'SOURCE': 'GEM-15 (Google Research), '
              'gs://climate-and-sustainability/gem-15',
    'LICENSE': 'CC-BY-4.0',
    'ATTRIBUTION': 'This dataset is produced by Google',
}


class RasterError(Exception):
    pass


class Canceled(Exception):
    pass


def _options(driver):
    if driver == 'GTiff':
        return [
            'COMPRESS=DEFLATE',
            'PREDICTOR=3',
            'TILED=YES',
            'BIGTIFF=IF_SAFER',
        ]
    return []


def _callback(on_progress, is_canceled):
    def callback(complete, message, data):
        on_progress(complete)
        return 0 if is_canceled() else 1

    return callback


def _fail(what, is_canceled):
    if is_canceled():
        raise Canceled()
    raise RasterError('{}: {}'.format(what, gdal.GetLastErrorMsg()))


def clip(urls, dest, driver, dst_wkt, bounds, resolution, cutline_geojson,
         on_progress, is_canceled):
    """Write band 1 of every COG in urls into one raster on dest's grid.

    bounds and resolution are in the units of dst_wkt. The grid is aligned to
    multiples of resolution, so a clip in the cells' own UTM zone keeps their
    pixels as they are. cutline_geojson, in EPSG:4326, masks out what lies
    outside the polygons."""
    cutline = None
    if cutline_geojson is not None:
        cutline = '/vsimem/gem15_cutline_{}.geojson'.format(uuid.uuid4().hex)
        gdal.FileFromMemBuffer(cutline, cutline_geojson.encode('utf-8'))
    try:
        gdal.ErrorReset()
        out = gdal.Warp(
            dest,
            ['/vsicurl/' + url for url in urls],
            options=gdal.WarpOptions(
                format=driver,
                dstSRS=dst_wkt,
                outputBounds=bounds,
                xRes=resolution,
                yRes=resolution,
                targetAlignedPixels=True,
                srcBands=[1],
                resampleAlg='bilinear',
                dstNodata=float('nan'),
                outputType=gdal.GDT_Float32,
                cutlineDSName=cutline,
                multithread=True,
                creationOptions=_options(driver),
                callback=_callback(on_progress, is_canceled),
            ),
        )
        if out is None:
            _fail('Cannot clip GEM-15', is_canceled)
        out = None
    finally:
        if cutline is not None:
            gdal.Unlink(cutline)


def difference(dsm_path, dtm_path, dest, driver, on_progress, is_canceled):
    """Write dsm minus dtm. Both rasters must share one grid, as clip()
    makes them when given the same bounds, resolution and CRS."""
    dsm = gdal.Open(dsm_path)
    if dsm is None:
        raise RasterError('Cannot open {}'.format(dsm_path))
    vrt = (
        '<VRTDataset rasterXSize="{x}" rasterYSize="{y}">'
        '<SRS>{srs}</SRS><GeoTransform>{gt}</GeoTransform>'
        '<VRTRasterBand dataType="Float32" band="1" '
        'subClass="VRTDerivedRasterBand">'
        '<NoDataValue>nan</NoDataValue>'
        '<PixelFunctionType>diff</PixelFunctionType>'
        '<SimpleSource><SourceFilename relativeToVRT="0">{dsm}'
        '</SourceFilename><SourceBand>1</SourceBand></SimpleSource>'
        '<SimpleSource><SourceFilename relativeToVRT="0">{dtm}'
        '</SourceFilename><SourceBand>1</SourceBand></SimpleSource>'
        '</VRTRasterBand></VRTDataset>'
    ).format(
        x=dsm.RasterXSize,
        y=dsm.RasterYSize,
        srs=_xml(dsm.GetProjection()),
        gt=', '.join(repr(v) for v in dsm.GetGeoTransform()),
        dsm=_xml(dsm_path),
        dtm=_xml(dtm_path),
    )
    dsm = None
    gdal.ErrorReset()
    out = gdal.Translate(
        dest,
        gdal.Open(vrt),
        options=gdal.TranslateOptions(
            format=driver,
            creationOptions=_options(driver),
            callback=_callback(on_progress, is_canceled),
        ),
    )
    if out is None:
        _fail('Cannot compute the nDSM', is_canceled)
    out = None


def _xml(text):
    return (
        text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    )


def tag(path, description):
    """Write the attribution into the file, so it travels with the data."""
    ds = gdal.Open(path, gdal.GA_Update)
    if ds is None:
        return
    ds.SetMetadata(TAGS)
    ds.GetRasterBand(1).SetDescription(description)
    ds = None


def has_data(path):
    """Whether the raster has at least one pixel with a value."""
    ds = gdal.Open(path)
    if ds is None:
        return False
    gdal.PushErrorHandler('CPLQuietErrorHandler')
    try:
        low, high = ds.GetRasterBand(1).ComputeRasterMinMax(False)
    except (RuntimeError, TypeError):
        return False
    finally:
        gdal.PopErrorHandler()
    return low == low


def size(path):
    ds = gdal.Open(path)
    return (ds.RasterXSize, ds.RasterYSize) if ds is not None else (0, 0)

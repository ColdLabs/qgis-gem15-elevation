import os
from collections import namedtuple

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFeatureRequest,
    QgsGeometry,
    QgsNetworkAccessManager,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingFeatureSource,
    QgsProcessingParameterCrs,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingUtils,
    QgsRectangle,
    QgsUnitTypes,
)
from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from . import cells, raster
from .style import ATTRIBUTION, product_style

ICON = os.path.join(os.path.dirname(__file__), 'icon.svg')
WGS84 = QgsCoordinateReferenceSystem('EPSG:4326')
LICENCE = 'CC-BY 4.0 (https://creativecommons.org/licenses/by/4.0/)'
DTM, DSM, NDSM = 0, 1, 2


def tr(text):
    return QCoreApplication.translate('Gem15Elevation', text)


Product = namedtuple('Product', 'key output label description')


PRODUCTS = [
    Product('dtm', 'OUTPUT_DTM', 'DTM (bare earth)',
            'GEM-15 DTM, bare-earth elevation (m)'),
    Product('dsm', 'OUTPUT_DSM', 'DSM (surface)',
            'GEM-15 DSM, surface elevation (m)'),
    Product('ndsm', 'OUTPUT_NDSM', 'nDSM (height above ground)',
            'GEM-15 nDSM, DSM minus DTM (m)'),
]


class DownloadElevation(QgsProcessingAlgorithm):
    EXTENT = 'EXTENT'
    AREA = 'AREA'
    PRODUCTS = 'PRODUCTS'
    CRS = 'CRS'
    MAX_AREA_KM2 = 'MAX_AREA_KM2'

    def name(self):
        return 'download'

    def displayName(self):
        return tr('Download elevation')

    def createInstance(self):
        return DownloadElevation()

    def icon(self):
        return QIcon(ICON)

    def shortHelpString(self):
        return tr(
            'Downloads GEM-15 elevation from Google Research for an extent '
            'or the polygons of a layer: 15 m pixels, made from sub-metre '
            'optical stereo imagery acquired up to 2024. Google labels the '
            'dataset experimental.\n\n'
            'DTM: bare-earth elevation. DSM: surface elevation, including '
            'buildings and trees. nDSM: DSM minus DTM, the height of what '
            'stands on the ground.\n\n'
            'Coverage: 60 S to 84 N, except Russia, China, Mongolia, '
            'Greenland and Antarctica. India is offset on purpose, to '
            'comply with Indian geospatial rules. The DTM is less accurate '
            'under dense forest.\n\n'
            'Only the part of each file that covers the area is read, so '
            'nothing is cached. Output: GeoTIFF, in the UTM zone Google uses '
            'for the cell at the area centre unless you set a CRS. In the '
            'cells\' own UTM zone the pixels are kept as they are; elsewhere '
            'they are reprojected (bilinear). The size limit applies to the '
            'bounding box of the area, which the output covers.\n\n'
            'Data: {}. Licence: {}. Keep this credit when you publish maps '
            'or data made with it. This plugin is not affiliated with '
            'Google.'
        ).format(ATTRIBUTION, LICENCE)

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterExtent(
                self.EXTENT, tr('Extent'), optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.AREA,
                tr('Area polygons (overrides the extent)'),
                [QgsProcessing.SourceType.TypeVectorPolygon],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PRODUCTS,
                tr('Products'),
                [tr(p.label) for p in PRODUCTS],
                allowMultiple=True,
                defaultValue=[DTM, DSM, NDSM],
            )
        )
        self.addParameter(
            QgsProcessingParameterCrs(
                self.CRS,
                tr('Output CRS (empty: the UTM zone of the cell at the area '
                   'centre)'),
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_AREA_KM2,
                tr('Stop if the bounding box of the area exceeds (km²)'),
                QgsProcessingParameterNumber.Type.Integer,
                2500,
                minValue=1,
            )
        )
        for p in PRODUCTS:
            self.addParameter(
                QgsProcessingParameterRasterDestination(
                    p.output, tr(p.label), optional=True
                )
            )

    def checkParameterValues(self, parameters, context):
        if not parameters.get(self.AREA) and not parameters.get(self.EXTENT):
            return False, tr('Set an extent or a polygon layer.')
        return super().checkParameterValues(parameters, context)

    def _area(self, parameters, context):
        """The area in EPSG:4326, and whether it is a plain rectangle."""
        source = self.parameterAsSource(parameters, self.AREA, context)
        if source is None:
            geom = self.parameterAsExtentGeometry(
                parameters, self.EXTENT, context, WGS84
            )
            return geom, True
        transform = QgsCoordinateTransform(
            source.sourceCrs(), WGS84, context.transformContext()
        )
        parts = []
        # Repair instead of letting QGIS stop on an invalid polygon: the
        # area only needs to say where to clip.
        for f in source.getFeatures(
            QgsFeatureRequest(),
            QgsProcessingFeatureSource.Flag.FlagSkipGeometryValidityChecks,
        ):
            g = f.geometry()
            if g.isEmpty():
                continue
            g = g.makeValid()
            g.transform(transform)
            if not g.isEmpty():
                parts.append(g)
        if not parts:
            raise QgsProcessingException(tr('The area layer has no polygons.'))
        return QgsGeometry.unaryUnion(parts), False

    def _item(self, cell, feedback):
        """The cell's STAC item, or None where GEM-15 has no data."""
        request = QNetworkRequest(QUrl(cell.item_url))
        reply = QgsNetworkAccessManager.instance().blockingGet(
            request, feedback=feedback
        )
        if feedback.isCanceled():
            raise raster.Canceled()
        status = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        # The bucket answers 404 for a cell it has no file for.
        if status == 404:
            return None
        if reply.error() != QNetworkReply.NetworkError.NoError:
            raise QgsProcessingException(
                tr('Cannot reach the GEM-15 catalogue: {}').format(
                    reply.errorString()
                )
            )
        try:
            return cells.parse_item(bytes(reply.content()).decode('utf-8'))
        except (cells.BadItem, UnicodeDecodeError) as e:
            raise QgsProcessingException(
                tr('Unexpected answer from the GEM-15 catalogue at {}: {}')
                .format(cell.item_url, e)
            )

    def _cells(self, area, feedback):
        """(cell, item) for each cell of the area that has data."""
        bbox = area.boundingBox()
        found = []
        for cell in cells.cells_in_bbox(
            bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum()
        ):
            if feedback.isCanceled():
                raise raster.Canceled()
            outline = QgsGeometry.fromRect(QgsRectangle(*cell.bounds))
            if not outline.intersects(area):
                continue
            item = self._item(cell, feedback)
            if item is None:
                feedback.pushInfo(tr('Cell {}: no data').format(cell.id))
            else:
                feedback.pushInfo(
                    tr('Cell {}: EPSG:{}').format(cell.id, item.epsg)
                )
                found.append((cell, item))
        return found

    def _target_crs(self, parameters, context, area, found):
        """The CRS asked for, or else the UTM zone Google used for the cell
        at the area centre, so its pixels are kept as they are."""
        crs = self.parameterAsCrs(parameters, self.CRS, context)
        if crs.isValid():
            return crs
        c = area.centroid().asPoint()
        epsg = cells.utm_epsg(c.x(), c.y())
        for cell, item in found:
            lon, lat, east, north = cell.bounds
            if lon <= c.x() < east and lat <= c.y() < north:
                epsg = item.epsg
        return QgsCoordinateReferenceSystem('EPSG:{}'.format(epsg))

    def _outputs(self, parameters, context):
        """(product, path) for each chosen product, in PRODUCTS order."""
        chosen = self.parameterAsEnums(parameters, self.PRODUCTS, context)
        if not chosen:
            raise QgsProcessingException(tr('Choose at least one product.'))
        outputs = []
        for n in sorted(set(chosen)):
            p = PRODUCTS[n]
            path = self.parameterAsOutputLayer(parameters, p.output, context)
            if not path:
                raise QgsProcessingException(
                    tr('Set the {} output.').format(tr(p.label))
                )
            if os.path.splitext(path)[1].lower() not in ('.tif', '.tiff'):
                raise QgsProcessingException(
                    tr('Save the {} output as a GeoTIFF (.tif).').format(
                        tr(p.label)
                    )
                )
            outputs.append((p, path))
        return outputs

    def processAlgorithm(self, parameters, context, feedback):
        area, is_rect = self._area(parameters, context)
        outputs = self._outputs(parameters, context)
        max_km2 = self.parameterAsInt(parameters, self.MAX_AREA_KM2, context)

        measure = QgsDistanceArea()
        measure.setSourceCrs(WGS84, context.transformContext())
        measure.setEllipsoid(WGS84.ellipsoidAcronym())
        # The output covers the bounding box of the area, so that is what the
        # limit applies to. Two far-apart polygons, or an area across the 180
        # degree meridian, have a huge one.
        km2 = measure.measureArea(
            QgsGeometry.fromRect(area.boundingBox())
        ) / 1e6
        feedback.pushInfo(tr('Area (bounding box): {:.1f} km²').format(km2))
        if km2 > max_km2:
            raise QgsProcessingException(
                tr(
                    'The bounding box of the area is {:.0f} km², over the {} '
                    'km² limit. Use a smaller area or raise the limit. Areas '
                    'across the 180° meridian are not supported.'
                ).format(km2, max_km2)
            )

        try:
            found = self._cells(area, feedback)
        except raster.Canceled:
            return {}
        if not found:
            raise QgsProcessingException(
                tr(
                    'GEM-15 has no data here. It covers 60 S to 84 N, '
                    'except Russia, China, Mongolia, Greenland and '
                    'Antarctica, and has no cells over open sea.'
                )
            )

        items = [item for cell, item in found]
        crs = self._target_crs(parameters, context, area, found)
        to_target = QgsCoordinateTransform(
            WGS84, crs, context.transformContext()
        )
        bbox = to_target.transformBoundingBox(area.boundingBox())
        bounds = (
            bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum()
        )
        resolution = raster.PIXEL_M * QgsUnitTypes.fromUnitToUnitFactor(
            Qgis.DistanceUnit.Meters, crs.mapUnits()
        )
        cutline = None if is_rect else area.asJson()
        feedback.pushInfo(tr('Output CRS: {}').format(crs.authid()))

        paths = dict((p.key, path) for p, path in outputs)
        # The nDSM is computed from both surfaces, so fetch the ones the user
        # did not ask for into temporary files.
        if 'ndsm' in paths:
            for key in ('dsm', 'dtm'):
                if key not in paths:
                    paths[key] = QgsProcessingUtils.generateTempFilename(
                        'gem15_{}.tif'.format(key), context
                    )
        steps = [key for key in ('dtm', 'dsm', 'ndsm') if key in paths]
        share = 100.0 / len(steps)
        by_key = dict((p.key, p) for p in PRODUCTS)

        for n, key in enumerate(steps):
            path = paths[key]
            base = n * share
            feedback.setProgressText(
                tr('{} ({} of {})').format(
                    tr(by_key[key].label), n + 1, len(steps)
                )
            )

            def on_progress(fraction, base=base):
                feedback.setProgress(base + share * fraction)

            try:
                if key == 'ndsm':
                    raster.difference(
                        paths['dsm'], paths['dtm'], path,
                        on_progress, feedback.isCanceled,
                    )
                else:
                    urls = [
                        i.dtm_url if key == 'dtm' else i.dsm_url
                        for i in items
                    ]
                    raster.clip(
                        urls, path, crs.toWkt(), bounds, resolution,
                        cutline, on_progress, feedback.isCanceled,
                    )
            except raster.Canceled:
                return {}
            except raster.RasterError as e:
                raise QgsProcessingException(str(e))
            raster.tag(path, by_key[key].description)
            width, height = raster.size(path)
            feedback.pushInfo(
                tr('{}: {} x {} pixels').format(
                    tr(by_key[key].label), width, height
                )
            )
            if not raster.has_data(path):
                feedback.pushWarning(
                    tr(
                        '{}: no elevation in this area (open sea or a gap '
                        'in GEM-15). The file is empty.'
                    ).format(tr(by_key[key].label))
                )

        results = {}
        for p, path in outputs:
            results[p.output] = path
            if context.willLoadLayerOnCompletion(path):
                context.layerToLoadOnCompletionDetails(path).setPostProcessor(
                    product_style(p.key)
                )
        feedback.pushInfo(
            tr('Data: GEM-15, {}. Licence: {}.').format(ATTRIBUTION, LICENCE)
        )
        return results

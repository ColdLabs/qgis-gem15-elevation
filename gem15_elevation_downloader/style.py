from qgis.core import (
    QgsBilinearRasterResampler,
    QgsColorRampShader,
    QgsProcessingLayerPostProcessorInterface,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtGui import QColor

ATTRIBUTION = 'This dataset is produced by Google'

# Height above ground in metres. Under 2 m is see-through, so bare ground,
# streets and noise show the map below; then viridis, light for low and dark
# for tall, like the height colours of the sibling building plugins.
NDSM_STOPS = [
    (2, (253, 231, 37, 0), '2 m'),
    (3, (253, 231, 37, 255), '3 m'),
    (6, (94, 201, 98, 255), '6 m'),
    (12, (33, 145, 140, 255), '12 m'),
    (25, (59, 82, 139, 255), '25 m'),
    (50, (68, 1, 84, 255), '50 m'),
]


# Elevation colours from the lowest to the highest value of the layer, as
# shares of that range: greens low, browns high.
ELEVATION_STOPS = [
    (0.0, (0, 104, 55)),
    (0.2, (120, 198, 121)),
    (0.45, (255, 255, 191)),
    (0.7, (216, 162, 91)),
    (1.0, (107, 61, 10)),
]


def _renderer(provider, stops):
    """stops: (value, (r, g, b[, a]), label), lowest first."""
    ramp = QgsColorRampShader(stops[0][0], stops[-1][0])
    ramp.setColorRampType(QgsColorRampShader.Type.Interpolated)
    ramp.setColorRampItemList(
        [
            QgsColorRampShader.ColorRampItem(value, QColor(*rgba), label)
            for value, rgba, label in stops
        ]
    )
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(ramp)
    renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
    renderer.setClassificationMin(stops[0][0])
    renderer.setClassificationMax(stops[-1][0])
    return renderer


def ndsm_renderer(provider):
    return _renderer(provider, NDSM_STOPS)


def elevation_renderer(provider):
    stats = provider.bandStatistics(1)
    low, high = stats.minimumValue, stats.maximumValue
    if not low < high:
        low, high = 0.0, 100.0
    return _renderer(
        provider,
        [
            (
                low + share * (high - low),
                rgb,
                '{:.0f} m'.format(low + share * (high - low)),
            )
            for share, rgb in ELEVATION_STOPS
        ],
    )


class ProductStyle(QgsProcessingLayerPostProcessorInterface):
    def __init__(self, key):
        super().__init__()
        self.key = key

    def postProcessLayer(self, layer, context, feedback):
        provider = layer.dataProvider()
        if self.key == 'ndsm':
            layer.setRenderer(ndsm_renderer(provider))
        else:
            layer.setRenderer(elevation_renderer(provider))
        layer.resampleFilter().setZoomedInResampler(
            QgsBilinearRasterResampler()
        )
        metadata = layer.metadata()
        metadata.setRights([ATTRIBUTION])
        metadata.setLicenses(['CC-BY 4.0'])
        layer.setMetadata(metadata)
        layer.triggerRepaint()


# QGIS takes ownership of a post-processor and deletes it after the run, so
# every output of every run needs a new one. Python still holds each one, or
# the wrapper could be collected before QGIS calls it.
_live = []


def product_style(key):
    style = ProductStyle(key)
    _live.append(style)
    return style

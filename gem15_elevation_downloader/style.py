from qgis.core import (
    QgsColorRampShader,
    QgsHillshadeRenderer,
    QgsProcessingLayerPostProcessorInterface,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtGui import QColor

ATTRIBUTION = 'This dataset is produced by Google'

# Height above ground in metres. Under 1 m is see-through, so bare ground
# shows the map below; then viridis, light for low and dark for tall, like
# the height colours of the sibling building plugins.
NDSM_STOPS = [
    (0, (253, 231, 37, 0), '0 m'),
    (1, (253, 231, 37, 255), '1 m'),
    (6, (94, 201, 98, 255), '6 m'),
    (12, (33, 145, 140, 255), '12 m'),
    (25, (59, 82, 139, 255), '25 m'),
    (50, (68, 1, 84, 255), '50 m'),
]


def ndsm_renderer(provider):
    ramp = QgsColorRampShader(0, 50)
    ramp.setColorRampType(QgsColorRampShader.Type.Interpolated)
    ramp.setColorRampItemList(
        [
            QgsColorRampShader.ColorRampItem(value, QColor(*rgba), label)
            for value, rgba, label in NDSM_STOPS
        ]
    )
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(ramp)
    renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
    renderer.setClassificationMin(0)
    renderer.setClassificationMax(50)
    return renderer


def hillshade_renderer(provider):
    renderer = QgsHillshadeRenderer(provider, 1, 315, 45)
    renderer.setMultiDirectional(True)
    return renderer


class ProductStyle(QgsProcessingLayerPostProcessorInterface):
    def __init__(self, key):
        super().__init__()
        self.key = key

    def postProcessLayer(self, layer, context, feedback):
        provider = layer.dataProvider()
        if self.key == 'ndsm':
            layer.setRenderer(ndsm_renderer(provider))
        else:
            layer.setRenderer(hillshade_renderer(provider))
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

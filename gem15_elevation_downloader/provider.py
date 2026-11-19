import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithm import DownloadElevation


class Provider(QgsProcessingProvider):
    def id(self):
        return 'gem15elevation'

    def name(self):
        return 'GEM-15 Elevation'

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icon.svg'))

    def loadAlgorithms(self):
        self.addAlgorithm(DownloadElevation())

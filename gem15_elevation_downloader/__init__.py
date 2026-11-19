def classFactory(iface):
    from .plugin import Gem15ElevationPlugin

    return Gem15ElevationPlugin(iface)

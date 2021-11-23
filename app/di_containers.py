"""
Контейнеры для инъекции зависимостей в программу.
Позволяют удобно посредством конфигов менять используемые компоненты программы.

Например: вы можете поменять способ распознавания объектов с одного на другой,
никак при этом не редактируя исходный код.
"""
from dependency_injector import containers, providers

from . import video, network


class NetworkContainer(containers.DeclarativeContainer):
    """
    DataInjection-контейнер с обёртками для сетевого взаимодействия.
    """
    config = providers.Configuration()

    _Placeholder = providers.Factory(network.senders.EmptyLoggingApi)

    ApiWrapper = providers.Selector(
        config.using,
        Placeholder=_Placeholder,
    )


class DetectionContainer(containers.DeclarativeContainer):
    """
    DataInjection-контейнер с обёртками для объектов детектирования.
    """
    config = providers.Configuration()

    _BackgroundDetector = providers.Factory(
        video.detectors.Mog2ObjectDetector,
    )

    Detector = providers.Selector(
        config.using,
        Background=_BackgroundDetector,
    )


class TrackingContainer(containers.DeclarativeContainer):
    """
    DataInjection-контейнер с обёртками для объектов трекинга.
    """
    config = providers.Configuration()

    _CentroidTracker = providers.Factory(
        video.trackers.CentroidObjectTracker,
    )

    Tracker = providers.Selector(
        config.using,
        Centroid=_CentroidTracker,
    )


class ApplicationContainer(containers.DeclarativeContainer):
    """
    DataInjection-контейнер.
    Отвечает за инъекцию определённых объектов и классов из конфига.
    """
    config = providers.Configuration()

    network = providers.Container(
        NetworkContainer,
        config=config.network,
    )
    detection = providers.Container(
        DetectionContainer,
        config=config.detection,
    )
    tracking = providers.Container(
        TrackingContainer,
        config=config.tracking,
    )

    get_log_path = config.log_file
    get_log_level = config.log_level
    get_log_format = config.log_format

    get_video_path = config.video_path
    get_video_sizer = config.video_sizer
    get_show_video = config.show_video

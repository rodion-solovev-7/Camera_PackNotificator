"""
Контейнеры для инъекции зависимостей в программу.
Позволяют удобно посредством конфигов менять используемые компоненты программы.

Например: вы можете поменять способ распознавания объектов с одного на другой,
никак при этом не редактируя исходный код.
"""
from dependency_injector import containers, providers

from .components import (
    accessors,
    detectors,
    notifiers,
    validators,
    network_sources,
)


class NetworkSources(containers.DeclarativeContainer):
    """
    Контейнер с обёртками разных сетевых устройств.
    """
    config = providers.Configuration()

    Backend = providers.Singleton(
        network_sources.Backend,
        domain=config.backend.domain,
        timeout_sec=config.backend.timeout_sec,
    )

    Shutter = providers.Singleton(
        network_sources.Shutter,
        domain=config.shutter.domain,
        key=config.shutter.key,
    )

    Sensor = providers.Singleton(
        network_sources.Sensor,
        domain=config.sensor.domain,
        key=config.sensor.key,
    )


class Accessors(containers.DeclarativeContainer):
    """
    Контейнер с обёртками для доступа к актуальным данным бэкенда
    (в перспективе и других ресурсов)
    """
    config = providers.Configuration()

    network = providers.DependenciesContainer()

    _BackendAccessor = providers.Singleton(
        accessors.BackendAccessor,
        backend=network.Backend,
        init_work_mode=config.work_mode,
        init_codes_count=config.codes_count,
    )

    _ImmutableAccessor = providers.Singleton(
        accessors.ImmutableAccessor,
        init_work_mode=config.work_mode,
        init_codes_count=config.codes_count,
    )

    Accessor = providers.Selector(
        config.using,
        Immutable=_ImmutableAccessor,
        Backend=_BackendAccessor,
    )


class Detectors(containers.DeclarativeContainer):
    """
    Контейнер с детекторами пачек.
    """
    config = providers.Configuration()

    network = providers.DependenciesContainer()

    _NeuronetDetector = providers.Singleton(
        detectors.NeuronetDetector,
        model_path=config.Neuronet.model_path,
        threshold_score=config.Neuronet.threshold,
        pooling_period_sec=config.Neuronet.pooling_period_sec,
    )

    _BackgroundDetector = providers.Singleton(
        detectors.BackgroundDetector,
        learning_rate=config.Background.learning_rate,
        threshold_score=config.Background.threshold_score,
    )

    _SensorDetector = providers.Singleton(
        detectors.SensorDetector,
        sensor=network.Sensor,
        pooling_period_sec=config.Sensor.pooling_period_sec,
    )

    Detector = providers.Selector(
        config.using,
        Neuronet=_NeuronetDetector,
        Background=_BackgroundDetector,
        Sensor=_SensorDetector,
    )


class Notifiers(containers.DeclarativeContainer):
    """
    Контейнер с обёртками для оповещения сетевых устройств
    (шторок для сброса, бэкендов).
    """
    config = providers.Configuration()

    network = providers.DependenciesContainer()

    _EmptyLoggingNotifier = providers.Singleton(
        notifiers.EmptyLoggingNotifier,
    )

    _BackendNotifier = providers.Singleton(
        notifiers.BackendNotifier,
        backend=network.Backend,
    )

    _BackendNotifierWithShutter = providers.Singleton(
        notifiers.BackendNotifierWithShutter,
        backend=network.Backend,
        shutter=network.Shutter,
        shutter_wait_before_sec=config.BackendWithShutter.shutter_wait_before_sec,
        shutter_wait_open_sec=config.BackendWithShutter.shutter_wait_open_sec,
        use_shutter_for_bad_packs=config.BackendWithShutter.use_shutter_for_bad_packs,
        use_backend_for_bad_packs=config.BackendWithShutter.use_backend_for_bad_packs,
    )

    Notifier = providers.Selector(
        config.using,
        Backend=_BackendNotifier,
        BackendWithShutter=_BackendNotifierWithShutter,
    )


class Validators(containers.DeclarativeContainer):
    """
    Контейнер с валидаторами для данных с пачек.
    """
    config = providers.Configuration()

    _CodesCountValidator = providers.Singleton(
        validators.CodesCountValidator,
        reject_if_less=config.CodesCount.reject_if_less,
        reject_if_more=config.CodesCount.reject_if_more,
        placeholders_if_reject=config.CodesCount.placeholders_if_reject,
    )

    Validator = providers.Selector(
        config.using,
        CodesCount=_CodesCountValidator,
    )


class Application(containers.DeclarativeContainer):
    """
    DataInjection-контейнер.
    Отвечает за инъекцию определённых объектов и классов из конфига.
    """
    config = providers.Configuration()

    network = providers.Container(
        NetworkSources,
        config=config.devices,
    )

    accessing = providers.Container(
        Accessors,
        config=config.access,
        network=network,
    )

    detection = providers.Container(
        Detectors,
        config=config.detection,
        network=network,
    )

    notification = providers.Container(
        Notifiers,
        config=config.notification,
        network=network,
    )

    validation = providers.Container(
        Validators,
        config=config.validation,
    )

    get_log_path = config.log_file
    get_log_level = config.log_level
    get_log_format = config.log_format

    get_video_path = config.video_path
    get_video_sizer = config.video_sizer
    get_show_video = config.video_show

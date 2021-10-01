from dependency_injector import containers, providers

from .networking import api_wrappers, codes_consolidation
from .scanning import image_loggers
from .scanning.pack_recognition import recognizers


class ScanningContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    _BSPackRecognizer = providers.Factory(
        recognizers.BSPackRecognizer,
        activation_interval=config.recognizing.Background.activation,
        learning_rate=config.recognizing.Background.learning_rate,
        threshold_score=config.recognizing.Background.threshold_score,
        size_multiplier=config.recognizing.Background.sizer,
        region=config.recognizing.Background.region,
    )

    _NeuronetPackRecognizer = providers.Factory(
        recognizers.NeuronetPackRecognizer,
        model_path=config.recognizing.Neuronet.model_path,
        threshold_score=config.recognizing.Neuronet.threshold_score,
    )

    _SensorPackRecognizer = providers.Factory(
        recognizers.SensorPackRecognizer,
        sensor_ip=config.recognizing.Sensor.sensor_ip,
        sensor_key=config.recognizing.Sensor.sensor_const,
        frameskip=config.recognizing.Sensor.skipframes_mod,
    )

    PackRecognizer = providers.Selector(
        config.recognizing.using,
        Background=_BSPackRecognizer,
        Neuronet=_NeuronetPackRecognizer,
        Sensor=_SensorPackRecognizer,
    )

    _FakeImagesSaver = providers.Factory(image_loggers.FakeImagesSaver)
    _ImagesBufferedSaver = providers.Factory(
        image_loggers.ImagesBufferedSaver,
        path=config.images_logging.SaveImages.path,
        buff_size=config.images_logging.SaveImages.buff_size,
        sizer=config.images_logging.SaveImages.sizer,
    )

    ImagesSaver = providers.Selector(
        config.images_logging.using,
        No=_FakeImagesSaver,
        SaveImages=_ImagesBufferedSaver,
    )

    video_path = config.video_path
    show_video = config.show_video
    auto_restart = config.auto_restart


class NetworkingContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    _ApiV1SendCodesAnyway = providers.Factory(
        api_wrappers.ApiV1SendCodesAnyway,
        domain_url=config.commutication.OnlySendCodes.domain,
    )

    _ApiV1WithShutterDrop = providers.Factory(
        api_wrappers.ApiV1WithShutterDrop,
        domain_url=config.commutication.DropAndSendCodes.domain,
        shutter_ip=config.commutication.DropAndSendCodes.shutter_ip,
        shutter_key=config.commutication.DropAndSendCodes.shutter_const,
        shutter_before_time_sec=config.commutication.DropAndSendCodes.shutter_wait_before_sec,
        shutter_open_time_sec=config.commutication.DropAndSendCodes.shutter_wait_open_sec,
    )

    _ApiV1WithShutterDropAndCodesSending = providers.Factory(
        api_wrappers.ApiV1WithShutterDropAndCodesSending,
        domain_url=config.commutication.DropOnly.domain,
        shutter_ip=config.commutication.DropOnly.shutter_ip,
        shutter_key=config.commutication.DropOnly.shutter_const,
        shutter_before_time_sec=config.commutication.DropAndSendCodes.shutter_wait_before_sec,
        shutter_open_time_sec=config.commutication.DropAndSendCodes.shutter_wait_open_sec,
    )

    NetworkApi = providers.Selector(
        config.commutication.using,
        OnlySendCodes=_ApiV1SendCodesAnyway,
        DropAndSendCodes=_ApiV1WithShutterDropAndCodesSending,
        DropOnly=_ApiV1WithShutterDrop,
    )

    _ResultValidator = providers.Factory(codes_consolidation.ResultValidator)

    CodesConsolidator = providers.Selector(
        config.packs_synchronization.using,
        FillPlaceholders=_ResultValidator,
    )

    log_path = config.log_path
    log_level = config.log_level


class ApplicationContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    networking = providers.Container(
        NetworkingContainer,
        config=config.networking,
    )

    scanning = providers.Container(
        ScanningContainer,
        config=config.scanning,
    )

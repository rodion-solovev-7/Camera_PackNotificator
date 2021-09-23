import multiprocessing as mp

from .video_processing import get_events_from_video

__all__ = ['FakeScannerProcess', 'CameraScannerProcess']

from ..di_containers import ApplicationContainer


class FakeScannerProcess(mp.Process):
    """
    Процесс, который делает вид, что читает коды с камер.
    Используется для тестирования.
    """
    def __init__(self, queue: mp.Queue):
        super().__init__(target=self.target, daemon=True, args=(queue, ))

    @classmethod
    def target(cls, queue: mp.Queue):
        from random import randint
        from time import sleep
        print(f'{cls.__name__} started')
        for _ in range(1000):
            queue.put(randint(0, 10))
            sleep(5)


class CameraScannerProcess(mp.Process):
    """
    Процесс - источник событий с камеры.
    Общается с управляющим процессом через ``queue``.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(
            target=self.target,
            args=args,
            kwargs=kwargs,
            daemon=True,
        )

    @staticmethod
    def target(
            queue: mp.Queue,
            worker_id: int,
            *args,
            **kwargs,
    ) -> None:
        """
        Метод для запуска в отдельном процессе.

        Бесконечное читает QR-, штрихкоды с выбранной камеры
        и отправляет их данные базовому процессу через ``queue``.

        Кладёт в ``queue`` следующие события-наследники от ``CamScannerEvent``:

        - В случае ошибок экземпляр ``TaskError`` с информацией об ошибке.
        - В случае успешной обработки экземпляр ``CameraPackResult`` со считанными данными.
        """
        try:
            container = ApplicationContainer()
            container.config.from_yaml('config.yaml')

            video_path = container.scanning.video_path()
            show_video = container.scanning.show_video()
            auto_restart = container.scanning.auto_restart()
            recognizer = container.scanning.PackRecognizer()
            images_logger = container.scanning.ImagesSaver()

            events = get_events_from_video(
                video_url=video_path,
                recognizer=recognizer,
                images_logger=images_logger,
                display_window=show_video,
                auto_reconnect=auto_restart,
            )

            # бесконечный цикл, который получает события от камеры и кладёт их в очередь
            for event in events:
                # отправка события основному процессу
                event.worker_id = worker_id
                queue.put(event)
        except KeyboardInterrupt:
            pass

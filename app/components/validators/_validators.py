import abc
import copy

from loguru import logger


class BaseValidator(metaclass=abc.ABCMeta):
    """
    Базовый класс для валидаторов пачек.
    """

    @abc.abstractmethod
    def get_validated(self, pack_data: dict) -> dict:
        """
        Изменяет данные пачки чтобы они соответствовали критерию этого валидатора.
        Устанавливает аттрибут is_correct, указывающий на (не)валидность пачки.
        """


class CodesCountValidator(BaseValidator):
    """
    Валидатор пачки по считанным с неё кодам.
    """

    QR_CODE = 'QRCODE'
    BARCODE = 'EAN13'

    blacklisted_qrs = ['xps.tn.ru']

    def __init__(
            self,
            *,
            reject_if_less: bool = True,
            reject_if_more: bool = True,
            replace_empty_if_reject: bool = True,
    ):
        self._reject_if_less = reject_if_less
        self._reject_if_more = reject_if_more
        self._replace_if_reject = replace_empty_if_reject

    def get_validated(self, pack_data: dict) -> dict:
        """
        Удаляет из данных пачки пары с запрещёнными QR-кодами и
        валидирует пачку по кол-ву ожидаемых и найденных кодов.
        """
        logger.info(f"Получены данные пачки для валидации: {pack_data}")

        pack_data = copy.deepcopy(pack_data)

        pack_data['QRCODE'] = self._get_non_blacklisted_qr_codes(pack_data['QRCODE'])
        while len(pack_data['EAN13']) > len(pack_data['QRCODE']):
            pack_data['EAN13'].pop()

        expected_count = pack_data['expected']
        actual_count = len(pack_data['QRCODE'])

        pack_data['is_valid'] = self._is_correct_codes_count(actual_count, expected_count)
        if pack_data['is_valid']:
            logger.info(f"Пачка {pack_data} помечена корректной")
        else:
            logger.info(f"Пачка {pack_data} помечена НЕкорректной")
            if self._replace_if_reject:
                logger.info("Некорректная пачка заменена пустой")
                pack_data = self._get_empty_pack(expected_count)

        return pack_data

    def _get_non_blacklisted_qr_codes(self, qrs: list[str]):
        """
        Удаляет пары кодов, среди которых найдены запрещённые.
        """
        new_qrs = []
        for qr_code in qrs:

            is_ignored = False
            for blacklisted in self.blacklisted_qrs:
                if blacklisted in qr_code:
                    logger.info(f"Код '{qr_code}' был удалён из пачки, "
                                "т.к. находится в чёрном списке")
                    is_ignored = True
                    break

            if not is_ignored:
                new_qrs.append(qr_code)
        return new_qrs

    def _is_correct_codes_count(self, actual_count: int, expected_count: int) -> bool:
        """
        Проверяет, соответствует ли кол-во кодов ожидаемому.
        """
        if actual_count > expected_count:
            logger.info("Количество кодов больше ожидаемого "
                        f"({actual_count} > {expected_count})")
            if self._reject_if_more:
                return False

        if actual_count < expected_count:
            logger.info(f"Количество кодов меньше ожидаемого "
                        f"({actual_count} < {expected_count})")
            if self._reject_if_less:
                return False

        return True

    @staticmethod
    def _get_empty_pack(expected: int) -> dict:
        """
        Создаёт пустую пачку.
        """
        return dict(
            QRCODE=[''] * expected,
            EAN13=['0' * 13] * expected,
            is_valid=False,
            expected=expected,
        )


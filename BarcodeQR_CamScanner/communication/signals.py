"""
Функции для отправки результатов работы
программам извне и получению информации от них.
"""
from json import JSONDecodeError
from time import sleep
from typing import List, Optional

import requests
from loguru import logger
from requests.exceptions import RequestException

from . import _snmp_commands

REQUEST_TIMEOUT_SEC = 2
SHUTTER_OPEN_TIME_SEC = 16


def _shutter_task() -> None:
    """Сбрасывает бракованную пачку с конвейера"""
    global SHUTTER_OPEN_TIME_SEC
    send_shutter_down()
    sleep(SHUTTER_OPEN_TIME_SEC)
    send_shutter_up()


def send_shutter_down() -> None:
    """Опускает шторку для начала сброса пачек"""
    try:
        _snmp_commands.snmp_set(_snmp_commands.OID['ALARM-1'], _snmp_commands.on)
    except Exception:
        logger.error("Ошибка при отправлении запроса на опускание шторки")


def send_shutter_up() -> None:
    """Поднимает шторку для прекращения сброса пачек"""
    try:
        _snmp_commands.snmp_set(_snmp_commands.OID['ALARM-1'], _snmp_commands.off)
    except Exception:
        logger.error("Ошибка при отправлении запроса на поднятие шторки")


def notify_about_packdata(
        domain_url: str,
        qr_codes: List[str],
        barcodes: List[str],
) -> None:
    """
    Оповещает сервер, что QR- и штрихкоды успешно считаны с пачки.
    Считанные данные также отправляются серверу.
    """
    global REQUEST_TIMEOUT_SEC
    success_pack_mapping = f'{domain_url}/api/v1_0/new_pack_after_pintset'

    logger.debug(f"Отправка данных пачки на сервер: QR-коды: {qr_codes} штрих-коды: {barcodes}")

    for qr_code, barcode in zip(qr_codes, barcodes):
        send_data = {
            'qr': qr_code,
            'barcode': barcode,
        }

        try:
            response = requests.put(success_pack_mapping, json=send_data, timeout=REQUEST_TIMEOUT_SEC)
            response.raise_for_status()
        except RequestException as e:
            logger.error("Ошибка при попытке отправки кодов на сервер")
            logger.opt(exception=e)


def get_work_mode(domain_url: str) -> Optional[str]:
    """
    Получает режим работы (в оригинале "записи"!?) с сервера.
    """
    global REQUEST_TIMEOUT_SEC
    wmode_mapping = f'{domain_url}/api/v1_0/get_mode'

    logger.debug("Получение данных о текущем режиме записи")
    try:
        response = requests.get(wmode_mapping, timeout=REQUEST_TIMEOUT_SEC)
        response.raise_for_status()
    except RequestException as e:
        logger.error("Ошибка при попытке получить режим работы с сервера")
        logger.opt(exception=e)
        return None

    try:
        work_mode = response.json()['work_mode']
    except (JSONDecodeError, KeyError) as e:
        logger.error("Ошибка при попытке получить режим работы с сервера")
        logger.opt(exception=e)
        return None

    return work_mode


def get_pack_codes_count(domain_url: str) -> Optional[int]:
    """
    Узнаёт от сервера, сколько QR-кодов ожидать на одной пачке
    """
    global REQUEST_TIMEOUT_SEC
    qr_count_mapping = f'{domain_url}/api/v1_0/current_batch'

    logger.debug("Получение данных об ожидаемом кол-ве QR-кодов")
    try:
        response = requests.get(qr_count_mapping, timeout=REQUEST_TIMEOUT_SEC)
        response.raise_for_status()
    except RequestException as e:
        logger.error("Ошибка при попытке получить от сервера ожидаемое кол-во пачек")
        logger.opt(exception=e)
        return None

    try:
        data = response.json()
    except JSONDecodeError as e:
        logger.error("Ошибка при декодировании JSON-ответа с ожидаемым кол-вом пачек")
        logger.opt(exception=e)
        return None

    packs_in_block = data.get('params', {}).get('multipacks_after_pintset', None)
    if packs_in_block is None:
        logger.error("Ошибка при извлечении из JSON ответа с ожидаемым кол-вом пачек")
        return None
    return int(packs_in_block)

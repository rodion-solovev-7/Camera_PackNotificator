"""
Обёртки для всех сетевых взаимодействий программы.
Инкапсулируют в себе обращения к разным устройствам и
обращения к разным источникам: бэкенду, шторке и другим.
"""
import abc
import asyncio
import time
from abc import ABCMeta
from typing import Optional

import aiohttp
import pysnmp.hlapi as snmp
from loguru import logger

from ..models import PackGoodCodes, PackBadCodes
from ..scanning.code_reading import CodeType


class BaseNetworkingApi(metaclass=abc.ABCMeta):
    """
    Базовый класс для всех обёрток над API.
    """

    @abc.abstractmethod
    async def notify_about_good_pack(self, pack: PackGoodCodes) -> None:
        """Уведомить, что прошла пачка с указанными кодами"""

    @abc.abstractmethod
    async def notify_about_bad_pack(self, pack: PackBadCodes) -> None:
        """Уведомить, что прошла некорректная пачка"""

    @abc.abstractmethod
    async def get_workmode(self) -> Optional[str]:
        """Получить текущий режим работы системы"""

    @abc.abstractmethod
    async def get_expected_codes_count(self) -> Optional[int]:
        """Получить текущее ожидаемое кол-во кодов"""


class BaseApiV1(BaseNetworkingApi, metaclass=ABCMeta):
    """
    Верхоуровневая обёртка над V1 версией API бэкенда.

    Поддерживает отправку запросов о:
        - прочитанных кодах
        - некорректных пачках
        - получения ожидаемого количества кодов
        - получения текущего режима обработки
    """
    _REQUEST_TIMEOUT_SEC: float
    _domain_url: str

    def __init__(self, domain_url: str, *, request_timeout_sec: float = 2):
        self._domain_url = domain_url
        self._REQUEST_TIMEOUT_SEC = request_timeout_sec

    async def notify_about_good_pack(self, pack: PackGoodCodes) -> None:
        """
        Оповещает сервер о корректной пачке

        (Отправляет корректные коды бэкенду)
        """
        for codes in pack.codepairs:
            await self._send_codepair(codes[CodeType.QR_CODE], codes[CodeType.BARCODE])

    @abc.abstractmethod
    async def notify_about_bad_pack(self, pack: PackBadCodes) -> None:
        """
        Оповещает сервер о некорректной пачке
        """

    async def get_workmode(self) -> Optional[str]:
        """
        Получает режим работы с сервера.

        Returns:
            "auto" или "manual" в случае успешного получения,
                либо `None` в случае ошибок.
        """
        workmode_mapping = f'{self._domain_url}/api/v1_0/get_mode'

        logger.debug('Получение данных о текущем режиме записи')
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                        url=workmode_mapping,
                        timeout=self._REQUEST_TIMEOUT_SEC
                ) as resp:
                    json_data = await resp.json()
            workmode = str(json_data['work_mode'])
            return workmode
        except Exception as e:
            logger.error("Ошибка при попытке получить режим работы с сервера")
            logger.opt(exception=e)

    async def get_expected_codes_count(self) -> Optional[int]:
        """
        Узнаёт от сервера, сколько QR-кодов ожидать на одной пачке.

        Returns:
            натуральное число (кол-во кодов) в случае успешного получения,
                либо `None` в случае ошибок.
        """
        qr_count_mapping = f'{self._domain_url}/api/v1_0/current_batch'

        logger.debug("Получение данных об ожидаемом кол-ве QR-кодов")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                        url=qr_count_mapping,
                        timeout=self._REQUEST_TIMEOUT_SEC
                ) as resp:
                    json_data = await resp.json()
            packs_in_block = int(json_data['params']['multipacks_after_pintset'])
            return packs_in_block
        except Exception as e:
            logger.error("Ошибка при попытке получить от сервера ожидаемое кол-во пачек")
            logger.opt(exception=e)

    async def _send_codepair(self, qr_code: str, barcode: str) -> None:
        """
        Отправляет пару из QR- и штрихкода на сервер.
        """
        success_pack_mapping = f'{self._domain_url}/api/v1_0/new_pack_after_pintset'

        logger.debug("Отправка пары кодов на сервер: "
                     f"QR-код: {qr_code} штрих-код: {barcode}")

        json4send = {
            'qr': qr_code,
            'barcode': barcode,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                        url=success_pack_mapping,
                        json=json4send,
                        timeout=self._REQUEST_TIMEOUT_SEC,
                ):
                    pass
        except Exception as e:
            logger.error("Ошибка при попытке отправки пары кодов на сервер")
            logger.opt(exception=e)


class BaseApiV1WithShutter(BaseApiV1, metaclass=ABCMeta):
    # TODO: переписать smnp запросы на асинхронные.
    #  Для этого посмотреть в сторону pysnmp.hlapi.asyncio
    SHUTTER_BEFORE_TIME_SEC: float
    SHUTTER_OPEN_TIME_SEC: float
    SHUTTER_PORT = 161
    SHUTTER_ON = snmp.Integer(1)
    SHUTTER_OFF = snmp.Integer(0)

    # TODO: выяснить что это за ... - переименовать и задокументировать
    OID = {
        'ALARM-1': '.1.3.6.1.4.1.40418.2.6.2.2.1.3.1.2',
        'ALARM-2': '.1.3.6.1.4.1.40418.2.6.2.2.1.3.1.3',
        'ALARM-3': '.1.3.6.1.4.1.40418.2.6.2.2.1.3.1.4',
        'ALARM-4': '.1.3.6.1.4.1.40418.2.6.2.2.1.3.1.5',
    }

    def __init__(
            self,
            shutter_ip: str,
            *args,
            shutter_before_time_sec: float = 8,
            shutter_open_time_sec: float = 25,
            **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.shutter_ip = shutter_ip
        self.SHUTTER_BEFORE_TIME_SEC = shutter_before_time_sec
        self.SHUTTER_OPEN_TIME_SEC = shutter_open_time_sec

        self.snmp_community_string = 'public'
        self.snmp_engine = snmp.SnmpEngine()

        self.is_shutter_open = False
        self.shutter_close_time = time.monotonic()

    async def _drop_pack(self) -> None:
        """
        Асинхронно ждёт, открывает сброс пачёк и через некоторое время закрывает его.
        Если ещё до закрытия заслонки на сброс была отправлена
        новая группа пачек, то заслонка остаётся в открытом состоянии.
        """
        awake_time = self.SHUTTER_BEFORE_TIME_SEC + self.SHUTTER_OPEN_TIME_SEC
        self.shutter_close_time = time.monotonic() + awake_time
        await asyncio.sleep(self.SHUTTER_BEFORE_TIME_SEC)
        if not self.is_shutter_open:
            logger.info("Открыта заслонка - начало сброса пачек")
            self.is_shutter_open = True
            self._send_shutter_open()
        await asyncio.sleep(self.SHUTTER_OPEN_TIME_SEC)
        if self.is_shutter_open and time.monotonic() > self.shutter_close_time - 1e-3:
            self.is_shutter_open = False
            logger.info("Закрыта заслонка - окончание сброса пачек")
            self._send_shutter_close()

    def _send_shutter_open(self) -> None:
        """
        Отправляет запрос на опускание заслонки - начало сброса бракованных пачек.
        """
        logger.debug("Запрос на открытие сброса")
        try:
            key_object = snmp.ObjectIdentity(self.OID['ALARM-1'])
            value = self.SHUTTER_ON
            snmp.setCmd(
                self.snmp_engine,
                snmp.CommunityData(self.snmp_community_string),
                snmp.UdpTransportTarget((self.shutter_ip, self.SHUTTER_PORT)),
                snmp.ContextData(),
                snmp.ObjectType(key_object, value),
            )
        except Exception as e:
            logger.error("Ошибка при отправлении запроса на опускание шторки")
            logger.opt(exception=e)

    def _send_shutter_close(self) -> None:
        """
        Отправляет запрос на поднятие заслонки - прекращение сброса пачек.
        """
        logger.debug("Запрос на закрытие сброса")
        try:
            key_object = snmp.ObjectIdentity(self.OID['ALARM-1'])
            value = self.SHUTTER_OFF
            snmp.setCmd(
                self.snmp_engine,
                snmp.CommunityData(self.snmp_community_string),
                snmp.UdpTransportTarget((self.shutter_ip, self.SHUTTER_PORT)),
                snmp.ContextData(),
                snmp.ObjectType(key_object, value),
            )
        except Exception as e:
            logger.error("Ошибка при отправлении запроса на поднятие шторки")
            logger.opt(exception=e)


class ApiV1SendCodesAnyway(BaseApiV1):
    """
    Версия API-обёртки для случаев, где сам бэкенд занимается сбросом плохих пачек.

    (Необходимо чтобы среди кодов был хотя бы 1 код-заглушка)
    """
    async def notify_about_bad_pack(self, pack: PackBadCodes) -> None:
        """
        Отправляет некорректные коды бэкенду в надежде, что он их сбросит сам
        """
        for codes in pack.codepairs:
            await self._send_codepair(codes[CodeType.QR_CODE], codes[CodeType.BARCODE])


class ApiV1WithShutterDrop(BaseApiV1WithShutter):
    """
    Версия API, которая ставит сбрасывает некорректные пачки заслонкой, не извещая о них бэкенд.
    """
    async def notify_about_bad_pack(self, pack: PackBadCodes) -> None:
        """
        Сбрасывает пачки заслонкой, не извещая о них сервер
        """
        await self._drop_pack()


class ApiV1WithShutterDropAndCodesSending(BaseApiV1WithShutter):
    """
    Версия API, которая ставит коды некорректных пачек в очередь и сбрасывает эти пачки заслонкой.

    (Необходимо чтобы среди кодов был хотя бы 1 код-заглушка)
    """
    async def notify_about_bad_pack(self, pack: PackBadCodes) -> None:
        """
        Отправляет некорректные коды бэкенду и сбрасывает пачки заслонкой
        """
        for codes in pack.codepairs:
            await self._send_codepair(codes[CodeType.QR_CODE], codes[CodeType.BARCODE])
        await self._drop_pack()

from typing import Optional

import aiohttp
import pysnmp.hlapi.asyncio as snmp
from loguru import logger


class Backend:
    """
    Обёртка для связи с бэкендом.
    Позволяет получать ожидаемое кол-во QR кодов и отправлять данные о считанных с пачек кодах.
    """

    def __init__(self, domain: str, *, timeout_sec: float = 2):
        self._domain = domain

        self._TIMEOUT_SEC = timeout_sec

    async def get_mode(self) -> Optional[str]:
        """
        Получает режим работы с сервера.

        Returns:
            "auto" или "manual" в случае успешного получения,
                либо `None` в случае ошибок.
        """
        workmode_mapping = f'http://{self._domain}/api/v1_0/get_mode'

        logger.debug('Получение данных о текущем режиме записи')
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(workmode_mapping, timeout=self._TIMEOUT_SEC) as resp:
                    logger.debug(f"Статус ответа: {resp.status}")
                    json_data = await resp.json()
                    logger.debug(f"JSON из ответа: {json_data}")
            workmode = str(json_data['work_mode'])
            logger.debug(f"Полученный режим работы: {workmode}")
            return workmode
        except Exception as e:
            logger.opt(exception=e).error("Ошибка при попытке получить режим работы с сервера")

    async def get_multipacks_after_pintset(self) -> Optional[int]:
        """
        Узнаёт от сервера, сколько QR-кодов ожидать на одной пачке.

        Returns:
            натуральное число (кол-во кодов) в случае успешного получения,
                либо `None` в случае ошибок.
        """
        qr_count_mapping = f'http://{self._domain}/api/v1_0/current_batch'

        logger.debug("Получение данных об ожидаемом кол-ве QR-кодов")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(qr_count_mapping, timeout=self._TIMEOUT_SEC) as resp:
                    logger.debug(f"Статус ответа: {resp.status}")
                    json_data = await resp.json()
                    logger.debug(f"JSON из ответа: {json_data}")
            packs_in_block = int(json_data['params']['multipacks_after_pintset'])
            logger.debug(f"Полученное кол-во кодов: {packs_in_block}")
            return packs_in_block
        except Exception as e:
            logger.opt(exception=e).error("Ошибка при попытке получить от сервера ожидаемое кол-во пачек")

    async def send_codepair(
            self,
            qr_code: str,
            barcode: str,
    ) -> None:
        """
        Отправляет пару из QR- и штрихкода на сервер.
        """
        success_pack_mapping = f'http://{self._domain}/api/v1_0/new_pack_after_pintset'

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
                        timeout=self._TIMEOUT_SEC,
                ) as resp:
                    logger.debug(f"Статус ответа: {resp.status}")
                    json_data = await resp.json()
                    logger.debug(f"JSON из ответа: {json_data}")
        except Exception as e:
            logger.opt(exception=e).error("Ошибка при попытке отправки пары кодов на сервер")


class Shutter:
    """
    Обёртка над контроллером, который отвечает за сброс пачек с конвейера.
    """

    def __init__(
            self,
            domain: str,
            key: str,
            port: int = 161,
            *,
            engine: snmp.SnmpEngine = None,
    ):
        if engine is None:
            engine = snmp.SnmpEngine()

        self._engine = engine
        self._transport = snmp.UdpTransportTarget((domain, port))
        self._identity = snmp.ObjectIdentity(key)

        self._CLOSE = snmp.Integer(0)
        self._OPEN = snmp.Integer(1)

    async def open(self):
        """
        Отправляет запрос на открытие сброса
        """
        logger.info("Запрос на открытие сброса")
        logger.debug(f"SNMP SET TARGET={self._transport} OBJECT={self._identity}")
        try:
            errorIndication, errorStatus, errorIndex, varBinds = await snmp.setCmd(
                self._engine,
                snmp.CommunityData('public'),
                self._transport,
                snmp.ContextData(),
                snmp.ObjectType(self._identity, self._OPEN),
            )

            if errorIndication:
                logger.error("Ошибка при попытке отправить запрос на открытие сброса: "
                             f"{errorStatus=} {errorIndex=}")
            logger.debug(f"SNMP SET RESULTS: {varBinds=}")

        except Exception as e:
            logger.opt(exception=e).error("Ошибка при попытке отправить запрос на открытие сброса")

    async def close(self):
        """
        Отправляет запрос на закрытие сброса
        """
        logger.info("Запрос на закрытие сброса")
        logger.debug(f"SNMP SET TARGET={self._transport} OBJECT={self._identity}")
        try:
            errorIndication, errorStatus, errorIndex, varBinds = await snmp.setCmd(
                self._engine,
                snmp.CommunityData('public'),
                self._transport,
                snmp.ContextData(),
                snmp.ObjectType(self._identity, self._CLOSE),
            )

            if errorIndication:
                logger.error("Ошибка при попытке отправить запрос на закрытие сброса "
                             f"{errorStatus=} {errorIndex=}")
            logger.debug(f"SNMP SET RESULTS: {varBinds=}")

        except Exception as e:
            logger.opt(exception=e).error("Ошибка при попытке отправить запрос на закрытие сброса")


class Sensor:
    """
    Обертка для связи с датчиком расстояния.
    Позволяет определять, находится ли пачка перед датчиком.
    """

    def __init__(
            self,
            domain: str,
            key: str,
            port: int = 161,
            *,
            engine: snmp.SnmpEngine = None,
    ):
        if engine is None:
            engine = snmp.SnmpEngine()

        self._engine = engine
        self._transport = snmp.UdpTransportTarget((domain, port))
        self._identity = snmp.ObjectIdentity(key)

        self._CLOSE = snmp.Integer(0)
        self._OPEN = snmp.Integer(1)

    async def get_sensor_status(self) -> Optional[bool]:
        """
        Возвращает статус от датчика расстояния.

        Returns:
            True: датчик обнаружил объект
            False: датчик не обнаружил ничего
            None: произошла ошибка в процессе получения данных
        """
        logger.info("Запрос к состоянию сенсора")
        logger.debug(f"SNMP GET TARGET={self._transport}")
        try:
            errorIndication, errorStatus, errorIndex, varBinds = await snmp.getCmd(
                self._engine,
                snmp.CommunityData('public'),
                self._transport,
                snmp.ContextData(),
                snmp.ObjectType(self._identity),
            )
            if errorIndication:
                logger.error("Ошибка при попытке получить состояние сенсора "
                             f"{errorStatus=} {errorIndex=} {varBinds=}")
                return None

            logger.debug(f"SNMP GET RESULTS: {varBinds=}")
            name, val = varBinds[0]
            return int(val.prettyPrint()) != 0
        except Exception as e:
            logger.opt(exception=e).error("Ошибка при попытке получить состояние сенсора")

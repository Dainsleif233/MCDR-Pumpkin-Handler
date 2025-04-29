import functools
import json
import re
import time
from abc import ABC
from typing import Optional, List

import parse
from typing_extensions import override

from mcdreforged.handler.abstract_server_handler import AbstractServerHandler
from mcdreforged.info_reactor.info import InfoSource, Info
from mcdreforged.info_reactor.server_information import ServerInformation
from mcdreforged.minecraft.rtext.text import RTextBase
from mcdreforged.utils import string_utils
from mcdreforged.utils.types.message import MessageText

class PumpkinHandler(AbstractServerHandler, ABC):
    """
    A handler for Pumpkin Minecraft servers
    """
    @override
    def get_name(self) -> str:
        return 'pumpkin_handler'
    
    @override
    def get_stop_command(self) -> str:
        return 'stop'
    
    @classmethod
    @override
    def get_content_parsing_formatter(cls) -> re.Pattern:
        return re.compile(r'\[(?P<logging>[^]]+)\](?: \((\d+)\))? (?P<content>.*)')
    
    @classmethod
    @functools.lru_cache()
    def __get_content_parsers(cls) -> List[re.Pattern]:
        formatters = cls.get_content_parsing_formatter()
        if isinstance(formatters, str) or isinstance(formatters, re.Pattern):
            formatters = [formatters]
        return [parse.Parser(fmt) if isinstance(fmt, str) else fmt for fmt in formatters]

    @override
    def _content_parse(cls, info: Info):
        for parser in cls.__get_content_parsers():
            if isinstance(parser, parse.Parser):
                parsed = parser.parse(info.content)
            else:
                parsed = parser.fullmatch(info.content)
            if parsed is not None:
                break
        else:
            raise ValueError('Unrecognized input: ' + info.content)
        t = time.localtime(time.time())
        info.hour = t.tm_hour
        info.min = t.tm_min
        info.sec = t.tm_sec
        info.logging_level = parsed['logging']
        info.content = parsed['content']

    @classmethod
    def get_player_message_parsing_formatter(cls) -> List[re.Pattern]:
        return [
            re.compile(r'\<chat\> (?P<name>[^:]+): (?P<message>.*)')
        ]

    @classmethod
    @functools.lru_cache()
    def __get_player_message_parsers(cls) -> List[re.Pattern]:
        formatters = cls.get_player_message_parsing_formatter()
        return [parse.Parser(fmt) if isinstance(fmt, str) else fmt for fmt in formatters]

    @classmethod
    def format_message(cls, message: MessageText) -> str:
        if isinstance(message, RTextBase):
            return message.to_json_str()
        else:
            return json.dumps(str(message), ensure_ascii=False, separators=(',', ':'))

    @override
    def get_send_message_command(self, target: str, message: MessageText, server_information: ServerInformation) -> Optional[str]:
        return 'tellraw {} {}'.format(target, self.format_message(message))

    @override
    def get_broadcast_message_command(self, message: MessageText, server_information: ServerInformation) -> Optional[str]:
        return self.get_send_message_command('@a', message, server_information)

    @classmethod
    @override
    def _get_server_stdout_raw_result(cls, text: str) -> Info:
        if type(text) is not str:
            raise TypeError('The text to parse should be a string')
        raw_result = Info(InfoSource.SERVER, text)
        raw_result.content = string_utils.clean_console_color_code(text)
        raw_result.hour = 0
        raw_result.min = 0
        raw_result.sec = 0
        return raw_result

    __player_name_regex = re.compile(r'[a-zA-Z0-9_]{3,16}')

    @classmethod
    def _verify_player_name(cls, name: str):
        return cls.__player_name_regex.fullmatch(name) is not None

    @override
    def parse_server_stdout(self, text: str):
        result = super().parse_server_stdout(text)

        for parser in self.__get_player_message_parsers():
            if isinstance(parser, parse.Parser):
                parsed = parser.parse(result.content)
            else:
                parsed = parser.fullmatch(result.content)
            if parsed is not None and self._verify_player_name(parsed['name']):
                result.player, result.content = parsed['name'], parsed['message']
                break

        return result

    __player_joined_regex = re.compile(r'(?P<name>[^ ]+) joined the game')

    @override
    def parse_player_joined(self, info: Info):
        if not info.is_user:
            if (m := self.__player_joined_regex.fullmatch(info.content)) is not None:
                if self._verify_player_name(m['name']):
                    return m['name']
        return None

    __player_left_regex = re.compile(r'(?P<name>[^ ]+) left the game')

    @override
    def parse_player_left(self, info: Info):
        if not info.is_user:
            if (m := self.__player_left_regex.fullmatch(info.content)) is not None:
                if self._verify_player_name(m['name']):
                    return m['name']
        return None

    __server_version_regex = re.compile(r'Starting Pumpkin ([^ ]+) \([a-z0-9_]{8}\) for Minecraft (?P<version>.+) \(Protocol (d+)\)')

    @override
    def parse_server_version(self, info: Info):
        if not info.is_user:
            if (m := self.__server_version_regex.fullmatch(info.content)) is not None:
                return m['version']
        return None

    __server_address_regex = re.compile(r'You now can connect to the server; listening on (?P<ip>\S+):(?P<port>\d+)')

    @override
    def parse_server_address(self, info: Info):
        if not info.is_user:
            if (m := self.__server_address_regex.fullmatch(info.content)) is not None:
                return m['ip'], int(m['port'])
        return None

    @override
    def test_server_startup_done(self, info: Info):
        return info.is_from_server and self.__server_address_regex.fullmatch(info.content) is not None

    __rcon_started_regex = re.compile(r'RCON running on [\w.]+:\d+')

    @override
    def test_rcon_started(self, info: Info):
        return info.is_from_server and self.__rcon_started_regex.fullmatch(info.content) is not None

    __server_stopping_regex = re.compile(r'Stopping the server')

    @override
    def test_server_stopping(self, info: Info):
        return info.is_from_server and self.__server_stopping_regex.fullmatch(info.content) is not None

def on_load(server, prev_module):

    server.register_server_handler(PumpkinHandler())
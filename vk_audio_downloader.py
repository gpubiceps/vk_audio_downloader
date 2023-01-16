import os
import time
from typing import List, Tuple

import requests
import vk_api
from vk_api import audio
import m3u8
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from asyncio import Semaphore, gather, run, wait_for
from aiohttp.client import ClientSession


REQUEST_STATUS_CODE = 200
DEFAULT_SAVE_DIR = "music/"
TEMP_AUDIO_FILE_NAME = "temp.ts"
MAX_TASKS = 10
MAX_TIME = 100


class MusicDownloader:
    def __init__(self, login: str, password: str, save_dir: str = None):
        self._vk_session = vk_api.VkApi(login=login,
                                        password=password)
        self._vk_session.auth()
        self._vk_audio = audio.VkAudio(self._vk_session)
        self.save_dir = save_dir or DEFAULT_SAVE_DIR
        self.temp_file_path = f"{self.save_dir}/{TEMP_AUDIO_FILE_NAME}"

    def download_audio_by_id(self, owner_id: int, audio_id: int, convert_to_mp3: bool = False, verbose: bool = False):
        """Скачивает аудио по id трека

        Params
        ------
        owner_id: ID владельца (отрицательные значения для групп)
        audio_id: ID аудио
        verbose: Вывод времени выполнения
        """
        if verbose:
            start = time.time()

        os.makedirs(self.save_dir, exist_ok=True)

        m3u8_data, m3u8_url, meta_info = self._get_m3u8_by_id(owner_id, audio_id)
        parsed_m3u8 = self._parse_m3u8(m3u8_data)
        segments_binary_data = self._get_audio_from_m3u8(parsed_m3u8=parsed_m3u8, m3u8_url=m3u8_url)

        audio_name = f"{owner_id}_{audio_id}"
        if convert_to_mp3:
            self._write_to_mp3(segments_binary_data, name=audio_name)
        else:
            audio_path = f"{self.save_dir}/{audio_name}.ts"
            self._write_to_file(segments_binary_data, path=audio_path)

        if verbose:
            print(f"{audio_name} saved in {time.time() - start} sec")

    def _get_m3u8_by_id(self, owner_id: int, audio_id: int) -> Tuple:
        """
        Params
        ------
        owner_id: ID владельца (отрицательные значения для групп)
        audio_id: ID аудио

        Returns
        -------
        data: сожержимое m3u8 файла
        url: сылка на m3u8 файл
        meta_info: Dict['artist': str, 'title': str]
        """
        audio_info = self._vk_audio.get_audio_by_id(owner_id=owner_id, audio_id=audio_id)
        url = audio_info.get("url")
        data = m3u8.load(uri=url)
        meta_info = {
            "artist": audio_info.get("artist"),
            "title": audio_info.get("title"),
            "duration": audio_info.get("duration"),
        }
        return data, url, meta_info

    @staticmethod
    def _parse_m3u8(m3u8_data):
        """Возвращает информацию о сегментах"""
        parsed_data = []
        segments = m3u8_data.data.get("segments")
        for segment in segments:
            temp = {"name": segment.get("uri")}

            if segment["key"]["method"] == "AES-128":
                temp["key_uri"] = segment["key"]["uri"]
            else:
                temp["key_uri"] = None

            parsed_data.append(temp)
        return parsed_data

    @staticmethod
    def _download_content(url: str) -> bytes:
        response = requests.get(url=url)
        return response.content if response.status_code == REQUEST_STATUS_CODE else None

    
    def _get_audio_from_m3u8(self, parsed_m3u8: list, m3u8_url: str) -> bytes:
        """Асинхронно скачивает сегменты и собирает их в одну байт-строку"""
        downloaded_chunks = [None] * len(parsed_m3u8) # to keep chunks order
        semaphore = Semaphore(MAX_TASKS)

        async def download():
            tasks = []
            async with ClientSession() as session:
                for index, segment in enumerate(parsed_m3u8):
                    tasks.append(
                            wait_for(
                                handle_segment(segment, index, session),
                                timeout=MAX_TIME
                                )
                            )
                return await gather(*tasks)

        async def handle_segment(segment: dict, segment_index: int, session: ClientSession) -> None:
            segment_uri = m3u8_url.replace("index.m3u8", segment["name"])
            content = await download_chunk(segment_uri, session)
            if segment["key_uri"] is not None:
                key = await download_chunk(segment["key_uri"], session)
                content = await decode_aes_128(data=content, key=key)

        async def download_chunk(url: str, session: ClientSession) -> bytes:
            async with semaphore:
                async with session.get(url) as res:
                    content = await res.read()
                    return content if res.status == REQUEST_STATUS_CODE else None

        async def decode_aes_128(data: bytes, key: bytes) -> bytes:
            """Декодирование из AES-128 по ключу"""
            try:
                iv = data[0:16]
            except TypeError:
                return bytearray()
            ciphered_data = data[16:]
            cipher = AES.new(key, AES.MODE_CBC, iv=iv)
            decoded = unpad(cipher.decrypt(ciphered_data), AES.block_size)
            return decoded

        run(download())
        return b''.join(downloaded_chunks)

    @staticmethod
    def _write_to_file(data: bytes, path: str):
        with open(path, "wb+") as f:
            f.write(data)

    def _write_to_mp3(self, segments_binary_data: bytes, name: str):
        """Записывает бинарные данные в файл и конвертирует его в .mp3"""
        mp3_path = f"{self.save_dir}/{name}.mp3"

        self._write_to_file(data=segments_binary_data, path=self.temp_file_path)

        if not os.path.isfile(mp3_path):
            os.system(f'ffmpeg -hide_banner -loglevel error -i {self.temp_file_path} -vn -acodec copy -y {mp3_path}')
            os.remove(f"{self.temp_file_path}")
        else:
            os.remove(f"{self.temp_file_path}")
            raise Exception(f"Файл {mp3_path} уже существует, задайте другое имя.")

    def search(self, q: str, count: int):
        """Поиск треков по запросу

        Params
        ------
        q:
            Запрос
        count:
            Количество треков в выдаче

        Returns
        -------
        Список словарей с мета-информацией о треках
        """
        response = self._vk_audio.search(q=q, count=count)
        return list(response)

    def download_by_m3u8_url(self, m3u8_url, audio_name):
        """Загрузка и сохранение аудио по m3u8 ссылке"""
        m3u8_data = m3u8.load(uri=m3u8_url)
        parsed_m3u8 = self._parse_m3u8(m3u8_data)
        segments_binary_data = self._get_audio_from_m3u8(parsed_m3u8=parsed_m3u8, m3u8_url=m3u8_url)

        os.makedirs(self.save_dir, exist_ok=True)
        audio_path = f"{self.save_dir}/{audio_name}.ts"
        self._write_to_file(segments_binary_data, path=audio_path)


def main():
    login = ""
    password = ""
    downloader = MusicDownloader(login=login, password=password)

    owner_id = 371745470
    audio_id = 456463164
    downloader.download_audio_by_id(owner_id=owner_id, audio_id=audio_id, verbose=True)


if __name__ == "__main__":
    main()

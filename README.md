## Python скрипт для скачивания музыки из ВКонтакте по id
Нельзя просто так взять и скачать аудио из ВК :D

Официальный API предоставляет лишь возможность получить файл-плейлист *.m3u8. В нем описаны мета-данные сегментов, на которые разбита аудиозапись. У каждого сегмента есть своя ссылка для скачивания. Кроме того, некоторые сегменты зашифрованы алгоритмом AES-128 и рядом лежит ссылка на ключ. После расшифровки сегменты собираются в один набор байт и записываются в файл. С помощью утилиты ffmpeg файл конвертируется в *.mp3
___
Необходима предустановленная утилита ffmpeg, которая должна быть прописана в PATH

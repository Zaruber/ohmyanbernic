<p align="center">
  <img src="LOGO.png" alt="Anbernic Dashboard" width="100%">
</p>

# Anbernic RG405V — Веб морда

Веб-панель мониторинга и управления Anbernic RG405V через Termux.
Доступна по локальной сети с любого устройства через браузер.

## Возможности

| Функция            | Описание                                                                                           |
| ------------------------- | ---------------------------------------------------------------------------------------------------------- |
| **System Monitor**  | CPU, RAM, Storage, Battery — live-данные + графики истории                            |
| **File Manager**    | Навигация, просмотр, удаление и загрузка файлов                    |
| **Script Runner**   | Запуск Python-скриптов в фоновых сессиях с просмотром вывода |
| **Process Manager** | Список процессов, сортировка по CPU, kill                                       |
| **i18n**            | Переключение между русским и английским                                 |

## Стек

- **Backend:** Python 3.7+ (только stdlib — `http.server`, `threading`, `subprocess`)
- **Frontend:** HTML + CSS + JS (vanilla, без фреймворков)
- **Шрифты:** Montserrat + JetBrains Mono (Google Fonts CDN)
- **Зависимости:** **нет** — zero dependencies

## Структура проекта

```
ANBERNIC/
├── server.py          # HTTP-сервер + API (все эндпоинты)
├── index.html         # Фронтенд (SPA, всё в одном файле)
├── requirements.txt   # Зависимости (пустой — stdlib only)
└── README.md          # Этот файл
```

## Деплой на Anbernic RG405V (Termux)

### Предварительные требования

- Anbernic RG405V с установленным **Termux**
- Устройство подключено к **Wi-Fi** в той же сети, что и ваш ПК
- SSH-сервер запущен в Termux (`sshd`)

### Шаг 1. Установка Python в Termux

```bash
pkg update && pkg install python openssh -y
```

### Шаг 2. Перенос файлов на устройство

С вашего ПК (замените `IP` и `USER` на свои):

```bash
scp -P 8022 server.py index.html USER@IP:~/
```

Пример:

```bash
scp -P 8022 server.py index.html u0_a168@192.168.1.76:~/
```

### Шаг 3. Запуск сервера

В Termux на устройстве:

```bash
python server.py &
```

Сервер запустится на порту `8080`. Откройте в браузере:

```
http://<IP устройства>:8080
```

### Шаг 4. Автозапуск (опционально)

Чтобы сервер и SSH стартовали автоматически при открытии Termux:

```bash
echo 'termux-wake-lock' > ~/.bashrc
echo 'sshd' >> ~/.bashrc
echo 'pkill -f server.py 2>/dev/null; sleep 1; python ~/server.py &' >> ~/.bashrc
echo 'echo "Dashboard: http://$(hostname -I | cut -d\" \" -f1):8080"' >> ~/.bashrc
```

### Шаг 5. Отключение энергосбережения Android

> [!IMPORTANT]
> Без этих настроек Android будет убивать Termux в фоне.

1. **Настройки → Батарея → Оптимизация → Termux → "Не оптимизировать"**
2. **Wi-Fi → Дополнительно → Wi-Fi в спящем режиме → "Не отключать"**

## API эндпоинты

| Метод | Путь                     | Описание                                                                 |
| ---------- | ---------------------------- | -------------------------------------------------------------------------------- |
| `GET`    | `/api/stats`               | Системная статистика (CPU, RAM, Storage, Battery)             |
| `GET`    | `/api/network`             | Сетевая информация (hostname, IP, порты)                   |
| `GET`    | `/api/history`             | История метрик (до 1 часа, точки каждые 10 сек) |
| `GET`    | `/api/files?path=`         | Листинг директории                                              |
| `GET`    | `/api/files/read?path=`    | Чтение текстового файла (до 50 КБ)                      |
| `DELETE` | `/api/files?path=`         | Удаление файла                                                      |
| `POST`   | `/api/files/upload`        | Загрузка файла (multipart/form-data)                                |
| `GET`    | `/api/processes`           | Список процессов                                                  |
| `DELETE` | `/api/processes?pid=`      | Завершение процесса                                            |
| `POST`   | `/api/scripts/run`         | Запуск Python-скрипта `{"path": "..."}`                           |
| `GET`    | `/api/scripts/sessions`    | Список активных сессий                                       |
| `GET`    | `/api/scripts/output?pid=` | Вывод сессии (последние 200 строк)                      |
| `DELETE` | `/api/scripts/kill?pid=`   | Остановка сессии                                                  |

## SSH-подключение с Mac

Добавьте в `~/.ssh/config`:

```
Host anbernic
    HostName 192.168.1.76
    Port 8022
    User u0_a168
    GSSAPIAuthentication no
    AddressFamily inet
    ConnectTimeout 30
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

Подключение:

```bash
ssh anbernic
```

## Безопасность

- Файловый менеджер ограничен **домашней директорией** Termux
- Навигация выше `$HOME` заблокирована (path traversal protection)
- Сервер доступен только в **локальной сети**

## Дизайн

Острый минимализм:

| Элемент          | Значение                |
| ----------------------- | ------------------------------- |
| Основной фон | `#1E1E1E`                     |
| Карточки        | `#282828`                     |
| Акцент            | `#2C3F2F`                     |
| Акцент-текст | `#CDF7D5`                     |
| Шрифт UI           | Montserrat                      |
| Шрифт моно     | JetBrains Mono                  |
| Border-radius           | `0` (острые грани) |

## Лицензия

MIT

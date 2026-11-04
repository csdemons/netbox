# NetBox Plan — устройства и первый кабель

Русскоязычный pip-пакет **`netbox-plan`** для **NetBox 4.5+**. Поддерживает
создание и расширение физических серверов и коммутаторов (`dcim.Device`),
серийные номера, проекты, дополнительные Ethernet/FC карты и WWPN, а также
документирование **только первого кабеля** от интерфейса устройства до
**порта коммутатора (`Interface`)** или **лицевого порта патч-панели (`FrontPort`)**.

Полные составные трассы, соединения фронтальных и тыльных портов патч-панелей,
перемычки и дальнейшие кабели остаются ответственностью **штатного NetBox**.
Мастер не изменяет физическое оборудование и не настраивает коммутаторы.

> Версия **0.5.0** — тестовая, не предназначена для немедленной установки на
> продуктивный NetBox. Проверяются Python-синтаксис, pip-сборка и автономные
> тесты. Для допуска к эксплуатации нужно запустить интеграционные тесты
> на отдельно развёрнутом NetBox + PostgreSQL (Docker).

## Важные имена: не переименовываем миграции

| Что | Имя |
|---|---|
| Пакет для `pip install` | `netbox-plan` |
| Файл дистрибутива | `netbox_plan-0.5.0-py3-none-any.whl` |
| Модуль плагина в `PLUGINS` | `netbox_server_wizard` |
| Ключ настроек `PLUGINS_CONFIG` | `netbox_server_wizard` |
| Миграции и существующие таблицы БД | `netbox_server_wizard` |
| Имя в интерфейсе | **NetBox Plan** |

**Не заменяйте** `netbox_server_wizard` на `netbox_plan` в настройках:
это намеренная совместимость с ранее созданной схемой БД версий 0.3/0.4.
При переходе со старого образа установите новый образ от того же официального
NetBox Docker, а не поверх старого пользовательского образа с другим
названием pip-дистрибутива.

## Как работает мастер

1. Открыть **Плагины → NetBox Plan — устройства и первый кабель**.
2. Выбрать **создать новое устройство** (сервер или коммутатор) или **дополнить существующее**.
3. Заполнить площадку, модель, роль, стойку, серийный номер и проект. При
   необходимости создать проект из мастера.
4. Через **+** указать сетевые карты Ethernet или HBA Fibre Channel, количество
   и имена портов, серийные номера и WWPN для FC.
5. Для каждого физического интерфейса выбрать **ближайшее устройство**:
   - коммутатор (роль из `switch_role_slugs`) → свободный **Interface**;
   - патч-панель (роль из `patch_panel_role_slugs`) → свободный **FrontPort**.
6. Создать физический кабель со статусом `planned` или `connected`.

В мастере доступны только **однопозиционные FrontPort** (`positions=1`).
`FrontPort.type` — **тип разъёма** (LC, SC, 8P8C и т. п.), не тип протокола.
Ethernet/FC проверяются при подключении к интерфейсу коммутатора; при
подключении к патч-панели оператор должен сам подтвердить соответствие
физической среды и коннектора. `RearPort` в мастере не выбирается.

Существующие соединения дальше по трассе отображаются и трассируются
в NetBox, когда корректно заведены его `FrontPort` ↔ `RearPort` mappings
и следующие кабели. Мастер не создаёт эти mappings.

### Как хранятся объекты

- Оборудование: `dcim.Device`, интерфейсы: `dcim.Interface`.
- Первый кабель: `dcim.Cable`, A-окончание `Interface`, B-окончание
  `Interface` либо `FrontPort`.
- Проекты: модель плагина `Project` и связь `DeviceProject` (один проект/устройство).
- Дополнительные адаптеры: модель `Adapter`, связи с портами `AdapterPort`.
- Серийные номера корпуса в `Device.serial`, карт в `Adapter.serial`;
  WWPN портов FC в `Interface.wwn`.
- Проекты и карты используют `ChangeLoggedModel` NetBox, когда операции
  выполняются через web-request.

### Безопасность

- Целевые устройства доступны **только** по явно настроенным slug ролей;
  оба списка пусты по умолчанию (fail closed).
- Права `ObjectPermission` проверяются на конкретных объектах, включая
  `change_interface` и `change_frontport` для кабельных окончаний.
- Нельзя повторно использовать занятые и `mark_connected` порты.
- Выбранные окончания блокируются через `SELECT ... FOR UPDATE`; все
  изменения (создание устройства, карт, проекта, кабелей) идут в одной
  `transaction.atomic()` и откатываются целиком при ошибке.
- Не поддерживаются `FrontPort.positions > 1`, `RearPort`, автонастройка
  коммутаторов, LACP, VLAN, настройка SFP/оптики и построение составной трассы.

## Установка wheel в Docker (рекомендуется)

Плагин в `netbox-community/netbox-docker` нужно устанавливать в **собственный
образ**, который используют **оба** сервиса: `netbox` и `netbox-worker`.
Установка `pip install` вручную в запущенный контейнер недолговечна:
результат исчезает при пересоздании контейнера.

**Обязательно** определите тег работающего образа:

```bash
docker compose images
# пример: docker.io/netboxcommunity/netbox:v4.5-<номер сборки>
```

Ниже два репозитория лежат рядом: `netbox-docker/` и `netbox-publish/`.

```bash
cd /path/to/netbox-publish
python3 -m pip install --upgrade build
python3 -m build --sdist --wheel -o dist
# wheel: dist/netbox_plan-0.5.0-py3-none-any.whl
```

В каталоге `netbox-docker/` создайте/дополните
`configuration/plugins.py` (сохраните другие плагины):

```python
PLUGINS = [
    # ...другие существующие плагины...
    "netbox_server_wizard",
]

PLUGINS_CONFIG = {
    # ...конфигурации других плагинов...
    "netbox_server_wizard": {
        "server_role_slugs": ["server"],
        "switch_role_slugs": ["switch", "san-switch"],
        "patch_panel_role_slugs": ["patch-panel", "fiber-panel"],
    },
}
```

Это **примеры slug** — требуется указать значения, существующие в вашей
базе. Если список ролей не задан, такая категория устройств не предлагается
для создания первого кабеля. Особенно важно назначить отдельную роль
патч-панелям и убедиться, что FrontPort уже созданы.

В каталоге `netbox-docker/` запустите сборку **на тестовом стенде**:

```bash
# Укажите точный текущий тег своего образа NetBox, а не обновляйтесь вместе с плагином.
export NETBOX_BASE_IMAGE='docker.io/netboxcommunity/netbox:<точный-текущий-тег>'
export NETBOX_PLAN_VERSION='0.5.0'

# Если проект лежит рядом, как в примере:
cp ../netbox-publish/docker/docker-compose.plugin.yml docker-compose.plan.yml
# Учтите: пути override разрешаются относительно первого compose-файла.

docker compose -f docker-compose.yml -f docker-compose.plan.yml build netbox
# Поднимать ТОЛЬКО на тестовом контуре с отдельной БД и volumes:
docker compose -f docker-compose.yml -f docker-compose.plan.yml up -d
```

Файл `docker/Dockerfile.wheel` устанавливает **готовый wheel**, а не
исходный код. Текущий `docker-compose.plugin.yml` использует этот Dockerfile.
Файл `docker/Dockerfile` оставлен как вариант сборки напрямую из исходников.

На тестовом контуре проверить:

```bash
docker compose -f docker-compose.yml -f docker-compose.plan.yml exec netbox \
  /opt/netbox/venv/bin/python -m pip show netbox-plan

docker compose -f docker-compose.yml -f docker-compose.plan.yml exec netbox \
  /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py check

docker compose -f docker-compose.yml -f docker-compose.plan.yml exec netbox \
  /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py showmigrations netbox_server_wizard
```

**Миграции**: при первой установке нужны `0001_initial` и
`0002_changelog_fields`. NetBox Docker обычно выполняет миграции при запуске;
перед запуском проверьте план миграций и резервную копию PostgreSQL.
Миграций специально для `0.5.0` нет: схема сохранена как у `0.4.0`.

## Тесты

На любой машине с Python 3.12+ **без NetBox/PostgreSQL**:

```bash
python3 -m compileall -q netbox_server_wizard tests
python3 -m unittest discover -s tests -v
python3 -m pip wheel --no-deps --no-build-isolation -w dist .
```

Интеграционные тесты (только в **изолированном контейнере** с временной БД;
используется Django `manage.py test`, **не** на рабочей БД):

```bash
# В контейнере после установки wheel и настройки PLUGINS:
/opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py \
  test netbox_server_wizard.tests --noinput --verbosity 2
```

Тесты покрывают миграции, создание сервера и коммутатора, Ethernet/FC,
WWPN, права, откат транзакции, одновременное соединение к одному порту
коммутатора, а в `0.5.0` — подключение к FrontPort патч-панели.

**Проверенные локальные тесты не означают, что интеграционные тесты прошли.**
Полную совместимость с реальным тегом NetBox Docker необходимо подтвердить
на отдельном стенде, включая роль для PostgreSQL с правом создать тестовую БД.

## Обновление с версии 0.4.0

Из репозитория `csdemons/netbox` примените подготовленный патч `0.4→0.5`,
соберите wheel и отправьте commit в GitHub. **Не** переименовывайте app label
`netbox_server_wizard`, иначе нарушится зависимость существующих миграций.
Перед установкой новой версии — резервная копия PostgreSQL и проверка
актуальных `PLUGINS_CONFIG` и роли пользователей.

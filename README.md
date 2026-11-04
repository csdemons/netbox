# NetBox Server Wizard — серверы, коммутаторы, Ethernet/FC и проекты

Русскоязычный плагин для **NetBox 4.5+**, развёрнутого в том числе с помощью
[netbox-community/netbox-docker](https://github.com/netbox-community/netbox-docker).
Создаёт **физический сервер или коммутатор** как штатный `dcim.Device` либо
дополняет существующее устройство, назначает проект, учитывает сетевые карты,
серийные номера, WWPN и регистрирует кабели в кабельном менеджере NetBox.

**Статус: v0.4.0, экспериментальный.** В разработческой среде проверяются
синтаксис, сборка wheel и 9 автономных тестов. Файлы интеграционных тестов
для PostgreSQL/NetBox и CI предоставлены, но успешное выполнение этих тестов
в реальном NetBox **пока не подтверждено**. Не устанавливать в рабочую систему
до испытаний на отдельном тестовом контуре и резервного копирования.

## Мастер

1. В меню «Плагины → Добавить сервер или коммутатор / кабели» выберите
   **тип оборудования: сервер / коммутатор** и **режим: создать / изменить**.
2. Выберите площадку, Device Type, роль, стойку, U, серийный номер и статус
   (для существующего устройства достаточно выбрать его из списка).
3. Выберите существующий проект либо создайте новый через «+».
4. Через «+ Добавить карту» создайте Ethernet NIC или FC HBA, указав
   наименование, Part Number, серийный номер, тип и 1–8 интерфейсов.
   Для FC можно указать **WWPN каждого порта** в порядке перечисления портов:
   `10:00:00:10:9B:12:34:50, 10:00:00:10:9B:12:34:51`.
5. Выберите **коммутатор** и **свободный порт** для каждого интерфейса;
   для FC доступны только FC-порты. Для коммутатора доступны те же операции,
   включая прямое подключение его портов к другим коммутаторам.
6. Сохраните: создание устройств, интерфейсов, карт, проектов и кабелей
   происходит в **одной транзакции PostgreSQL**.

Фактическую конфигурацию реальных коммутаторов этот плагин не изменяет.

## Обязательная настройка ролей коммутаторов

Во избежание ошибочных соединений **список целевых коммутаторов по умолчанию пуст**.
Администратор обязан указать реальные slug ролей, например:

```python
PLUGINS = ["netbox_server_wizard"]  # добавить к другим установленным плагинам
PLUGINS_CONFIG = {
    "netbox_server_wizard": {
        "switch_role_slugs": ["switch", "san-switch"],
        "server_role_slugs": ["server"],
    },
}
```

**Важное отличие:** `switch_role_slugs` обязателен для выбора целевых
коммутаторов и создания кабелей через мастер. Если список пуст, мастер
позволит добавить устройство, но запретит назначение кабелей.
`server_role_slugs` необязателен; при пустом списке разрешены все роли
серверов, доступные пользователю. При выборе типа «Коммутатор» мастер
использует роль выбранного оборудования, не создавая отдельный тип объекта.

## Исправления безопасности и целостности v0.4.0

- Перед изменением **существующего** устройства проверяются право
  `dcim.change_device` и его объектные ограничения.
- Для **новых** объектов выполняется сохранение внутри `transaction.atomic()`,
  после чего **до commit** проверяется доступ через
  `Model.objects.restrict(user, 'add').filter(pk=...).exists()`.
  Если ограничения `ObjectPermission` запрещают создание, транзакция
  откатывается, и объекты не остаются в БД.
- Для кабеля проверяется `add_cable`; для исходного и целевого интерфейса —
  объектное `change_interface`, а также `view_interface`; для целевого
  коммутатора — `view_device`.
- Для существующих привязок проекта проверяется объектное `change`,
  для новых проектов, карт и связей портов — объектное `add`.
- При создании кабеля повторно проверяются роль устройства, площадка,
  Ethernet/FC-тип, занятость порта и отметка `mark_connected`.
- Перед записью целевые порты блокируются `SELECT ... FOR UPDATE`;
  второй оператор не может занять тот же порт после фиксации первого.
- Отказы построения кабельного пути (`AbortRequest`,
  `UnsupportedCablePath`) отображаются как ошибки формы.
  Непредвиденные системные ошибки не маскируются и должны попадать в логи.
- Модели `Project`, `DeviceProject`, `Adapter`, `AdapterPort` наследуются
  от `netbox.models.ChangeLoggedModel`, что подключает штатный механизм
  журнала изменений NetBox при работе через его request middleware.
- `Interface.wwn` используется для WWPN каждого порта FC HBA;
  типы InfiniBand/SONET/виртуальных интерфейсов не считаются Ethernet.

**Ограничения**: это не полноценная система согласований изменений.
Нет поддержки патч-панелей, VLAN, SFP, LACP, iDRAC/iLO, автоматической
настройки коммутаторов; проект только один на устройство.
Контроль физических типов трансиверов не реализован, поддерживается
разделение FC/Ethernet. Исходные порты, не относящиеся к поддерживаемым
физическим FC/Ethernet, не предлагаются к подключению.

## Установка в netbox-docker

**Нельзя применять команды systemctl или pip установки в работающий контейнер
как постоянное решение:** необходимо собрать расширенный образ и использовать
его для сервисов `netbox` и `netbox-worker`.

Пример структуры каталогов на хосте:

```text
/work/netbox-publish/      # этот репозиторий, версия 0.4.0
/work/netbox-docker/       # netbox-community/netbox-docker, ветка release
```

1. **Узнайте версию текущего NetBox Docker**, сохраните БД и конфигурацию:

   ```bash
   cd /work/netbox-docker
   docker compose images
   docker compose exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py --version
   ```

   Пример в `docker/docker-compose.plugin.yml` использует `v4.7`; **замените
   `NETBOX_BASE_IMAGE` на точно тот же тег, что используется на вашем
   текущем стенде.** Не запускайте неподтверждённое обновление NetBox.

2. Скопируйте или объедините содержимое `docker/plugins.py.example` с
   **существующим** `netbox-docker/configuration/plugins.py`. Не стирайте
   другие плагины и настройки; укажите реальные роли устройств.

3. Соберите отдельный образ на **тестовом Docker-стенде**:

   ```bash
   cd /work/netbox-docker
   export NETBOX_BASE_IMAGE=docker.io/netboxcommunity/netbox:v4.7  # ПРИМЕР, замените
   docker compose -f docker-compose.yml \
     -f ../netbox-publish/docker/docker-compose.plugin.yml build netbox
   docker compose -f docker-compose.yml \
     -f ../netbox-publish/docker/docker-compose.plugin.yml up -d
   ```

   Официальный `netbox-docker` запускает необходимые процедуры и миграции
   при инициализации; в любом случае сначала проверьте план:

   ```bash
   docker compose -f docker-compose.yml \
     -f ../netbox-publish/docker/docker-compose.plugin.yml exec netbox \
     /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py \
     showmigrations netbox_server_wizard
   ```

4. Для обновления с v0.3.0 применяется миграция
   `netbox_server_wizard.0002_changelog_fields`: она добавляет поля
   `created` и `last_updated` к четырём моделям и сохраняет старые записи.

### Тесты с PostgreSQL

**Только на тестовом стенде** (проверить отдельную PostgreSQL БД, разрешение
`CREATEDB` у роли, достаточное место и отсутствие конфликтующего тестового имени):

```bash
cd /work/netbox-docker
I_AM_USING_STAGING=yes ../netbox-publish/docker/test-staging.sh
```

Скрипт использует `manage.py check`, `makemigrations --check --dry-run` и
`manage.py test netbox_server_wizard.tests`. Django test runner должен
создать **отдельную тестовую БД**, а не использовать производственные данные.
Из-за особенностей окружения запускать скрипт следует на отдельном Docker
стенде, **не внутри рабочего кластера**.

Проверяются создание сервера и коммутатора, генерация портов из Device Type,
создание проекта, Ethernet/FC-карт и WWPN, построение кабелей, отказ при
незаданной роли коммутатора, объектные ограничения на создание, откат
запрещённого действия, конфликт одного порта у двух операторов и
миграция с сохранением существующего проекта.

В `.github/workflows/ci.yml` есть задания для 9 быстрых тестов и для полного
тестирования на отдельном netbox-docker + PostgreSQL/Redis. **Пока нет
успешного отчёта выполнения CI на загруженном коде, результат нельзя
считать подтверждением продакшен-готовности.**

## Локальные проверки

```bash
python3 -m compileall -q netbox_server_wizard tests
python3 -m unittest discover -s tests -v
python3 -m pip wheel --no-deps --no-build-isolation -w dist .
```

## Разрешения

Операторы должны обладать соответствующими **объектными**, а не только
модельными правами: `view_device`, `change_device` для существующего
устройства, `add_device` для нового, `view_interface`, `change_interface`
при добавлении кабеля, `add_interface` при создании новых портов,
`add_cable`, плагиновыми `view/add/change` по необходимости для
`Project`, `DeviceProject`, `Adapter`, `AdapterPort`.
Администратор должен настроить подходящие правила `ObjectPermission`.
Тестирование под суперпользователем не заменяет проверку обычных ролей.

## Состав проекта

```text
netbox_server_wizard/
  __init__.py
  choices.py
  forms.py
  views.py
  models.py
  migrations/0001_initial.py
  migrations/0002_changelog_fields.py
  navigation.py
  template_content.py
  templates/netbox_server_wizard/
  tests/test_integration.py
  tests/test_migrations.py

tests/test_choices.py
docker/Dockerfile
docker/docker-compose.plugin.yml
docker/plugins.py.example
docker/test-staging.sh
.github/workflows/ci.yml
pyproject.toml
```

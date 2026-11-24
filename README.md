# Журнал подань

Flask приймає JSON з полями group_code і submission_key. SE-01 є прикладом коду групи. Ключ унікальний у SQLite. Перше успішне подання повертає 201, повтор тієї самої роботи повертає 200 з тим самим номером. Дані в навчальному експерименті синтетичні.

## Тести та образи

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -r requirements-test.txt
    python lab.py test --timeout 45

Публічний workflow release.yml запускається для Git-тегів v*. Тег v1.0.0-ci вказує на той самий коміт, що й v1.0.0. Робочий випуск v2 зібрано з v2.0.0. Workflow також запускається для контрольної гілки experiment/test-gate. У GitHub Actions завантаж архіви image-v1.0.0-ci і image-v2.0.0 у local-artifacts/v1 і local-artifacts/v2. Архіви мають image.sha256 та image-id.txt. Обидва проходять перевірку перед запуском. Для v1 скрипт додає локальний псевдонім тега після перевірки ID. Образи зібрано для Linux ARM64. Для повторного запуску на іншій архітектурі потрібна підтримка ARM64 у Docker.

    gh run download 45445741701 -R SashaPom/submission-canary-lab -n image-v1.0.0-ci -D local-artifacts/v1
    gh run download 45445568578 -R SashaPom/submission-canary-lab -n image-v2.0.0 -D local-artifacts/v2
    bash scripts/deliver.sh local-artifacts/v1 staging
    python -m pytest -q --hosts="docker://$(docker compose -p submission-stage ps -q stage)" infra
    curl -sS -i -H 'Content-Type: application/json' \
      -d '{"group_code":"SE-01","submission_key":"stage-v1-001"}' \
      http://127.0.0.1:8091/submissions
    bash scripts/deliver.sh local-artifacts/v2 staging
    python -m pytest -q --hosts="docker://$(docker compose -p submission-stage ps -q stage)" infra
    curl -sS -i -H 'Content-Type: application/json' \
      -d '{"group_code":"SE-01","submission_key":"stage-v2-001"}' \
      http://127.0.0.1:8091/submissions

Для повторного тестового подання підстав новий ключ. Staging використовує окремий том і прапорець 0. На робочому стенді обидві версії підключені до одного тома. Файл .env.example описує змінні Compose. Не видаляй робочий том під час відкату.

## Рішення про збільшення трафіку

Рішення ухвалює оператор навчального релізу після аналізу вимірів. Для всіх серій клієнт посилає 200 однотипних POST із новими ключами, інтервал між спробами 35 мс, тайм-аут 2 с. Поріг p95 зафіксовано перед запуском на 250 мс. Розширення canary можливе після щонайменше 20 спроб на v2, за частки помилок до 5% включно і p95 до 250 мс. Помилки — сума 5xx та спроб без завершеної відповіді. p95 обчислюється методом найближчого рангу серед завершених відповідей. SLI — частка всіх спроб з 201 не пізніше ніж за 1 с. Навчальний SLO становить 99%.

    bash scripts/deliver.sh local-artifacts/v1 working
    docker compose -p submission-work up -d prometheus
    python scripts/traffic.py baseline --prefix run-01 --output results
    LAB_CANARY_FAIL=1 bash scripts/deliver.sh local-artifacts/v2 working
    python scripts/traffic.py canary --prefix run-01 --output results

За невиконання порогів оператор припиняє подавати запити на v2 і зупиняє цей контейнер. Префікс має бути новим під час повторення набору серій.

    docker compose -p submission-work stop v2
    python scripts/traffic.py rollback --prefix run-01 --output results
    curl -sS -i http://127.0.0.1:8081/submissions/210
    curl -sS -i -H 'Content-Type: application/json' \
      -d '{"group_code":"SE-01","submission_key":"run-01-canary-010"}' \
      http://127.0.0.1:8081/submissions

Приклад номера 210 передбачає порожній робочий том до першого прогону. Для іншого запуску візьми submission_id і submission_key з першого рядка v2 у canary.csv. Повтор має повернути той самий номер. Зупинка стенда зберігає томи SQLite.

    docker compose -p submission-work --profile working down
    docker compose -p submission-stage --profile staging down

## Метрики та журнали

Запит Prometheus sum by (version, status) (submission_responses_total) показує кількість завершених POST. Його результат зберігає python scripts/metrics.py --output results/canary-prometheus.json. Prometheus доступний на 127.0.0.1:9090. Метрики накопичувальні до перезапуску процесу. Вимірюй їх до зупинки v2.

    docker compose -p submission-work logs --no-log-prefix v1 v2 | awk '/^[{]/' > results/submissions.jsonl
    python lab.py summarize results/submissions.jsonl
    python lab.py summarize results/absent.jsonl

У лабораторному запуску сирі CSV, дані Prometheus та пов'язаний за request_id фрагмент JSONL знаходяться в evidence. Журнал підраховує тільки події submission_response, по одній на кожен POST.

## Як зупиняється збірка

Крок Run the timed test command викликає lab.py test і зберігає статус pytest завдяки Bash із pipefail. Ненульовий статус пропускає наступний крок Build and checksum the image. Діагностика pytest зберігається й тоді, коли збірку пропущено.

## Прозорість підготовки

ШІ допоміг підготувати чернетки сервісу, тестів і CI. Результат перевірено реальними прогонами pytest, HTTP-запитами в Docker і журналами GitHub Actions.

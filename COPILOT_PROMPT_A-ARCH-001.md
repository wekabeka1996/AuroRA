## 📌 TASK_ID: A-ARCH-001 — Archive non-production files

КОПІЛОТ, ВИКОНАЙ:

Створи інструмент для архівації всього коду, який **не використовується у продакшн-запуску Аврори та скальп-бота**.

ІНСТРУКЦІЇ:

1. Створи новий файл: `tools/archive_nonprod.py`.

2. Логіка:

   * У режимі `--dry-run` виводь список файлів/папок, які підлягають архівації.
   * У звичайному режимі переміщуй їх у каталог:
     `archive/YYYYMMDD/...` (зберігаючи відносні шляхи).
   * Додай файл `ARCHIVE_INDEX.md` у папці архіву, який містить таблицю «звiдки → куди».

3. В архів переміщати:

   * `notebooks/**`
   * `experiments/**`
   * `prototypes/**`
   * `scripts/legacy/**`
   * `*.ps1` файли
   * `docs/drafts/**`
   * `tmp/**`
   * інші *dev-only* утиліти, які не використовуються в CLI/runner/API.

4. **Не чіпати (залишити в репо):**

   * `tools/auroractl.py`, `tools/run_all.py`
   * `core/**`, `app/**`
   * `configs/**`, `tests/**`
   * `logs/**`, `artifacts/**`
   * `Makefile`, `README.md`

5. Онови `README.md`:

   * Додай розділ «Repo layout after archive».
   * Додай інструкцію «Як відновити файли з archive/».

6. Додай приклади запуску:

```
python tools/archive_nonprod.py --dry-run
python tools/archive_nonprod.py
```

КРИТЕРІЇ ГОТОВНОСТІ (DoD):

* Після архівації всі тести (`pytest -q`) мають проходити.
* `tools/auroractl.py start-api && tools/auroractl.py health` працює.
* Файл `archive/YYYYMMDD/ARCHIVE_INDEX.md` створений і містить список перенесених файлів.

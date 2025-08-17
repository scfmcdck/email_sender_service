# fetch_allure_owner_emails.py
# -*- coding: utf-8 -*-
"""
Читает project_ids.csv из папки скрипта, для каждого ID вызывает:
  GET {ALLURE_BASE_URL}/api/project/access/{projectId}/collaborator
Считает владельцами записи с permissionSetName == "Project Owner" (с учётом регистра/пробелов)
и сохраняет уникальные e-mail в emails.csv.

Требуется: pip install requests
Запуск: python fetch_allure_owner_emails.py
"""

import csv
import os
import re
import sys
import time
import json
from typing import List, Dict, Any, Optional

import requests # type: ignore
from urllib3.exceptions import InsecureRequestWarning # type: ignore
import urllib3 # type: ignore

# ================== НАСТРОЙКИ ==================
ALLURE_BASE_URL = "your-endpoint-url"  # без завершающего /
ALLURE_TOKEN    = "your-token-here"   # вставьте токен
TOKEN_TYPE      = "Api-Token"       # или 'Bearer'

INPUT_CSV  = "project_ids.csv"
OUTPUT_CSV = "emails.csv"

# Отладочная печать примеров объектов коллабораторов
DEBUG_MODE         = False       # при необходимости поставьте True
DEBUG_SAMPLE_LIMIT = 2
# =================================================

# Отключаем проверку SSL и предупреждения об этом (verify=False)
VERIFY = False
urllib3.disable_warnings(InsecureRequestWarning)


def read_project_ids(path: str) -> List[str]:
    """Считывает все числовые ID из CSV, убирает дубликаты, сохраняет порядок."""
    ids: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            for token in row:
                token = token.strip()
                if token.isdigit():
                    ids.append(token)
    # убрать дубликаты с сохранением порядка
    seen = set()
    uniq = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    return uniq


def _norm(x: Any) -> str:
    """UPPER + пробелы/дефисы в подчёркивания (Project Owner -> PROJECT_OWNER)."""
    return re.sub(r"[\s\-]+", "_", str(x or "").upper())


def is_owner(collab: Dict[str, Any]) -> bool:
    """Владелец = permissionSetName содержит Project Owner (независимо от регистра/пробелов)."""
    # Явные булевы флаги (на всякий)
    for k in ("isOwner", "owner", "projectOwner"):
        if isinstance(collab.get(k), bool) and collab[k]:
            return True

    # Главный признак — permissionSetName
    pset_name = _norm(collab.get("permissionSetName"))
    if "PROJECT_OWNER" in pset_name or pset_name == "OWNER":
        return True

    # Резервные признаки (если вдруг поля появятся в других проектах)
    role = _norm(collab.get("role"))
    if "PROJECT_OWNER" in role or role == "OWNER":
        return True

    pr = collab.get("projectRole") or {}
    pr_name = _norm(pr.get("name"))
    if "PROJECT_OWNER" in pr_name or pr_name == "OWNER":
        return True

    access_level = _norm(collab.get("accessLevel"))
    if "PROJECT_OWNER" in access_level or access_level == "OWNER":
        return True

    return False


def _looks_like_email(val: str) -> bool:
    return bool(val) and re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", val) is not None


def extract_email(collab: Dict[str, Any]) -> Optional[str]:
    """Вытянуть email. Он на верхнем уровне: 'email'."""
    # верхний уровень
    for key in ("email", "mail", "username", "login"):
        val = collab.get(key)
        if isinstance(val, str) and _looks_like_email(val):
            return val.strip()

    # запасной путь — во вложенном user
    user = collab.get("user") or {}
    for key in ("email", "mail", "username", "login"):
        val = user.get(key)
        if isinstance(val, str) and _looks_like_email(val):
            return val.strip()

    return None


def fetch_collaborators(project_id: str):
    """GET /api/project/access/{projectId}/collaborator"""
    url = f"{ALLURE_BASE_URL.rstrip('/')}/api/project/access/{project_id}/collaborator"
    headers = {
        "Authorization": f"{TOKEN_TYPE} {ALLURE_TOKEN}",
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=30, verify=VERIFY)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("content", "items", "results", "data", "collaborators"):
            if isinstance(data.get(key), list):
                return data[key]
        # если пришёл один объект
        return [data]
    return []


def _role_label_for_stats(collab: Dict[str, Any]) -> str:
    """Для сводки по ролям показываем приоритетно permissionSetName."""
    return (
        _norm(collab.get("permissionSetName"))
        or _norm(collab.get("role"))
        or _norm((collab.get("projectRole") or {}).get("name"))
        or _norm(collab.get("accessLevel"))
        or "UNKNOWN"
    )


def main():
    here = os.path.abspath(os.path.dirname(__file__))
    input_path = os.path.join(here, INPUT_CSV)
    output_path = os.path.join(here, OUTPUT_CSV)

    if not os.path.exists(input_path):
        print(f"❌ Не найден {INPUT_CSV} рядом со скриптом: {input_path}")
        sys.exit(1)

    project_ids = read_project_ids(input_path)
    print(f"Найдено {len(project_ids)} projectId: {project_ids}")
    if not project_ids:
        # создадим пустой результат, чтобы пайплайны не падали
        open(output_path, "w", encoding="utf-8").close()
        sys.exit(0)

    emails = set()

    for pid in project_ids:
        print(f"\n🔍 Обработка проекта {pid}…")
        try:
            collabs = fetch_collaborators(pid)
            print(f"   → Получено коллабораторов: {len(collabs)}")

            if DEBUG_MODE and collabs:
                print("   ↳ Пример(ы) объектов:")
                for sample in collabs[:DEBUG_SAMPLE_LIMIT]:
                    try:
                        print("     ", json.dumps(sample, ensure_ascii=False)[:800])
                    except Exception:
                        print("     ", str(sample)[:800])

            owners = [c for c in collabs if is_owner(c)]
            if not owners:
                # сводка по ролям с приоритетом permissionSetName
                role_stats = {}
                for c in collabs:
                    label = _role_label_for_stats(c)
                    role_stats[label] = role_stats.get(label, 0) + 1
                print(f"   → Владельцев не найдено. Роли в ответе: {role_stats}")
            else:
                print(f"   → Найдено владельцев: {len(owners)}")

            added = 0
            for c in owners:
                email = extract_email(c)
                if email and email not in emails:
                    emails.add(email)
                    added += 1
            print(f"   → Добавлено email: {added}")

        except requests.HTTPError as e:
            print(f"   ❌ HTTP ошибка: {e}")
        except requests.RequestException as e:
            print(f"   ❌ Сетевая ошибка: {e}")
        except json.JSONDecodeError:
            print("   ❌ Некорректный JSON в ответе")
        except Exception as e:
            print(f"   ❌ Неожиданная ошибка: {e}")

        time.sleep(0.1)  # чтобы не спамить сервер

    # Сохраняем результат
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for email in sorted(emails):
            w.writerow([email])

    print(f"\n✅ Найдено {len(emails)} уникальных email'ов.")
    print(f"📁 Результат сохранён в {OUTPUT_CSV} (рядом со скриптом)")


if __name__ == "__main__":
    main()
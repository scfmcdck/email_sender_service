#!/usr/bin/env python3

"""
Забирает ID каждого проекта в Allure используя метод:
  GET /api/rs/project
и сохраняет уникальные ID построчно в project_ids.csv.

Требуется: pip install requests
Запуск: python fetch_allure_project_ids.py
"""

import os
import sys
import csv
import requests
import urllib3

# Отключаем предупреждения о небезопасном соединении
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ENDPOINT = os.getenv("ALLURE_ENDPOINT") or "https://your-testops.example.com" # без завершающего /
USER_TOKEN = os.getenv("ALLURE_USER_TOKEN") or "PUT_YOUR_API_TOKEN_HERE" # вставьте токен
OUT_CSV = os.getenv("OUT_CSV") or "project_ids.csv"

def get_jwt(endpoint: str, user_token: str) -> str:
    url = f"{endpoint.rstrip('/')}/api/uaa/oauth/token"
    resp = requests.post(
        url,
        headers={"Accept": "application/json", "Expect": ""},
        data={"grant_type": "apitoken", "scope": "openid", "token": user_token},
        timeout=30,
        verify=False  # отключена проверка SSL
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

def fetch_all_projects(endpoint: str, jwt: str):
    page = 0
    size = 200
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "Authorization": f"Bearer {jwt}",
    })

    while True:
        url = f"{endpoint.rstrip('/')}/api/rs/project"
        params = {"page": page, "size": size, "sort": "id,asc"}
        resp = session.get(url, params=params, timeout=30, verify=False)  # verify=False
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, dict) and "content" in data:
            items = data["content"]
            last_page = data.get("last", (page + 1) >= data.get("totalPages", page + 1))
        elif isinstance(data, list):
            items = data
            last_page = True
        else:
            raise RuntimeError(f"Неожиданный формат ответа: {type(data)}")

        for prj in items:
            yield prj.get("id")

        if last_page or not items:
            break
        page += 1

def main():
    if USER_TOKEN == "PUT_YOUR_API_TOKEN_HERE":
        print("✋ Укажите API токен в переменной окружения ALLURE_USER_TOKEN или прямо в скрипте.")
        sys.exit(1)

    jwt = get_jwt(ENDPOINT, USER_TOKEN)
    ids = list(filter(lambda x: x is not None, fetch_all_projects(ENDPOINT, jwt)))

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for pid in ids:
            w.writerow([pid])

    print(f"✅ Записано {len(ids)} ID в {OUT_CSV}")

if __name__ == "__main__":
    main()

import csv
import json
import os
import sys
import time
from pathlib import Path
import urllib.request
import urllib.error

# ── Конфигурация ──────────────────────────────────────────────────────────────
API_URL   = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "baidu/cobuddy:free" 
INPUT_CSV = Path("data/reviews.csv")
OUTPUT_JSON = Path("results/classified_reviews.json")
CONFIG_FILE = Path(".config.json")  # Файл для хранения API-ключа

# Промпты для работы с LLM
SYSTEM_PROMPT_ANALYZE = """Ты — аналитик отзывов. Тебе будет передан отзыв на товар на русском языке.
Твоя задача — вернуть ТОЛЬКО валидный JSON без лишнего текста, в точном формате:
{
  "sentiment": "<positive|negative|neutral>",
  "sentiment_score": <число от -1.0 до 1.0>,
  "topic": "<главная тема отзыва одним-двумя словами>",
  "aspects": {
    "quality": "<positive|negative|neutral|not_mentioned>",
    "price": "<positive|negative|neutral|not_mentioned>",
    "service": "<positive|negative|neutral|not_mentioned>",
    "delivery": "<positive|negative|neutral|not_mentioned>"
  },
  "summary": "<краткое резюме отзыва в одном предложении>",
  "recommend": <true|false|null>
}
Отвечай ТОЛЬКО JSON."""

SYSTEM_PROMPT_GENERATE = """Ты — симулятор базы данных интернет-магазина. Твоя задача — сгенерировать CSV-таблицу с фиктивными отзывами пользователей на русском языке.
Формат CSV должен содержать заголовки: ID,Товар,Отзыв
Сгенерируй ровно 5 строк с данными. Отзывы должны быть разными по тональности (позитивные, негативные, нейтральные) и затрагивать разные категории товаров (электроника, одежда, доставка).
Важно: в поле 'Отзыв' не используй символы перевода строки и кавычки, чтобы не ломать CSV-структуру.
Отвечай ТОЛЬКО чистым текстом CSV, без markdown-разметки (без ```csv)."""

def get_or_ask_api_key() -> str:
    """Загружает API-ключ из файла конфигурации или запрашивает его у пользователя."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                api_key = config.get("API_KEY", "").strip()
                if api_key:
                    return api_key
        except Exception:
            pass # Если файл поврежден, просто переспросим ключ

    # Если ключа нет, запрашиваем у пользователя
    print("API-ключ OpenRouter не найден.")
    while True:
        api_key = input("Пожалуйста, введите ваш API-ключ: ").strip()
        if api_key.startswith("sk-or-"):
            break
        print("Похоже, это некорректный ключ. Ключи OpenRouter обычно начинаются с 'sk-or-...'.")
        choice = input("Вы уверены, что хотите использовать этот ключ? (y/n): ").strip().lower()
        if choice == 'y' or choice == 'yes':
            break

    # Сохраняем ключ в файл конфигурации
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"API_KEY": api_key}, f, ensure_ascii=False, indent=2)
        print(f"Ключ успешно сохранен в файл {CONFIG_FILE} и больше не будет запрашиваться.\n")
    except Exception as e:
        print(f"Не удалось сохранить ключ в файл: {e}. При следующем запуске его придется ввести снова.\n")

    return api_key

def clean_llm_response(raw_text: str) -> str:
    """Очищает ответ модели от markdown-разметки (
```json, ```csv)."""
    raw_text = raw_text.strip()
    if "```" in raw_text:
        parts = raw_text.split("```")
        for part in parts:
            part_clean = part.strip()
            if part_clean.startswith("json"):
                part_clean = part_clean[4:]
            elif part_clean.startswith("csv"):
                part_clean = part_clean[3:]
            
            if part_clean:
                return part_clean.strip()
    return raw_text

def call_llm(api_key: str, prompt_system: str, prompt_user: str) -> str:
    """Универсальный метод для отправки запросов в OpenRouter."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user}
        ],
        "temperature": 0.7 if "симулятор" in prompt_system else 0.1
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://localhost",
        "Origin": "https://localhost",
        "X-Title": "Review Analyzer"
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API_URL.strip(), data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        error_details = e.read().decode()
        raise Exception(f"HTTP {e.code}: {error_details}")
    except Exception as e:
        raise Exception(f"Ошибка API: {str(e)}")

def generate_csv_via_llm(api_key: str):
    """Генерирует CSV файл с помощью нейросети и сохраняет его на диск."""
    print("Запрос к нейросети на генерацию CSV-данных...")
    try:
        raw_csv_content = call_llm(api_key, SYSTEM_PROMPT_GENERATE, "Сгенерируй CSV таблицу с отзывами.")
        csv_content = clean_llm_response(raw_csv_content)
        
        INPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(INPUT_CSV, "w", encoding="utf-8", newline="") as f:
            f.write(csv_content)
            
        print(f"Новый CSV-файл успешно сгенерирован и сохранен в: {INPUT_CSV}")
    except Exception as e:
        print(f"Не удалось сгенерировать CSV: {e}")
        sys.exit(1)

def run_pipeline():
    # 1. Получаем ключ (из файла или от пользователя)
    api_key = get_or_ask_api_key()

    # 2. Интерактивный выбор режима работы с CSV
    if INPUT_CSV.exists():
        print(f"Найдена существующая база отзывов: {INPUT_CSV}")
        print("1. Использовать текущий файл CSV")
        print("2. Сгенерировать новый CSV через нейросеть (старый сотрется)")
        choice = input("Выберите действие (1 или 2): ").strip()
        if choice == "2":
            generate_csv_via_llm(api_key)
    else:
        print(f"Файл {INPUT_CSV} не найден.")
        print("1. Сгенерировать структуру и данные через нейросеть")
        print("2. Выйти")
        choice = input("Выберите действие (1 или 2): ").strip()
        if choice == "1":
            generate_csv_via_llm(api_key)
        else:
            sys.exit(0)

    if not INPUT_CSV.exists():
        print(f"Файл {INPUT_CSV} отсутствует. Завершение работы.", file=sys.stderr)
        sys.exit(1)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    results = []
    errors  = []

    with open(INPUT_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows   = list(reader)

    print(f"\nЗагружено отзывов для анализа: {len(rows)}")
    print(f"Модель: {MODEL}\n")

    for i, row in enumerate(rows, 1):
        review_id   = row.get("ID") or row.get("id") or str(i)
        product     = row.get("Товар") or row.get("product") or "Неизвестный товар"
        review_text = row.get("Отзыв") or row.get("review")

        if not review_text:
            print(f"Строка {i} пропущена: отсутствует текст отзыва.")
            continue

        print(f"[{i}/{len(rows)}] #{review_id} «{product[:40]}»… ", end="", flush=True)

        try:
            raw_response = call_llm(api_key, SYSTEM_PROMPT_ANALYZE, f"Отзыв: {review_text}")
            cleaned_json = clean_llm_response(raw_response)
            llm_result = json.loads(cleaned_json)
            
            record = {
                "id": review_id,
                "product": product,
                "review_text": review_text,
                "analysis": llm_result
            }
            results.append(record)
            sentiment = llm_result.get("sentiment", "?")
            print(f"{sentiment}")
        except Exception as exc:
            print(f"Ошибка: {exc}")
            errors.append({"id": review_id, "error": str(exc)})

        if i < len(rows):
            time.sleep(3)  # Пауза для лимитов бесплатного API

    output = {
        "meta": {"model": MODEL, "total": len(rows), "success": len(results)},
        "results": results,
        "errors":  errors
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Обработка завершена! Результат сохранен в: {OUTPUT_JSON}")

if __name__ == "__main__":
    run_pipeline()

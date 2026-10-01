# Telegram Bot — Railway + PostgreSQL

Цей проєкт готовий для запуску через Railway.

## Що використовується
- Python
- aiogram 3
- PostgreSQL через `DATABASE_URL`
- Telegram Bot API через `TOKEN`

## Railway
1. Створіть GitHub repository та завантажте в нього всі файли цього проєкту.
2. У Railway створіть Project → Deploy from GitHub Repo.
3. Додайте PostgreSQL через Add → Database → PostgreSQL.
4. У Variables додайте `TOKEN` зі своїм Telegram Bot Token.
5. `DATABASE_URL` має бути підключений до сервісу бота з Railway PostgreSQL. Якщо Railway не додав його автоматично, скопіюйте значення PostgreSQL connection URL у змінну `DATABASE_URL`.
6. Deploy.

## Важливо
Не завантажуйте реальний токен у GitHub. Використовуйте тільки Railway Variables.

При першому запуску бот автоматично створить таблицю `bot_state` у PostgreSQL. Подальші зміни адміністраторів, користувачів, заявок і текстів зберігатимуться в PostgreSQL.

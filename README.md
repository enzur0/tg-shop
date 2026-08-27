# Bot magazin Telegram

## Lansare pe Windows

1. Instaleaza Python 3.11 sau mai nou.
2. Creeaza mediul virtual daca nu exista:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Completeaza `.env` folosind `.env.example`:
   - `BOT_TOKEN` — tokenul primit de la BotFather;
   - `ADMIN_IDS` — ID-urile Telegram ale administratorilor, separate prin virgula;
   - `STORE_NAME` — numele magazinului.
4. Porneste `start_bot.bat` sau ruleaza:

   ```powershell
   .\.venv\Scripts\python.exe bot.py
   ```

La pornire se initializeaza baza de date si se creeaza un backup SQLite in `backups/`.
Nu publica `.env`, `shop.db`, `backups/` sau logurile.

## Lansare pe Railway

1. Creeaza un proiect nou pe Railway si conecteaza repository-ul GitHub.
2. In Railway, la **Variables**, adauga:

   ```text
   BOT_TOKEN=tokenul_de_la_BotFather
   ADMIN_IDS=123456789,987654321
   STORE_NAME=Numele magazinului
   DATABASE_URL=sqlite+aiosqlite:////data/shop.db
   BACKUP_DIR=/data/backups
   ```

3. Adauga un **Volume** Railway montat la `/data`. Acesta pastreaza baza de date si backupurile la redeploy.
4. Railway va detecta proiectul Python cu Railpack, va instala dependentele din `requirements.txt` si va porni serviciul cu `python bot.py`.
5. Verifica logurile serviciului: trebuie sa apara `Bot started successfully` si `Start polling`.

Acesta este un worker Telegram si nu are nevoie de variabila `PORT` sau de un endpoint web.

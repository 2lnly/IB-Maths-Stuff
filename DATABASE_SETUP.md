# Database Setup Guide

## Overview

The application now supports **dual database modes**:
- **SQLite** for local development (automatic, no setup needed)
- **PostgreSQL** for production on Render (requires setup)

## How It Works

The app automatically detects which database to use:
- If `DATABASE_URL` environment variable exists → **PostgreSQL**
- Otherwise → **SQLite** (local file: `web/users.db`)

## Local Development (SQLite)

✅ **No setup required!**

The app automatically creates `web/users.db` when you run it locally.

```bash
cd web
python3 app.py
```

Your user accounts and saved questions are stored in `web/users.db` (ignored by git).

## Production Setup (Render + PostgreSQL)

### Step 1: Create PostgreSQL Database on Render

1. Go to your [Render Dashboard](https://dashboard.render.com/)
2. Click **"New +"** → **"PostgreSQL"**
3. Configure:
   - **Name**: `ib-practice-db` (or your choice)
   - **Database**: `ib_practice`
   - **User**: Auto-generated
   - **Region**: Choose closest to your web service
   - **Plan**: **Free** (or paid for better performance)
4. Click **"Create Database"**
5. Wait for it to deploy (~2 minutes)

### Step 2: Connect Web Service to Database

1. Go to your **Web Service** on Render
2. Click **"Environment"** in the left sidebar
3. Add new environment variable:
   - **Key**: `DATABASE_URL`
   - **Value**: Copy the **Internal Database URL** from your PostgreSQL service
     - It looks like: `postgres://user:password@host/database`
4. Click **"Save Changes"**
5. Your web service will automatically redeploy

### Step 3: Verify It Works

1. Wait for the deploy to finish
2. Visit your site and try to register an account
3. If it works, your PostgreSQL is connected! ✅

### Step 4: Monitor Your Database

On the PostgreSQL service page, you can:
- View connection info
- See disk usage (Free tier: 100MB)
- Monitor active connections
- Access via `psql` for debugging

## Database Schema

The app automatically creates these tables:

### `users`
```sql
id SERIAL PRIMARY KEY
username TEXT UNIQUE NOT NULL
password TEXT NOT NULL
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

### `question_history`
```sql
id SERIAL PRIMARY KEY
user_id INTEGER (→ users.id)
question_id TEXT
subject TEXT
viewed_at TIMESTAMP
UNIQUE(user_id, question_id, subject)
```

### `saved_questions`
```sql
id SERIAL PRIMARY KEY
user_id INTEGER (→ users.id)
question_id TEXT
subject TEXT
notes TEXT
saved_at TIMESTAMP
UNIQUE(user_id, question_id, subject)
```

## Migrating Data (Optional)

If you have local SQLite data you want to move to production:

### Export from SQLite:
```bash
sqlite3 web/users.db .dump > backup.sql
```

### Import to PostgreSQL:
1. Connect to your Render PostgreSQL:
   ```bash
   psql <your-external-database-url>
   ```
2. Run the SQL commands (may need editing for PostgreSQL syntax)

## Troubleshooting

### ❌ "relation does not exist" error
- Tables weren't created. Restart the web service to run init_database()

### ❌ Users can't register
- Check DATABASE_URL is set correctly
- Check PostgreSQL service is running
- Check the Internal Database URL (not External)

### ❌ "too many connections"
- Free tier has connection limits
- Consider upgrading or adding connection pooling

### ❌ Data disappears after deploy
- Using SQLite in production (ephemeral storage)
- Must use PostgreSQL with DATABASE_URL env var

## Files

- **`web/database.py`** - Database abstraction layer
- **`web/auth.py`** - User authentication
- **`web/user_data.py`** - Question history and saved questions
- **`web/users.db`** - Local SQLite file (git ignored)

## Cost

- **PostgreSQL Free Tier**:
  - 100MB storage
  - Expires after 90 days (unless upgraded)
  - Automatic backups not included

- **Paid Tier** ($7/month):
  - 1GB storage
  - Daily backups
  - Better performance

## Security Notes

- ⚠️ **Never commit `users.db` to git** (now in .gitignore)
- ⚠️ **Never expose DATABASE_URL publicly**
- ⚠️ **Change `app.secret_key` in production**
- ✅ Use environment variables for sensitive data

## Quick Reference

| Environment | Database | Location |
|-------------|----------|----------|
| Local | SQLite | `web/users.db` |
| Render | PostgreSQL | Render hosted |

| Environment Variable | Purpose |
|---------------------|---------|
| `DATABASE_URL` | PostgreSQL connection (production) |
| (none) | Use SQLite (development) |

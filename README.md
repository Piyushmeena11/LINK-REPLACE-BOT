# 🤖 Telegram HTML Button Editor Bot

A private Telegram bot to manually edit Telegram links in HTML files.

## Features
✅ Owner-only access  
✅ Multi-file support  
✅ Inline button editing  
✅ Duplicate detection  
✅ Link validation  
✅ Session timeout (10 min)  
✅ Render deployment ready  

## Deployment on Render

### Step 1: Get Bot Token
1. Open [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow instructions
3. Copy your bot token

### Step 2: Get Your User ID
1. Open [@userinfobot](https://t.me/userinfobot)
2. Send any message
3. Copy your numeric ID

### Step 3: Deploy on Render
1. Push code to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com/)
3. Click **New** → **Web Service**
4. Connect your GitHub repo
5. Set these environment variables:
   - `BOT_TOKEN` = your bot token
   - `OWNER_ID` = your user ID
   - `RENAME_TAG` = _edited
6. Click **Create Web Service**

### Step 4: Test Your Bot
1. Open your bot on Telegram
2. Send `/start`
3. Upload HTML files
4. Type `/done` and start editing!

## Commands
- `/start` - Start new session
- `/help` - Show help
- `/done` - Finish uploading files
- `/cancel` - Cancel session

## Security
Only the owner (OWNER_ID) can use this bot. Others will see "Not authorized" message.

## Support
For issues, check logs in Render dashboard.

# Teams Webhook to Database Flow

Complete step-by-step guide to register a Teams webhook and capture messages in your database.

## Prerequisites

- Azure AD App Registration with Teams read permissions
- `CLIENT_ID`, `CLIENT_SECRET`, `TENANT_ID` from Azure AD
- Deployed app at `https://teamspoc.onrender.com`

---

## **STEP 1: Create a Subscription (Register the Webhook)**

### Via Swagger UI

1. Open https://teamspoc.onrender.com/docs
2. Click **POST** `/subscriptions`
3. Click **"Try it out"**
4. Enter the request body:

   ```json
   {
     "resource": "teams/{teamId}/channels/{channelId}/messages",
     "expiration_hours": 4320
   }
   ```

   Replace `{teamId}` and `{channelId}` with actual Teams IDs.

5. Click **"Execute"**
6. **Expected Response** (201 Created):
   ```json
   {
     "id": "sub-123xyz",
     "resource": "teams/team-id/channels/channel-id/messages",
     "notificationUrl": "https://teamspoc.onrender.com/graph-webhook",
     "expirationDateTime": "2026-01-25T12:38:00Z",
     "clientState": "your-secret-client-state"
   }
   ```
7. **Save the subscription ID** - you'll need it later.

### Via cURL

```bash
curl -X POST https://teamspoc.onrender.com/subscriptions \
  -H "Content-Type: application/json" \
  -d '{
    "resource": "teams/{teamId}/channels/{channelId}/messages",
    "expiration_hours": 4320
  }'
```

---

## **STEP 2: Test the Webhook (Manual Notification)**

This simulates Microsoft Graph sending a notification.

### Via Swagger UI

1. Open https://teamspoc.onrender.com/docs
2. Click **POST** `/test-notification`
3. Click **"Try it out"**
4. Enter the request body:

   ```json
   {
     "subscriptionId": "sub-123xyz",
     "clientState": "your-secret-client-state",
     "changeType": "created",
     "resource": "teams/team-id/channels/channel-id/messages/msg-id",
     "resourceData": {
       "@odata.type": "#Microsoft.Graph.chatMessage",
       "@odata.id": "teams/team-id/channels/channel-id/messages/msg-id",
       "id": "msg-id-12345"
     },
     "tenantId": "your-tenant-id"
   }
   ```

   **Important:** Ensure `clientState` matches your `CLIENT_STATE_SECRET` in `.env`

5. Click **"Execute"**
6. **Expected Response** (200 OK):
   ```json
   {
     "status": "accepted",
     "notification_id": 1
   }
   ```

### Via cURL

```bash
curl -X POST https://teamspoc.onrender.com/test-notification \
  -H "Content-Type: application/json" \
  -d '{
    "subscriptionId": "sub-123xyz",
    "clientState": "your-secret-client-state",
    "changeType": "created",
    "resource": "teams/team-id/channels/channel-id/messages/msg-id",
    "resourceData": {
      "@odata.type": "#Microsoft.Graph.chatMessage",
      "@odata.id": "teams/team-id/channels/channel-id/messages/msg-id",
      "id": "msg-id-12345"
    },
    "tenantId": "your-tenant-id"
  }'
```

---

## **STEP 3: Retrieve Messages from Database**

Once messages are ingested, retrieve them.

### Get All Messages

**Via Swagger UI:**

1. Open https://teamspoc.onrender.com/docs
2. Click **GET** `/messages`
3. Click **"Try it out"**
4. (Optional) Set `limit` parameter (default 50, max 500)
5. Click **"Execute"**
6. **Expected Response** (200 OK):
   ```json
   {
     "count": 1,
     "messages": [
       {
         "id": 1,
         "message_id": "msg-id-12345",
         "normalized_json": {
           "content": "Hello team!",
           "from": "user@example.com",
           ...
         },
         "raw_json": { ... },
         "ingested_at": "2026-01-17T12:38:00Z"
       }
     ]
   }
   ```

**Via cURL:**

```bash
curl https://teamspoc.onrender.com/messages?limit=10
```

### Get Specific Message

**Via Swagger UI:**

1. Open https://teamspoc.onrender.com/docs
2. Click **GET** `/messages/{message_id}`
3. Click **"Try it out"**
4. Enter `message_id`: `msg-id-12345`
5. Click **"Execute"**
6. **Expected Response** (200 OK):
   ```json
   {
     "id": 1,
     "message_id": "msg-id-12345",
     "normalized_json": { ... },
     "raw_json": { ... },
     "ingested_at": "2026-01-17T12:38:00Z"
   }
   ```

**Via cURL:**

```bash
curl https://teamspoc.onrender.com/messages/msg-id-12345
```

---

## **STEP 4: Real-time Flow (Graph → Webhook → Database)**

Once the subscription is created, Microsoft Graph will automatically send notifications:

1. **User posts a message in Teams** →
2. **Microsoft Graph detects the change** →
3. **Graph sends POST to** `https://teamspoc.onrender.com/graph-webhook` →
4. **App validates and queues the notification** →
5. **Background worker fetches the message from Graph API** →
6. **Worker normalizes and stores in database** →
7. **You can retrieve via GET** `/messages`

**Real-time Status:**

- Check `/health` to verify worker is running
- Check Render logs for background worker activity
- Query `/messages` to see newly stored messages

---

## **STEP 5: List & Delete Subscriptions**

### List All Subscriptions

**Via Swagger UI:**

1. Click **GET** `/subscriptions`
2. Click **"Execute"**

**Via cURL:**

```bash
curl https://teamspoc.onrender.com/subscriptions
```

### Delete a Subscription

**Via Swagger UI:**

1. Click **DELETE** `/subscriptions/{subscription_id}`
2. Enter the subscription ID
3. Click **"Execute"**

**Via cURL:**

```bash
curl -X DELETE https://teamspoc.onrender.com/subscriptions/sub-123xyz
```

---

## **Health Checks**

### Check App Status

```bash
curl https://teamspoc.onrender.com/
```

Response: `{"status":"running","service":"Teams Message Webhook MVP"}`

### Check Detailed Health

```bash
curl https://teamspoc.onrender.com/health
```

Response: `{"status":"healthy","database":"connected","worker":"running"}`

---

## **Troubleshooting**

| Issue                              | Solution                                                           |
| ---------------------------------- | ------------------------------------------------------------------ |
| 400 error on POST `/graph-webhook` | Ensure request body is valid JSON and `clientState` matches `.env` |
| 500 error on subscription creation | Check Azure AD credentials in `.env` are correct                   |
| Messages not appearing in DB       | Verify background worker is running (check `/health`)              |
| Subscription validation fails      | Ensure `notificationUrl` is accessible from internet               |

---

## **Database Schema**

### Messages Table

```sql
CREATE TABLE messages (
  id INTEGER PRIMARY KEY,
  message_id VARCHAR(255) UNIQUE NOT NULL,
  normalized_json TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  ingested_at DATETIME DEFAULT NOW()
)
```

### Notifications Table (Internal)

```sql
CREATE TABLE notifications (
  id INTEGER PRIMARY KEY,
  subscription_id VARCHAR(255) NOT NULL,
  resource VARCHAR(500) NOT NULL,
  payload_json TEXT NOT NULL,
  status VARCHAR(50) DEFAULT 'pending',
  created_at DATETIME DEFAULT NOW(),
  attempts INTEGER DEFAULT 0,
  error_message TEXT
)
```

---

## **Environment Variables**

Ensure your `.env` has these set:

```
TENANT_ID=your-tenant-id
CLIENT_ID=your-client-id
CLIENT_SECRET=your-client-secret
NGROK_URL=https://teamspoc.onrender.com
CLIENT_STATE_SECRET=your-secret-client-state
DB_PATH=sqlite:///./teams_mvp.db
```

---

**Happy webhook testing! 🚀**

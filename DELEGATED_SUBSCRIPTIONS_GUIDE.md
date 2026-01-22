# Delegated Channel Subscriptions Guide

## ✅ NO ADMIN CONSENT NEEDED!

This guide shows how to create webhook subscriptions for Teams channels using **delegated permissions** - meaning each user can subscribe to channels they're a member of, without requiring admin approval.

---

## How It Works

```
1. User logs in via OAuth (grants ChannelMessage.Read)
   ↓
2. User is a member of certain Teams/channels
   ↓
3. Create subscription for those channels using user's token
   ↓
4. Microsoft Graph sends webhook notifications
   ↓
5. Your app receives real-time message notifications
   ↓
6. Background worker processes and stores messages
```

**Key Point:** Subscription is scoped to channels the user can already access. No elevated permissions needed!

---

## Prerequisites

### 1. Azure AD Delegated Permissions

Ensure your app has these **delegated** permissions:

- ✅ `ChannelMessage.Read` - Read channel messages
- ✅ `Chat.Read` - Read chats (optional, for personal messages)
- ✅ `User.Read` - Read user profile
- ✅ `offline_access` - Refresh tokens

**All are user-consentable - NO admin approval needed!**

### 2. User Must Be Logged In

User needs to complete OAuth flow first:

```
Visit: https://teamspoc.onrender.com/auth/login
```

---

## Getting Channel IDs from Teams URL

### Example Teams URL:

```
https://teams.microsoft.com/l/team/19%3A8iOSOoNEa8vKLEexZ9bSVbrTQwt7wQ1Bkqq5rUWTs1Q1%40thread.tacv2/conversations?groupId=7e3768a7-4441-4d8e-bbad-208e1ff23e1d&tenantId=634afd4b-c03a-4ec7-bcbb-88ea55db47ac
```

### Extract IDs:

**Team ID (groupId):**

```
7e3768a7-4441-4d8e-bbad-208e1ff23e1d
```

**Channel ID (URL decoded from path):**

```
19:8iOSOoNEa8vKLEexZ9bSVbrTQwt7wQ1Bkqq5rUWTs1Q1@thread.tacv2
```

**Alternative:** Use Graph API to list channels:

```bash
# Get all teams user is a member of
GET /me/joinedTeams

# Get channels in a specific team
GET /teams/{team-id}/channels
```

---

## Creating a Subscription

### Method 1: Via Frontend UI

1. **Login:**
   - Visit: `https://teamspoc.onrender.com/ui`
   - Click "Login with Microsoft"
   - Grant permissions

2. **Create Subscription:**
   - Go to "Channel Subscriptions" section
   - Enter Team ID: `7e3768a7-4441-4d8e-bbad-208e1ff23e1d`
   - Enter Channel ID: `19:8iOSOoNEa8vKLEexZ9bSVbrTQwt7wQ1Bkqq5rUWTs1Q1@thread.tacv2`
   - Expiration: `4320` hours (6 months)
   - Click "Create My Channel Subscription"

3. **Expected Response:**

```json
{
  "status": "success",
  "message": "Subscription created with your delegated permissions",
  "subscription": {
    "id": "abc123...",
    "resource": "/teams/7e3768a7-.../channels/19:8iO.../messages",
    "notificationUrl": "https://teamspoc.onrender.com/graph-webhook",
    "expirationDateTime": "2026-07-23T12:00:00Z"
  }
}
```

### Method 2: Via API (curl)

```bash
# Replace YOUR_USER_ID with your actual user_id from login
curl -X POST "https://teamspoc.onrender.com/api/user/subscriptions?user_id=YOUR_USER_ID&team_id=7e3768a7-4441-4d8e-bbad-208e1ff23e1d&channel_id=19:8iOSOoNEa8vKLEexZ9bSVbrTQwt7wQ1Bkqq5rUWTs1Q1@thread.tacv2&expiration_hours=4320"
```

### Method 3: Via Python

```python
import requests

# After user logs in, you have their user_id
user_id = "b37273df-c818-42ce-9b89-4a9a3c326406"

# Create subscription
response = requests.post(
    "https://teamspoc.onrender.com/api/user/subscriptions",
    params={
        "user_id": user_id,
        "team_id": "7e3768a7-4441-4d8e-bbad-208e1ff23e1d",
        "channel_id": "19:8iOSOoNEa8vKLEexZ9bSVbrTQwt7wQ1Bkqq5rUWTs1Q1@thread.tacv2",
        "expiration_hours": 4320
    }
)

subscription = response.json()
print(f"Subscription ID: {subscription['subscription']['id']}")
```

---

## Testing the Subscription

### 1. Send a Test Message

1. Open Teams
2. Go to the channel you subscribed to
3. Send a message: "Test webhook notification"

### 2. Check Webhook Was Received

**View Render logs:**

```
https://dashboard.render.com/web/your-service/logs
```

**Look for:**

```
Webhook notification received
Processing notification 1
Successfully processed notification 1, message msg-123
```

### 3. Verify Message Was Stored

**Via API:**

```bash
curl https://teamspoc.onrender.com/messages?limit=10
```

**Via UI:**

- Click "List Stored Messages"
- Should see your test message!

---

## Managing Subscriptions

### List All Subscriptions (Application-level)

```bash
curl https://teamspoc.onrender.com/subscriptions
```

**Note:** This lists subscriptions created with application permissions. Delegated subscriptions are also included.

### Delete a Subscription

```bash
curl -X DELETE https://teamspoc.onrender.com/subscriptions/{subscription-id}
```

---

## Subscription Lifecycle

### Expiration

**Max expiration for channel messages:** 43,200 minutes (~30 days for channels)

For longer monitoring:

- Set `expiration_hours: 4320` (6 months) - this works for `/chats` resources
- For channels, you may need to renew more frequently

### Renewal

Before subscription expires, renew it:

```bash
curl -X PATCH https://graph.microsoft.com/v1.0/subscriptions/{subscription-id} \
  -H "Authorization: Bearer {user-token}" \
  -d '{"expirationDateTime": "2026-07-23T12:00:00Z"}'
```

**Future Enhancement:** Auto-renewal before expiration (coming soon!)

---

## How Messages Flow

### Real-Time Flow

```
1. User sends message in Teams channel
   ↓
2. Microsoft Graph detects change
   ↓
3. Graph POST to /graph-webhook:
   {
     "value": [{
       "subscriptionId": "abc123",
       "resource": "teams/.../channels/.../messages/msg-456",
       "changeType": "created"
     }]
   }
   ↓
4. Your app validates clientState
   ↓
5. Notification saved to DB (status: pending)
   ↓
6. Background worker picks up notification
   ↓
7. Worker fetches full message:
   GET /teams/{team-id}/channels/{channel-id}/messages/{msg-id}
   ↓
8. Worker normalizes message
   ↓
9. Message saved to messages table
   ↓
10. Available via GET /messages
```

### Latency

- **Webhook notification:** <1 second
- **Worker processing:** 1-5 seconds
- **Total latency:** ~2-6 seconds (near real-time!)

---

## Subscribing to Multiple Channels

### Per-User, Per-Channel

Each user can create subscriptions for multiple channels:

```python
channels = [
    ("team-1", "channel-A"),
    ("team-1", "channel-B"),
    ("team-2", "channel-C"),
]

for team_id, channel_id in channels:
    create_subscription(user_id, team_id, channel_id)
```

### Auto-Subscribe to All User's Channels

**Future Enhancement:** Add endpoint to automatically subscribe to all channels user is a member of:

```python
# Pseudo-code (to be implemented)
@app.post("/api/user/subscriptions/auto")
async def auto_subscribe_all_channels(user_id: str):
    # 1. Get all teams: GET /me/joinedTeams
    # 2. For each team: GET /teams/{id}/channels
    # 3. For each channel: Create subscription
    # 4. Return list of created subscriptions
```

---

## Troubleshooting

### Error: "User not authenticated"

**Solution:** User needs to login first:

```
Visit: https://teamspoc.onrender.com/auth/login
```

### Error: "Token expired"

**Solution:** Token expired, user needs to re-login (or token will auto-refresh if refresh_token is valid).

### Error: "Insufficient privileges"

**Possible causes:**

1. User is NOT a member of that channel → Can only subscribe to channels they belong to
2. Missing `ChannelMessage.Read` permission in Azure AD
3. User hasn't granted consent yet → Re-login to grant new permissions

**Verify user has access:**

```bash
# Check if user can read the channel
GET /teams/{team-id}/channels/{channel-id}/messages
# Should return messages, not 403
```

### Error: "Subscription validation timeout"

**Rare:** Should not happen on Render (US servers).

**Solution:**

1. Check Render logs for any errors
2. Verify `/graph-webhook` is responding correctly
3. Test: `curl "https://teamspoc.onrender.com/graph-webhook?validationToken=test"`
   - Should return: `test` (plain text, 200 OK)

### No Notifications Arriving

**Debug Steps:**

1. **Verify subscription is active:**

   ```bash
   curl https://teamspoc.onrender.com/subscriptions
   # Check expirationDateTime hasn't passed
   ```

2. **Check Render logs for webhook POST:**
   - Should see: `Webhook notification received` when message sent

3. **Verify worker is running:**

   ```bash
   curl https://teamspoc.onrender.com/health
   # Should show: "worker": "running"
   ```

4. **Check database for pending notifications:**

   ```sql
   SELECT * FROM notifications WHERE status = 'pending';
   ```

5. **Check for errors in worker:**
   - Render logs should show: `Successfully processed notification X`
   - If errors, will show: `Failed to process notification X: <error>`

---

## Comparison: Delegated vs Application Subscriptions

| Feature              | Delegated (This Guide)          | Application (Admin Required) |
| -------------------- | ------------------------------- | ---------------------------- |
| **Admin Consent**    | ❌ Not needed                   | ✅ Required                  |
| **Scope**            | Channels user belongs to        | ALL channels/chats in org    |
| **Permission Type**  | ChannelMessage.Read (delegated) | Chat.Read.All (application)  |
| **Who Can Create**   | Any logged-in user              | Only after admin approval    |
| **Use Case**         | Per-user monitoring             | Org-wide monitoring          |
| **Latency**          | Real-time (<5 sec)              | Real-time (<5 sec)           |
| **Setup Complexity** | Simple (user login)             | Complex (admin approval)     |

---

## Rate Limits

**Microsoft Graph API Limits:**

- 20,000 requests per hour per application
- Applies to both delegated and application tokens

**Webhook Notifications:**

- No limit on receiving notifications
- Limit applies to fetching full message content

**With Delegated Subscriptions:**

- Each notification → 1 API call to fetch message
- 20,000 notifications/hour supported
- More than enough for most use cases!

---

## Security Considerations

### Client State Validation

All webhooks validate `clientState` matches your secret:

```python
CLIENT_STATE_SECRET=XTDptyck73GaHTzPl1DZkDCdUT4exgfQy6+36IYn0yI=
```

**This prevents:**

- Unauthorized webhook posts
- Replay attacks
- Spoofed notifications

### Token Security

- User tokens stored server-side (in-memory)
- Never exposed to frontend
- Auto-refresh when expired
- HttpOnly cookies for state (CSRF protection)

### HTTPS Required

- Microsoft Graph only sends webhooks to HTTPS endpoints
- Render.com provides free SSL certificates
- All communication encrypted

---

## Next Steps

1. **✅ Update Azure AD permissions** (add ChannelMessage.Read)
2. **✅ Update OAuth scopes in code** (already done above)
3. **✅ Deploy updated code to Render**
4. **✅ Users login via OAuth**
5. **✅ Create subscriptions for their channels**
6. **✅ Receive real-time message notifications!**

---

## Support

**Issues?**

1. Check Render logs: `https://dashboard.render.com/web/your-service/logs`
2. Test webhook endpoint: `curl "https://teamspoc.onrender.com/graph-webhook?validationToken=test"`
3. Verify user is logged in: `curl "https://teamspoc.onrender.com/api/user/profile?user_id=USER_ID"`

**Questions?**

- Review Microsoft Graph docs: https://learn.microsoft.com/en-us/graph/webhooks
- Check subscription resource paths: https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions

---

**✅ You now have real-time webhooks without admin consent!**

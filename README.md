# Microsoft Teams Webhook Listener

Enterprise-grade FastAPI application for receiving Microsoft Teams/Chats change notifications via webhooks with comprehensive subscription management capabilities.

## Overview

This application enables real-time monitoring of Microsoft Teams and Chats through the Microsoft Graph API change notification system. It provides a production-ready webhook endpoint, RESTful subscription management, asynchronous message processing, and persistent storage.

**Key Capabilities:**

- 🔔 Real-time change notification processing from Microsoft Graph
- 🔄 Full subscription lifecycle management (create, list, delete)
- 💬 Support for both Teams channels and 1-on-1 chats
- 🗄️ SQLite persistence with async background processing
- 🔐 OAuth2 client credentials flow with automatic token refresh

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   Microsoft Graph API                     │
│              (Change Notifications Service)               │
└───────────────────────────┬──────────────────────────────┘
                            │
                            │ HTTPS POST (webhook notification)
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│              FastAPI Application (Port 8000)              │
│                                                            │
│  ┌──────────────────────────────────────────────────┐   │
│  │         Webhook Endpoint (/graph-webhook)         │   │
│  │  • Validates subscription lifecycle events        │   │
│  │  • Queues notifications for processing            │   │
│  └────────────────────┬─────────────────────────────┘   │
│                       │                                    │
│                       ▼                                    │
│  ┌──────────────────────────────────────────────────┐   │
│  │      Subscription Management API                  │   │
│  │  • POST /subscriptions (create)                   │   │
│  │  • GET /subscriptions (list)                      │   │
│  │  • DELETE /subscriptions/{id} (remove)            │   │
│  └──────────────────────────────────────────────────┘   │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│              Background Async Worker                      │
│  • Processes notification queue                          │
│  • Fetches full message content from Graph API           │
│  • Normalizes and stores messages                        │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│                    SQLite Database                        │
│  • notifications: Raw Graph notifications                │
│  • messages: Normalized message content                  │
└──────────────────────────────────────────────────────────┘
```

## ⚠️ Critical Known Limitation

**Local Development Constraint:** Microsoft Graph requires webhook validation responses within **10 seconds**. When running locally with tunnel services (ngrok, Cloudflare Tunnel) from high-latency regions (e.g., India → USA), network round-trip time often exceeds 30 seconds, causing validation failures.

**Symptoms:**

- `400 Bad Request` with `"code": "Subscription_ValidationTimeOut"`
- Webhook responds correctly but response arrives too late at Microsoft's servers
- Subscription creation fails despite correct permissions and configuration

**Solutions:**

1. **Recommended:** Deploy to cloud (US/Europe region) - Render, Railway, Azure App Service
2. **Hybrid:** Use cloud webhook + local polling for development
3. **Testing:** Use `/subscriptions` API to verify subscription logic without creation

See `LATENCY_PROBLEM.md` for detailed analysis with network diagrams.

## Prerequisites

### Azure AD Application Setup

1. **Register Application** in Azure Portal:

   - Navigate to Azure Active Directory → App registrations → New registration
   - Note the `Application (client) ID` and `Directory (tenant) ID`

2. **Create Client Secret**:

   - Certificates & secrets → New client secret
   - Copy the secret **value** (not the ID)

3. **Configure API Permissions** (Application permissions, **not** Delegated):

   - Microsoft Graph → Application permissions:
     - `Chat.Read.All`
     - `ChatMessage.Read.All`
     - `ChannelMessage.Read.All`
   - Grant admin consent for your organization

4. **Public Webhook URL**:
   - Must be publicly accessible over HTTPS
   - Format: `https://your-domain.com/graph-webhook`
   - For local testing: Use ngrok/Cloudflare Tunnel (note latency limitations above)

## Installation

### 1. Clone Repository

```bash
git clone <repository-url>
cd webhookTeams
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Create `.env` file in project root:

```env
# Azure AD Credentials
TENANT_ID=your-tenant-id-here
CLIENT_ID=your-client-id-here
CLIENT_SECRET=your-client-secret-here

# Webhook Configuration
NOTIFICATION_URL=https://your-public-domain.com/graph-webhook

# Database (optional, defaults to sqlite:///./teams_mvp.db)
DATABASE_URL=sqlite:///./teams_mvp.db
```

## Usage

### Start Application

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Endpoints:**

- API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### API Examples

#### 1. Create Subscription

**Subscribe to Teams Channel:**

```bash
curl -X POST "http://localhost:8000/subscriptions" \
  -H "Content-Type: application/json" \
  -d '{
    "resource": "/teams/{team-id}/channels/{channel-id}/messages",
    "expiration_hours": 24
  }'
```

**Subscribe to 1-on-1 Chat:**

```bash
curl -X POST "http://localhost:8000/subscriptions" \
  -H "Content-Type: application/json" \
  -d '{
    "resource": "/chats/{chat-id}/messages",
    "expiration_hours": 24
  }'
```

**Subscribe to All Accessible Chats** (requires Teams Premium):

```bash
curl -X POST "http://localhost:8000/subscriptions" \
  -H "Content-Type: application/json" \
  -d '{
    "resource": "/chats/getAllMessages",
    "expiration_hours": 168
  }'
```

**Response:**

```json
{
  "id": "3c3c3c3c-3c3c-3c3c-3c3c-3c3c3c3c3c3c",
  "resource": "/chats/19:xxx/messages",
  "changeType": "created",
  "notificationUrl": "https://your-domain.com/graph-webhook",
  "expirationDateTime": "2024-01-15T10:30:00Z",
  "clientState": "SecretClientState"
}
```

#### 2. List Active Subscriptions

```bash
curl http://localhost:8000/subscriptions
```

**Response:**

```json
{
  "subscriptions": [
    {
      "id": "3c3c3c3c-3c3c-3c3c-3c3c-3c3c3c3c3c3c",
      "resource": "/chats/19:xxx/messages",
      "changeType": "created",
      "notificationUrl": "https://your-domain.com/graph-webhook",
      "expirationDateTime": "2024-01-15T10:30:00Z"
    }
  ]
}
```

#### 3. Delete Subscription

```bash
curl -X DELETE "http://localhost:8000/subscriptions/{subscription-id}"
```

**Response:**

```json
{
  "message": "Subscription deleted successfully"
}
```

### Helper Scripts

#### Get Available Chat IDs

```bash
python scripts/get_chat_ids.py
```

Lists all accessible chats with IDs and display names for subscription targeting.

#### Create Subscription via CLI

```bash
python scripts/create_subscription.py \
  --resource "/chats/{chat-id}/messages" \
  --expiration-hours 24
```

## Configuration

### Subscription Resources

| Resource Path                        | Description                | Max Expiration         |
| ------------------------------------ | -------------------------- | ---------------------- |
| `/teams/{id}/channels/{id}/messages` | Team channel messages      | 43200 minutes          |
| `/chats/{id}/messages`               | Specific 1-on-1/group chat | 4230 hours (~6 months) |
| `/chats/getAllMessages`              | All accessible chats       | 4230 hours             |

### Environment Variables

| Variable           | Description              | Required | Default                    |
| ------------------ | ------------------------ | -------- | -------------------------- |
| `TENANT_ID`        | Azure AD tenant ID       | Yes      | -                          |
| `CLIENT_ID`        | Application (client) ID  | Yes      | -                          |
| `CLIENT_SECRET`    | Client secret value      | Yes      | -                          |
| `NOTIFICATION_URL` | Public webhook HTTPS URL | Yes      | -                          |
| `DATABASE_URL`     | SQLite connection string | No       | `sqlite:///./teams_mvp.db` |

## Database Schema

### Notifications Table

Stores raw Graph notifications before processing.

```sql
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY,
    subscription_id VARCHAR,
    resource VARCHAR,
    change_type VARCHAR,  -- created, updated, deleted
    client_state VARCHAR,
    raw_data JSON,
    processed BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Messages Table

Stores normalized, processed messages.

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    message_id VARCHAR UNIQUE,  -- Graph API message ID
    chat_id VARCHAR,
    sender_name VARCHAR,
    sender_email VARCHAR,
    content TEXT,  -- HTML content
    created_at DATETIME
);
```

## Development

### Project Structure

```
webhookTeams/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, endpoints, lifespan
│   ├── graph_client.py      # Graph API client, OAuth2, retry logic
│   ├── subscription.py      # Subscription management wrappers
│   ├── schema.py            # Pydantic models (request/response)
│   ├── storage.py           # SQLAlchemy database operations
│   ├── worker.py            # Background async notification processor
│   └── utils.py             # Validation, logging utilities
├── scripts/
│   ├── create_subscription.py  # CLI subscription creation
│   └── get_chat_ids.py         # List available chats
├── tests/
│   ├── conftest.py          # Pytest fixtures
│   ├── test_normalize.py    # Message normalization tests
│   └── test_subscription.py # Subscription logic tests
├── examples/
│   ├── sample_notification.json  # Example Graph notification
│   └── sample_message_response.json  # Example Graph message
├── .env.example             # Environment template
├── requirements.txt         # Python dependencies
├── pyproject.toml          # Project metadata
└── README.md               # This file
```

### Running Tests

```bash
pytest tests/ -v
```

### Code Formatting

```bash
black app/ scripts/ tests/
```

## Deployment

### Cloud Deployment (Recommended)

**Why Cloud:** Eliminates network latency issues for <10s validation requirement.

#### Render

1. Connect GitHub repository
2. Add environment variables (TENANT_ID, CLIENT_ID, etc.)
3. Set start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Deploy to US/Europe region

#### Railway

1. New Project → Deploy from GitHub
2. Add variables in Variables tab
3. Railway auto-detects Python and installs dependencies
4. Use generated domain for NOTIFICATION_URL

#### Azure App Service

1. `az webapp up --name teams-webhook --runtime "PYTHON:3.11"`
2. Configure app settings with Azure AD credentials
3. Native integration with Azure AD for easier auth

### Docker Deployment

**Dockerfile:**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Build & Run:**

```bash
docker build -t teams-webhook .
docker run -p 8000:8000 --env-file .env teams-webhook
```

### Production Checklist

- [ ] Use PostgreSQL instead of SQLite for concurrent writes
- [ ] Enable HTTPS (required by Microsoft Graph)
- [ ] Implement subscription auto-renewal before expiration
- [ ] Add authentication to `/subscriptions` endpoints (API keys/OAuth)
- [ ] Set up monitoring (health checks, error tracking)
- [ ] Configure proper logging (structured JSON logs)
- [ ] Use secret management (Azure Key Vault, AWS Secrets Manager)
- [ ] Set up database backups
- [ ] Implement rate limiting on public endpoints
- [ ] Deploy to region close to Microsoft Graph servers (US/Europe)

## Troubleshooting

### Subscription Creation Fails with Timeout

**Error:** `400 Bad Request - Subscription_ValidationTimeOut`

**Cause:** Webhook validation response took >10 seconds to reach Microsoft servers.

**Solutions:**

1. Deploy to cloud platform (Render, Railway, Azure) in US/Europe region
2. Check tunnel service latency: `curl -w "@curl-format.txt" -o /dev/null https://your-ngrok-url.com/graph-webhook`
3. Verify webhook responds correctly: `curl https://your-url.com/graph-webhook?validationToken=test` should return `test`

### Missing Permissions Error

**Error:** `403 Forbidden - Insufficient privileges`

**Fix:**

1. Verify Azure AD app has **Application** permissions (not Delegated):
   - Chat.Read.All
   - ChatMessage.Read.All
   - ChannelMessage.Read.All
2. Ensure admin consent granted (check Azure Portal → API permissions)
3. Wait 5-10 minutes after granting consent for propagation

### No Notifications Received

**Debugging Steps:**

1. Check subscription status: `curl http://localhost:8000/subscriptions`
2. Verify expiration hasn't passed
3. Check FastAPI logs for incoming webhook requests
4. Test webhook directly: `curl -X POST https://your-url.com/graph-webhook -H "Content-Type: application/json" -d '{"value":[]}'`
5. Ensure notification URL matches subscription

### Token Authentication Errors

**Error:** `401 Unauthorized - InvalidAuthenticationToken`

**Fix:**

1. Verify CLIENT_SECRET hasn't expired (Azure Portal → Certificates & secrets)
2. Check TENANT_ID and CLIENT_ID are correct
3. Clear token cache by restarting application
4. Verify client credentials grant enabled (Azure Portal → Authentication → Allow public client flows = No)

## API Reference

### Endpoints

#### Webhook

**POST /graph-webhook**

- **Purpose:** Receives Microsoft Graph change notifications
- **Authentication:** Validated via `clientState` parameter
- **Validation:** Returns `validationToken` query parameter for subscription lifecycle events
- **Response:** `202 Accepted` (notification queued) or `200 OK` (validation)

#### Subscription Management

**POST /subscriptions**

- **Purpose:** Create new Microsoft Graph subscription
- **Body:**
  ```json
  {
    "resource": "/chats/{id}/messages",
    "expiration_hours": 24
  }
  ```
- **Response:** `SubscriptionResponse` (201 Created)

**GET /subscriptions**

- **Purpose:** List all active subscriptions
- **Response:** `SubscriptionListResponse` (200 OK)

**DELETE /subscriptions/{subscription_id}**

- **Purpose:** Remove subscription by ID
- **Response:** `{"message": "Subscription deleted successfully"}` (200 OK)

## Security Considerations

1. **Client State Validation:** Webhook validates `clientState` matches expected value
2. **HTTPS Only:** Microsoft Graph requires HTTPS for notification URLs
3. **Token Storage:** OAuth tokens cached in memory (consider Redis for production)
4. **Environment Secrets:** Never commit `.env` to version control
5. **Admin Consent:** Application permissions require tenant admin approval

## License

MIT License - see LICENSE file for details.

## Support & Resources

- **Microsoft Graph Docs:** https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions
- **Change Notifications:** https://learn.microsoft.com/en-us/graph/webhooks
- **Troubleshooting:** See `LATENCY_PROBLEM.md` for network latency analysis
- **Issues:** Open GitHub issue with logs and error details

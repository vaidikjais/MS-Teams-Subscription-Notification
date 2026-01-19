# OAuth 2.0 Integration Guide

This guide explains how to use the new OAuth 2.0 delegated access flow in your Teams message application.

## **Overview**

The OAuth flow allows users to sign in with their Microsoft account and grant your app permission to read their Teams messages. **No admin consent required** - users grant permission themselves.

---

## **How It Works**

```
1. User clicks "Connect Teams"
   ↓
2. Redirected to Microsoft login page
   ↓
3. User signs in with Microsoft account
   ↓
4. User grants permission (ChannelMessage.Read, Chat.Read)
   ↓
5. Redirected back to your app with authorization code
   ↓
6. App exchanges code for access token
   ↓
7. App can now fetch user's Teams messages
   ↓
8. Token automatically refreshed when expired
```

---

## **API Endpoints**

### **1. Initiate Login**

**Endpoint:** `GET /auth/login`

**What it does:**

- Redirects user to Microsoft login page
- Generates secure state token for CSRF protection

**Example:**

```bash
curl https://teamspoc.onrender.com/auth/login
```

**Response:**
Redirects to Microsoft login URL

---

### **2. OAuth Callback** (Automatic)

**Endpoint:** `GET /auth/callback`

**What it does:**

- Microsoft redirects here after user grants permission
- Exchanges authorization code for access token
- Stores user session with token

**Parameters:**

- `code`: Authorization code from Microsoft
- `state`: CSRF protection token

**Example Response:**

```json
{
  "status": "success",
  "message": "Successfully authenticated",
  "user": {
    "id": "00000000-0000-0000-0000-000000000000",
    "email": "user@company.com"
  }
}
```

---

### **3. Get User Profile**

**Endpoint:** `GET /api/user/profile`

**Description:** Get authenticated user's profile info

**Query Parameters:**

- `user_id`: The user's Microsoft ID (from login callback)

**Example:**

```bash
curl "https://teamspoc.onrender.com/api/user/profile?user_id=00000000-0000-0000-0000-000000000000"
```

**Response:**

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "email": "user@company.com",
  "authenticated_at": "2026-01-19T12:00:00"
}
```

---

### **4. Get User's Teams**

**Endpoint:** `GET /api/user/teams`

**Description:** List all teams the user is a member of

**Query Parameters:**

- `user_id`: The user's Microsoft ID

**Example:**

```bash
curl "https://teamspoc.onrender.com/api/user/teams?user_id=00000000-0000-0000-0000-000000000000"
```

**Response:**

```json
{
  "count": 2,
  "teams": [
    {
      "id": "team-id-1",
      "displayName": "Engineering",
      "description": "Engineering team"
    },
    {
      "id": "team-id-2",
      "displayName": "Marketing",
      "description": "Marketing team"
    }
  ]
}
```

---

### **5. Get User's Messages**

**Endpoint:** `GET /api/user/messages`

**Description:** Get messages from channels user is a member of

**Query Parameters:**

- `user_id`: The user's Microsoft ID (required)
- `team_id`: Specific team ID (optional)
- `channel_id`: Specific channel in team (optional)
- `limit`: Max messages to return (default: 50, max: 500)

**Examples:**

Get all chat messages:

```bash
curl "https://teamspoc.onrender.com/api/user/messages?user_id=USER_ID&limit=10"
```

Get messages from specific channel:

```bash
curl "https://teamspoc.onrender.com/api/user/messages?user_id=USER_ID&team_id=TEAM_ID&channel_id=CHANNEL_ID"
```

**Response:**

```json
{
  "count": 5,
  "messages": [
    {
      "id": "msg-123",
      "body": {
        "content": "Hello team!",
        "contentType": "html"
      },
      "from": {
        "user": {
          "displayName": "John Doe",
          "id": "user-123"
        }
      },
      "createdDateTime": "2026-01-19T12:00:00Z"
    }
  ]
}
```

---

### **6. Logout**

**Endpoint:** `POST /auth/logout`

**Description:** Remove user session and revoke access

**Query Parameters:**

- `user_id`: The user's Microsoft ID

**Example:**

```bash
curl -X POST "https://teamspoc.onrender.com/auth/logout?user_id=USER_ID"
```

**Response:**

```json
{
  "status": "logged_out",
  "user_id": "00000000-0000-0000-0000-000000000000"
}
```

---

## **Frontend Integration Example**

### **HTML/JavaScript Example**

```html
<!DOCTYPE html>
<html>
  <head>
    <title>Teams Message Dashboard</title>
  </head>
  <body>
    <h1>Teams Message Dashboard</h1>

    <!-- Login Button -->
    <button onclick="login()">Connect Teams</button>

    <!-- User Info (hidden initially) -->
    <div id="userInfo" style="display:none;">
      <p>Logged in as: <span id="userEmail"></span></p>
      <button onclick="loadTeams()">Load Teams</button>
      <button onclick="logout()">Logout</button>
    </div>

    <!-- Teams List -->
    <div id="teamsList"></div>

    <!-- Messages List -->
    <div id="messagesList"></div>

    <script>
      const API_BASE = "https://teamspoc.onrender.com";
      let currentUserId = null;

      // Login
      function login() {
        window.location.href = `${API_BASE}/auth/login`;
      }

      // Check if user is authenticated (call after redirect from login)
      async function checkAuth(userId) {
        try {
          const response = await fetch(
            `${API_BASE}/api/user/profile?user_id=${userId}`,
          );
          const user = await response.json();

          if (response.ok) {
            currentUserId = userId;
            document.getElementById("userEmail").textContent = user.email;
            document.getElementById("userInfo").style.display = "block";
            return true;
          }
        } catch (error) {
          console.error("Auth check failed:", error);
        }
        return false;
      }

      // Load teams
      async function loadTeams() {
        if (!currentUserId) return;

        try {
          const response = await fetch(
            `${API_BASE}/api/user/teams?user_id=${currentUserId}`,
          );
          const data = await response.json();

          let html = "<h2>Your Teams:</h2><ul>";
          data.teams.forEach((team) => {
            html += `<li>${team.displayName}</li>`;
          });
          html += "</ul>";

          document.getElementById("teamsList").innerHTML = html;
        } catch (error) {
          console.error("Failed to load teams:", error);
        }
      }

      // Load messages
      async function loadMessages(teamId, channelId) {
        if (!currentUserId) return;

        try {
          const url = `${API_BASE}/api/user/messages?user_id=${currentUserId}&team_id=${teamId}&channel_id=${channelId}`;
          const response = await fetch(url);
          const data = await response.json();

          let html = "<h2>Messages:</h2><ul>";
          data.messages.forEach((msg) => {
            const content = msg.body?.content || "No content";
            const from = msg.from?.user?.displayName || "Unknown";
            html += `<li><strong>${from}:</strong> ${content}</li>`;
          });
          html += "</ul>";

          document.getElementById("messagesList").innerHTML = html;
        } catch (error) {
          console.error("Failed to load messages:", error);
        }
      }

      // Logout
      async function logout() {
        if (!currentUserId) return;

        try {
          await fetch(`${API_BASE}/auth/logout?user_id=${currentUserId}`, {
            method: "POST",
          });

          currentUserId = null;
          document.getElementById("userInfo").style.display = "none";
          document.getElementById("teamsList").innerHTML = "";
          document.getElementById("messagesList").innerHTML = "";
        } catch (error) {
          console.error("Logout failed:", error);
        }
      }

      // Extract user_id from URL after login callback
      const params = new URLSearchParams(window.location.search);
      if (params.has("user_id")) {
        checkAuth(params.get("user_id"));
      }
    </script>
  </body>
</html>
```

---

## **Azure AD Configuration**

### **Required Permissions**

In Azure AD, ensure you have these **Delegated** permissions:

1. **ChannelMessage.Read** - Read channel messages
2. **Chat.Read** - Read chat messages
3. **User.Read** - Read user profile
4. **offline_access** - Refresh token support

All these permissions are **user-consentable** - no admin approval needed!

### **Redirect URI**

Set in App Registration:

- **Web**: `https://teamspoc.onrender.com/auth/callback`

---

## **Token Management**

### **How Tokens Work**

1. **Access Token** - Valid for ~1 hour
   - Used to make Graph API requests
   - Auto-refreshed when needed

2. **Refresh Token** - Long-lived
   - Stored server-side
   - Used to get new access tokens

3. **Session** - In-memory (production: use database)
   - Stores both tokens
   - Tracks user info

### **Automatic Token Refresh**

The system automatically refreshes tokens when they expire. You don't need to worry about expiration - just make API calls!

---

## **Error Handling**

### **Common Errors**

| Error                   | Cause                    | Solution                      |
| ----------------------- | ------------------------ | ----------------------------- |
| 401 Unauthorized        | User not authenticated   | Call `/auth/login`            |
| 401 Unauthorized        | Token expired            | Automatic refresh or re-login |
| 400 Invalid state token | CSRF attack attempt      | Retry login                   |
| 403 Forbidden           | Insufficient permissions | Check Azure AD permissions    |
| 500 Server error        | API failure              | Check Render logs             |

### **Example Error Response**

```json
{
  "detail": "User not authenticated"
}
```

---

## **Security Best Practices**

✅ **Do:**

- Store tokens server-side, not in browser
- Use HTTPS only (https://teamspoc.onrender.com)
- Validate state tokens (CSRF protection)
- Refresh tokens before expiry
- Log out users when done

❌ **Don't:**

- Share user tokens
- Store tokens in localStorage
- Ignore CSRF state validation
- Expose client secrets in frontend

---

## **Testing in Swagger UI**

1. Open: https://teamspoc.onrender.com/docs

2. **Test OAuth flow:**
   - Click GET `/auth/login`
   - Follow the redirect to Microsoft login
   - Grant permission
   - Note your user_id from the response

3. **Test endpoints:**
   - GET `/api/user/profile?user_id=YOUR_USER_ID`
   - GET `/api/user/teams?user_id=YOUR_USER_ID`
   - GET `/api/user/messages?user_id=YOUR_USER_ID&limit=10`

---

## **Troubleshooting**

### **"Invalid notification URL" errors?**

- These are from the old app-only flow
- Use OAuth flow instead (no subscriptions needed)

### **Token always expired?**

- Check server clock (important for expiry calculation)
- Ensure refresh token was issued

### **Can't fetch messages?**

- Verify user_id is correct
- Check if user is member of that channel
- Ensure permissions are granted in Azure AD

---

**Happy integrating! 🚀**

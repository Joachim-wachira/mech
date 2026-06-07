# mech Platform — Update Notes

## What's New in This Update

### 1. Login Page (`frontend/login.html`)
A new dedicated login page with:
- Login via **phone number or email** + password
- **Remember me** checkbox
- **Forgot Password** tab with OTP-based reset flow:
  1. Enter phone/email → receives 6-digit SMS/email code
  2. Enter code + new password → reset complete
- Links back to registration pages

**Update all registration pages**: The `register_driver.html`, `register_mechanic.html`, and `register_spareshop.html` files now link to `login.html` instead of `#`.

---

### 2. Chat Page — Emergency Contacts (`frontend/chat.html`)
The **Updates** tab has been replaced with an **Emergency Contacts** tab (🚨) that shows:
- All Kirinyaga County emergency services and national lines
- Filterable by category: Police, Medical, Fire, Ambulance
- **Tap 📞** to immediately open the device's native phone dialer
- Every emergency call is **logged to the History tab** automatically (locally + backend)

**History tab** now shows:
- Regular call/chat history
- A dedicated **Emergency Calls** section with timestamps

#### Emergency contacts data source
- Backend first: `GET /api/emergency/contacts` (reads from `frontend/data/emergency_contacts.xlsx`)
- Fallback: hardcoded in the HTML (same data as Excel)
- The Excel file is at `frontend/data/emergency_contacts.xlsx` — update it to change contacts

---

### 3. Mechanic & Spare Shop Dashboards — Ratings
**`dashboard_mechanic.html`** and **`dashboard_spareshop.html`** now:
- Show only **MY RATINGS** (own ratings from drivers, not other users' ratings)
- Star breakdown bar chart per rating level
- Individual driver reviews with name, stars, comment, date
- **🔒 Lock note**: Ratings cannot be altered by the mechanic/spare shop
- Only the admin can modify/delete ratings via the admin dashboard

---

### 4. Backend — New Files

#### `backend/app/emergency_routes.py`
```python
from .emergency_routes import emergency_bp
app.register_blueprint(emergency_bp, url_prefix='/api/emergency')
```
Endpoints:
- `GET  /api/emergency/contacts`         — public, returns contacts from Excel
- `POST /api/emergency/log`              — JWT, logs emergency call
- `GET  /api/emergency/logs`             — JWT, user's own call history

#### `backend/app/ratings_routes.py`
```python
from .ratings_routes import ratings_bp
app.register_blueprint(ratings_bp, url_prefix='/api/ratings')
```
Endpoints:
- `POST /api/ratings/submit`                — **Driver only** — submit/update rating
- `GET  /api/ratings/mechanic/my-ratings`   — **Mechanic only** — read own ratings
- `GET  /api/ratings/spareshop/my-ratings`  — **Spare shop only** — read own ratings
- `PATCH/PUT /api/ratings/<id>`             — **Admin only** — edit rating
- `DELETE /api/ratings/<id>`               — **Admin only** — delete rating
- `GET  /api/ratings/admin/all`            — **Admin only** — all ratings with filters

#### `backend/app/auth_extras.py`
```python
from .auth_extras import auth_extras_bp
app.register_blueprint(auth_extras_bp, url_prefix='/api/auth')
```
Endpoints:
- `POST /api/auth/login`            — login with phone or email
- `POST /api/auth/forgot-password`  — send OTP reset code
- `POST /api/auth/reset-password`   — validate OTP + set new password
- `POST /api/auth/logout`           — optional client-side logout

#### `backend/app/models_additions.py`
Copy the `Rating` and `EmergencyCallLog` classes into your `models.py`, then run:
```bash
flask db migrate -m "add ratings and emergency_call_logs"
flask db upgrade
```

---

### 5. Emergency Contacts Excel File (`frontend/data/emergency_contacts.xlsx`)
Pre-populated with Kirinyaga County emergency contacts.
Columns: `#`, `Service Name`, `Location`, `Emergency Contact`, `Notes`, `Category`, `Available 24/7`

To update contacts: edit the Excel file. The backend reads it on every request.
Categories recognised: `Police`, `Medical`, `Fire`, `Ambulance`

---

### 6. Platform Call Rules (enforced in chat.html)
- **Mechanic-to-Driver / Driver-to-Mechanic / Driver-to-Spare-Shop** calls: via **Mech Platform only** (WebSocket-based voice — `MechApp.WS.initiateCall()`)
- **Emergency services**: Native phone call (`tel:` link) — redirects to device dialer
- Only the **two users in a conversation** and the **admin** can see messages, calls, and voice notes
- Call history visible in the **History tab**

---

## Files Changed / Added

| File | Status |
|------|--------|
| `frontend/login.html` | ✅ New |
| `frontend/chat.html` | ✅ Updated |
| `frontend/dashboard_mechanic.html` | ✅ Updated |
| `frontend/dashboard_spareshop.html` | ✅ Updated |
| `frontend/register_driver.html` | ✅ Updated (login link) |
| `frontend/data/emergency_contacts.xlsx` | ✅ New |
| `backend/app/emergency_routes.py` | ✅ New |
| `backend/app/ratings_routes.py` | ✅ New |
| `backend/app/auth_extras.py` | ✅ New |
| `backend/app/models_additions.py` | ✅ New (instructions) |

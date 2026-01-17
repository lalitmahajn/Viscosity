# Security Package Analysis

## Overview
The `viscologic/security/` package provides authentication and commissioning security for the ViscoLogic system. It consists of:
1. `auth_engineer.py` - Engineer password authentication with session management
2. `commissioning_manager.py` - One-time commissioning password manager

## Files

### 1. `auth_engineer.py` (164 lines)
**Purpose:** Engineer-level authentication with secure password hashing and session management.

#### Key Features:
- **PBKDF2-SHA256 Password Hashing:** Industry-standard secure password storage
- **Session Management:** Token-based sessions with 5-minute timeout
- **Password Migration:** Automatic migration from plain text to hashed format
- **Password Change:** Secure password change with session validation
- **Password Hints:** Optional non-secret hints for password recovery

#### Security Implementation:
```python
# Password Hash Format:
"pbkdf2_sha256${iterations}${salt_hex}${dk_hex}"

# Example:
"pbkdf2_sha256$200000$a1b2c3d4e5f6...$f1e2d3c4b5a6..."
```

**PBKDF2 Parameters:**
- **Algorithm:** SHA-256
- **Iterations:** 200,000 (default, configurable)
- **Salt:** 16 random bytes (unique per password)
- **Key Length:** 32 bytes (256 bits)

#### Key Methods:

**`ensure_password_initialized()`**
- Initializes password hash if not exists
- Uses config password or default "admin"
- Migrates plain text passwords to hash format
- Stores hash in SQLite meta table

**`login(password: str) -> AuthResult`**
- Verifies password against stored hash
- Creates session token on success
- Auto-migrates plain text passwords
- Returns `AuthResult(ok, reason, session_token)`

**`is_session_valid(token: str) -> bool`**
- Validates session token
- Checks token matches active session
- Checks session hasn't expired (5 minutes)

**`refresh_session(token: str) -> bool`**
- Extends session expiry by 5 minutes
- Returns True if token is valid

**`change_password(session_token, new_password, hint) -> AuthResult`**
- Changes password (requires valid session)
- Validates minimum length (4 characters)
- Hashes new password with PBKDF2
- Stores optional hint

**`logout()`**
- Clears active session

#### Storage:
- **Hash:** `meta.engineer_password_hash`
- **Initialization Flag:** `meta.engineer_password_inited`
- **Hint:** `meta.engineer_password_hint`

#### Default Password:
- **Default:** "admin" (can be changed via config)
- **Config Key:** `security.engineer_password`
- **Warning:** Default password is logged on first initialization

---

### 2. `commissioning_manager.py` (256 lines)
**Purpose:** One-time commissioning password manager for new device setup.

#### Key Features:
- **One-Time Setup:** Prevents device operation until commissioned
- **PBKDF2-SHA256 Password Hashing:** Same secure hashing as engineer auth
- **Multiple Password Sources:** Environment variable, config, or auto-generated
- **Commissioning State:** Tracks if device has been commissioned
- **Password Reset:** Engineer can reset commissioning (requires re-commissioning)

#### Commissioning Flow:
```
1. Device boots → Check device_state.commissioned
2. If NOT commissioned → Show CommissioningLock screen
3. User enters commissioning password
4. Password verified → Open CommissioningWizard
5. Wizard completes → mark_commissioned()
6. Device can now operate normally
```

#### Password Sources (Priority Order):
1. **Environment Variable:** `VISC_COMMISSION_PW`
2. **Config File:** `security.commissioning_password`
3. **Auto-Generated:** If `auto_generate_commissioning_password=true`
4. **Default:** "1234" (with warning logged)

#### Key Methods:

**`is_commissioned() -> bool`**
- Checks `device_state.commissioned` flag
- Returns True if device has been commissioned

**`needs_commissioning() -> bool`**
- Returns True if commissioning is required and not completed
- Respects `commissioning_required_on_first_run` config

**`ensure_password_initialized()`**
- Initializes commissioning password hash
- Uses password source priority (env > config > generated > default)
- Logs auto-generated passwords (one-time warning)

**`verify_commissioning_password(password: str) -> VerifyResult`**
- Verifies password against stored hash
- Returns `VerifyResult(ok, reason)`
- Auto-initializes hash if missing

**`mark_commissioned()`**
- Marks device as commissioned
- Sets `device_state.commissioned = 1`
- Logs commissioning event

**`reset_commissioning()`**
- Resets commissioning flag (engineer-only)
- Sets `device_state.commissioned = 0`
- Requires re-commissioning on next boot
- Logs reset event

**`change_commissioning_password(new_password, hint) -> VerifyResult`**
- Changes commissioning password (engineer-only)
- Does NOT change commissioned flag
- Only changes the lock password

**`ensure_commissioned()`**
- Called by Orchestrator on startup
- Ensures password hash is initialized
- Raises `RuntimeError` if not commissioned
- Prevents system operation until commissioned

#### Storage:
- **Hash:** `meta.commissioning_password_hash`
- **Initialization Flag:** `meta.commissioning_password_inited`
- **Hint:** `meta.commissioning_password_hint`
- **Commissioned Flag:** `device_state.commissioned`

#### Default Password:
- **Default:** "1234" (with warning)
- **Auto-Generated:** `AUTO-{8_random_chars}` (if enabled)
- **Warning:** Default password is logged on first use

---

## Security Architecture

### Password Hashing (Both Modules)
```
Plain Password → PBKDF2-SHA256 → Stored Hash
                (200k iterations)
                (random salt)
                (32-byte key)
```

**Why PBKDF2?**
- **Industry Standard:** NIST-recommended key derivation function
- **Slow by Design:** 200,000 iterations make brute-force attacks expensive
- **Salt Protection:** Unique salt prevents rainbow table attacks
- **Timing-Safe Comparison:** Uses `hmac.compare_digest()` to prevent timing attacks

### Session Management (Engineer Auth Only)
```
Login → Generate Token → Store in Memory → Validate on Each Request
        (16 hex chars)   (5 min expiry)   (check token + expiry)
```

**Session Security:**
- **Token Generation:** `secrets.token_hex(8)` - cryptographically secure
- **Timeout:** 5 minutes (300 seconds)
- **Storage:** In-memory only (not persisted)
- **Validation:** Token + expiry check on each request

### Commissioning Flow
```
┌─────────────────────────────────────────────────────────┐
│              Device Boot                                │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │  CommissioningManager        │
        │  .ensure_commissioned()      │
        └───────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        │                               │
        ▼                               ▼
┌───────────────┐              ┌───────────────┐
│ Commissioned? │              │ NOT          │
│ YES           │              │ Commissioned  │
└───────────────┘              └───────────────┘
        │                               │
        │                               ▼
        │                   ┌───────────────────────┐
        │                   │ CommissioningLock     │
        │                   │ Screen                │
        │                   └───────────────────────┘
        │                               │
        │                               ▼
        │                   ┌───────────────────────┐
        │                   │ User Enters Password │
        │                   └───────────────────────┘
        │                               │
        │                               ▼
        │                   ┌───────────────────────┐
        │                   │ verify_password()     │
        │                   └───────────────────────┘
        │                               │
        │                               ▼
        │                   ┌───────────────────────┐
        │                   │ CommissioningWizard   │
        │                   └───────────────────────┘
        │                               │
        │                               ▼
        │                   ┌───────────────────────┐
        │                   │ mark_commissioned()   │
        │                   └───────────────────────┘
        │                               │
        └───────────────┬───────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │   Normal Operation             │
        │   (Operator Screen)            │
        └───────────────────────────────┘
```

### Engineer Authentication Flow
```
┌─────────────────────────────────────────────────────────┐
│              Engineer Screen                            │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │  User Clicks "Unlock"         │
        └───────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │  EngineerAuth.login(password) │
        └───────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        │                               │
        ▼                               ▼
┌───────────────┐              ┌───────────────┐
│ Valid?        │              │ Invalid       │
│ YES           │              │ Password      │
└───────────────┘              └───────────────┘
        │                               │
        │                               ▼
        │                   ┌───────────────────────┐
        │                   │ Show Error            │
        │                   │ "Wrong password"      │
        │                   └───────────────────────┘
        │
        ▼
┌───────────────────────────────┐
│ Generate Session Token        │
│ Store in Memory               │
│ Set 5-min Expiry              │
└───────────────────────────────┘
        │
        ▼
┌───────────────────────────────┐
│ Unlock Engineer Screen        │
│ Enable All Tabs               │
└───────────────────────────────┘
        │
        ▼
┌───────────────────────────────┐
│ On Each Action:               │
│ is_session_valid(token)?      │
└───────────────────────────────┘
        │
        └───► If expired → Re-lock screen
```

---

## Integration Points

### UI Integration

**Engineer Screen (`engineer_screen.py`):**
```python
# Initialization
self.auth = EngineerAuth(store, config, logger)
self.auth.ensure_password_initialized()

# Login
result = self.auth.login(password)
if result.ok:
    self._session_token = result.session_token
    self._unlocked = True

# Session Validation
if not self.auth.is_session_valid(self._session_token):
    self._lock()  # Re-lock if expired

# Password Change
result = self.auth.change_password(
    session_token=self._session_token,
    new_password=new_pw,
    hint=hint
)
```

**Commissioning Lock (`commissioning_lock.py`):**
```python
# Initialization
self.cm = CommissioningManager(store, config, logger)
self.cm.ensure_password_initialized()

# Verification
result = self.cm.verify_commissioning_password(password)
if result.ok:
    # Navigate to commissioning wizard
    self._proceed_unlocked()
```

**Main Window (`main_window.py`):**
```python
# Backend Initialization
if CommissioningManager:
    self.comm_mgr = CommissioningManager(store, config, logger)
    self.comm_mgr.ensure_password_initialized()

if EngineerAuth:
    self.auth_mgr = EngineerAuth(store, config, logger)
    self.auth_mgr.ensure_password_initialized()
```

### Orchestrator Integration

**Startup Check (`orchestrator.py`):**
```python
# In Orchestrator.start()
try:
    if hasattr(self.commissioning, "ensure_commissioned"):
        self.commissioning.ensure_commissioned()  # Raises if not commissioned
except Exception:
    pass  # UI will handle commissioning lock
```

---

## Security Considerations

### ✅ **Strengths:**
1. **Strong Hashing:** PBKDF2-SHA256 with 200k iterations
2. **Unique Salts:** Each password has unique salt
3. **Timing-Safe Comparison:** Uses `hmac.compare_digest()`
4. **Session Management:** Token-based with expiry
5. **Password Migration:** Automatic migration from plain text
6. **Password Hints:** Optional non-secret hints
7. **Lockout Protection:** Commissioning lock has 5-attempt lockout

### ⚠️ **Potential Improvements:**
1. **Default Passwords:** Both use weak defaults ("admin", "1234")
   - **Mitigation:** Warnings logged, passwords can be changed
2. **Session Storage:** Sessions stored in-memory only (lost on restart)
   - **Mitigation:** Acceptable for single-user device
3. **No Password Complexity:** Minimum 4 characters only
   - **Mitigation:** Could add complexity requirements
4. **No Rate Limiting:** Engineer auth has no lockout
   - **Mitigation:** Could add rate limiting
5. **Password in Config:** Plain passwords in config file
   - **Mitigation:** Only used for initialization, then hashed

### 🔒 **Security Best Practices:**
1. **Change Default Passwords:** Immediately after first use
2. **Use Environment Variables:** For production deployments
3. **Enable Auto-Generation:** For commissioning password
4. **Store Hints Securely:** Don't reveal password in hints
5. **Regular Password Rotation:** Change passwords periodically
6. **Monitor Failed Logins:** Log authentication failures

---

## Configuration

### Engineer Password:
```yaml
security:
  engineer_password: "admin"  # Default password (change after first use)
  pbkdf2_iterations: 200000   # Hashing iterations
```

### Commissioning Password:
```yaml
security:
  commissioning_required_on_first_run: true
  commissioning_password: "1234"  # Default (change after first use)
  auto_generate_commissioning_password: false  # Set to true for auto-gen
  commissioning_password_hint: ""  # Optional hint
  pbkdf2_iterations: 200000
```

### Environment Variables:
```bash
# Commissioning password (highest priority)
export VISC_COMMISSION_PW="secure_password_here"

# Engineer password (not supported via env, use config)
```

---

## Database Schema

### Meta Table (Both Modules):
```sql
-- Engineer Auth
key: "engineer_password_hash"      → PBKDF2 hash
key: "engineer_password_inited"     → "1" if initialized
key: "engineer_password_hint"       → Optional hint

-- Commissioning
key: "commissioning_password_hash"  → PBKDF2 hash
key: "commissioning_password_inited" → "1" if initialized
key: "commissioning_password_hint"  → Optional hint
```

### Device State Table:
```sql
-- Commissioning Status
device_state.commissioned → 0 (not commissioned) or 1 (commissioned)
device_state.commissioned_at_ms → Timestamp when commissioned
```

---

## Testing Recommendations

1. **Password Hashing:**
   - Test PBKDF2 hash generation
   - Test password verification
   - Test migration from plain text

2. **Session Management:**
   - Test session creation
   - Test session expiry
   - Test session refresh
   - Test concurrent sessions

3. **Commissioning Flow:**
   - Test first-time commissioning
   - Test password verification
   - Test commissioning completion
   - Test commissioning reset

4. **Security:**
   - Test brute-force protection
   - Test timing attacks (should be safe)
   - Test password change validation
   - Test session token security

---

## Summary

### `auth_engineer.py`:
- **Purpose:** Engineer-level authentication
- **Security:** PBKDF2-SHA256 hashing, session tokens
- **Default:** "admin" password
- **Use Case:** Unlock engineer screen for configuration

### `commissioning_manager.py`:
- **Purpose:** One-time device commissioning
- **Security:** PBKDF2-SHA256 hashing, commissioning flag
- **Default:** "1234" password
- **Use Case:** First-time device setup, prevent operation until configured

Both modules use **industry-standard security practices** with PBKDF2 password hashing and proper session management. The default passwords should be changed immediately after first use in production environments.


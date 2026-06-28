# Gateway HTTP Module

`gateway/http` is the API boundary layer responsible for routing, auth, user context resolution, middleware, and HTTP access to runtime services.

## Main Files

- `gateway/http/router.py`: route assembly
- `gateway/http/middleware.py`: context, rate-limit, logging, and error handling
- `gateway/http/user_manager.py`: user and user-config persistence
- `gateway/http/message_manager.py`: session message storage
- `gateway/http/routes/auth.py`: register, login, and profile
- `gateway/http/routes/chat.py`: chat endpoints, including streaming
- `gateway/http/routes/config.py`: config APIs
- `gateway/http/routes/memory.py`: memory endpoints and graph payloads
- `gateway/http/routes/sessions.py`: session list and details

## Request Flow

1. Middleware runs first.
2. Token resolves into `user_id`.
3. Route executes domain logic or delegates to a service.
4. Response is normalized for client consumption.

## Example: Settings Save

1. UI submits settings.
2. It calls `POST /api/config/update`.
3. The route delegates to `ConfigService.update_user_config`.
4. `user_manager` persists to `config/users/<user_id>/config.json`.

## Operational Notes

- Avoid duplicate write paths for the same action.
- Keep user-facing errors readable and logs actionable.
- Distinguish auth failures from business failures via status codes.

## Change Notes

- Keep endpoint naming consistent.
- Re-verify streaming behavior after middleware changes.
- Sync frontend auth state handling when auth payload fields change.

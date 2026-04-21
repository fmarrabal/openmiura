# Security posture

openMiura is now **secure-by-default** for network and terminal execution. Broad web access and terminal shell execution require an explicit opt-in through environment profiles or targeted overrides.

# Seguridad operativa y reverse proxy

## Sesiones de navegador, cookies y CSRF

openMiura puede operar de dos maneras para la UI y el broker HTTP:

- **Bearer tokens** en cabeceras `Authorization`
- **Sesiones de navegador** con cookie HttpOnly

Para producción con navegador se recomienda:

```env
OPENMIURA_AUTH_COOKIE_ENABLED=true
OPENMIURA_AUTH_COOKIE_SECURE=true
OPENMIURA_AUTH_COOKIE_SAMESITE=lax
OPENMIURA_AUTH_CSRF_ENABLED=true
```

Cuando el modo cookie está activo, openMiura:

- emite una cookie de sesión HttpOnly
- emite una cookie separada de CSRF
- exige `X-CSRF-Token` en peticiones mutantes cuando la autenticación entra por cookie

## Terminal endurecida por rol

`terminal_exec` admite una política global y políticas por rol en `configs/openmiura.yaml`.

Ejemplo:

```yaml
tools:
  terminal:
    allow_shell: false
    allow_shell_metacharacters: false
    allowed_commands: []
    blocked_commands: ["rm", "shutdown"]
    role_policies:
      user:
        allow_shell: false
        allow_shell_metacharacters: false
        allowed_commands: ["python", "pytest"]
      operator:
        allow_shell: false
        allowed_commands: ["python", "pytest", "git"]
      admin:
        allowed_commands: ["python", "pytest", "git", "pip"]
```

## Reverse proxy y TLS

Se recomienda publicar openMiura detrás de un reverse proxy y terminar TLS ahí.

### Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name openmiura.example.com;

    ssl_certificate     /etc/letsencrypt/live/openmiura/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/openmiura/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Forwarded-Host $host;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Request-ID $request_id;
        proxy_buffering    off;
    }
}
```

### Caddy

```caddy
openmiura.example.com {
    reverse_proxy 127.0.0.1:8081
}
```

## Recomendaciones finales

- usa `OPENMIURA_ADMIN_TOKEN` fuerte
- usa sesiones cortas si la UI es compartida
- rota tokens de API regularmente
- deja `terminal_exec` solo para agentes/roles muy concretos
- activa `gitleaks` en CI y también en `pre-commit`


## Tool allowlists by role

Además de la policy del agente, puedes limitar tools por rol en `tools.tool_role_policies`:

```yaml
tools:
  tool_role_policies:
    user:
      blocked_tools: ["fs_write", "terminal_exec"]
    operator:
      allowed_tools: ["time_now", "web_fetch", "fs_read"]
    admin:
      blocked_tools: []
```

Esto se aplica tanto al catálogo visible para la UI/broker como a la ejecución real de la tool.

## Cookies seguras tras reverse proxy

En producción con TLS terminado en Nginx/Caddy, activa también:

```env
OPENMIURA_AUTH_COOKIE_ENABLED=true
OPENMIURA_AUTH_COOKIE_SECURE=true
OPENMIURA_AUTH_CSRF_ENABLED=true
```

Comprueba en el navegador que la cookie de sesión sale con `HttpOnly; Secure; SameSite=Lax` (o `Strict` si no necesitas POST cross-site).

# Despliegue en `yincana.iyando.qzz.io`

Montado con **Cloudflare Tunnel** apuntando a `servidor.py` en el host Proxmox.
Este documento es el registro de lo que hay puesto y cómo reponerlo.

> Nota: el dominio es **`iyando.qzz.io`** (dos zetas, "qzz"). El subdominio del
> juego es `yincana.iyando.qzz.io` — de primer nivel, así lo cubre el SSL gratis.

## Por qué el túnel

El túnel abre una conexión **saliente** del Proxmox a Cloudflare: no hay que
abrir puertos, ni saber la IP pública, ni pelearse con el CGNAT del ISP.
Cloudflare pone el HTTPS en el borde (geolocalización y service worker
contentos) y `servidor.py` corre en `localhost:8000` en HTTP plano, sin tocarlo.
Descartadas: exposición directa (se cae si hay CGNAT), serverless Workers+D1
(habría que reescribir el backend Python), ngrok (intersticial que mata el
deep-link `?k=`) y Tailscale Funnel (no admite dominio propio).

## Lo que ya está hecho

- `cloudflared` (binario) en `~/.local/bin/cloudflared`.
- `cloudflared tunnel login` → `~/.cloudflared/cert.pem` (zona `iyando.qzz.io`).
- Túnel **`yincana`** creado, UUID `c4e29006-3da6-4b95-ba6e-be5fb934f663`,
  credenciales en `~/.cloudflared/<UUID>.json`.
- `~/.cloudflared/config.yml` con ingress `yincana.iyando.qzz.io → localhost:8000`.
- CNAME **proxied** `yincana.iyando.qzz.io` → el túnel (con
  `cloudflared tunnel route dns`).

## Hacerlo permanente (systemd) — REQUIERE `sudo`

Dos servicios, los dos como usuario `iyan`: la API y el túnel.

```bash
sudo cp ~/YINCANA_CADAVEDO/yincana.service        /etc/systemd/system/
sudo cp ~/YINCANA_CADAVEDO/yincana-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yincana yincana-tunnel
systemctl --no-pager status yincana yincana-tunnel
# logs:  journalctl -u yincana -f   /   journalctl -u yincana-tunnel -f
```

`yincana.service` arranca `python servidor.py --puerto 8000`; `yincana-tunnel.service`
arranca el túnel y depende del primero. Tras un reinicio del host, ambos suben solos.

## Ajustes en el panel de Cloudflare (una vez)

- **Rocket Loader: OFF** — reescribe el `<script>` y rompe el registro del SW.
- **Bot Fight Mode: OFF** — marca los `fetch` a `/api` como bot.
- **Under Attack Mode: no** — su intersticial rompe el deep-link `?k=` del tag.
- El registro `yincana` debe quedar **proxied** (nube naranja).

> **Caché del `sw.js`: ya resuelto en el código.** Cloudflare cachea el `.js`
> por extensión y `no-cache` no basta (lo cachea y revalida). `servidor.py`
> sirve el `sw.js` con **`Cache-Control: no-store`**, y así el edge lo deja
> fuera (`cf-cache-status: BYPASS`, comprobado). No hace falta una Cache Rule
> para esto. Las respuestas de `/api` ya van con `no-store` y salen `DYNAMIC`.

## Pendiente de limpiar

Al enrutar el DNS se creó por error un registro con el dominio mal escrito
(`yincana.iyando.qzzz.io` dentro de la zona) antes de corregirlo. Es inofensivo
pero conviene **borrarlo en el panel** (DNS → Records): busca el CNAME cuyo
nombre lleve `qzzz` y elimínalo. El bueno es `yincana` (→ `yincana.iyando.qzz.io`).

## Grabar el tag, ya para el día de campo

Con `yincana.iyando.qzz.io` fija, graba cada NTAG215 **una sola vez** con
`https://yincana.iyando.qzz.io/?k=<clave>` y no se vuelve a tocar. Los jugadores
abren su `…/?u=<token>` una vez.

## Reponer el túnel desde cero (si hiciera falta)

```bash
cloudflared tunnel login                                   # interactivo, zona iyando.qzz.io
cloudflared tunnel create yincana                          # anota el UUID
# escribe ~/.cloudflared/config.yml (tunnel + credentials-file + ingress)
cloudflared tunnel route dns yincana yincana.iyando.qzz.io
cloudflared tunnel --config ~/.cloudflared/config.yml run yincana   # probar
```

## Demo rápida sin dominio (túnel efímero)

```bash
python servidor.py --puerto 8000
cloudflared tunnel --url http://localhost:8000     # URL *.trycloudflare.com temporal
```
Ver `DEMO.md`.

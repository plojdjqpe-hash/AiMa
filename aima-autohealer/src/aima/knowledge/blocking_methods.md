# Полный каталог методов блокировки трафика (для LLM-loop AiMa)

> Источник: операционный опыт по обходу РКН ТСПУ / GFW / иранской NCFC / турецкой
> BTK. Используется как system-prompt контекст для `llm_decision.py`, чтобы
> модель понимала, какие сигнатуры зондов соответствуют каким техникам.
> Каждый раздел маппится на `BlockType` или его комбинацию.

## 1. DNS-уровень (`BlockType.DNS_BLOCK`)
Самый дешёвый и первый слой почти везде.
- **DNS poisoning** — резолвер возвращает подменённый IP (часто 0.0.0.0 или
  заглушку оператора).
- **NXDOMAIN injection** — фейковый «домен не существует».
- **DNS hijacking** — прозрачное перенаправление UDP/53 на оператора.
- **DoH/DoT throttling** — TCP/853 и https://dns.google/dns-query
  замедляются или блокируются.

Сигнатура зонда: DNS-резолвинг возвращает «зарегулированный» IP, NXDOMAIN на
зону, которая фактически существует, или таймаут.

## 2. IP-уровень (`BlockType.TCP_RST`, `TCP_TIMEOUT`)
- **Чёрные списки IP** — TCP SYN не получает SYN-ACK или сразу RST.
- **GeoIP filtering** — блок целых /16-/24, особенно популярных VPS-провайдеров.
- **BGP blackholing** — анонс /32 в null0; пакеты до сервера не доходят.
- **ASN-уровень** — сетевые трогалкин-устройства фильтруют по AS_PATH.

Минус для атакующего: ломает легальный трафик (Cloudflare, Apple, Google), что
ограничивает применение в default-листах.

## 3. SNI filtering (`BlockType.SNI_BLOCK`)
Анализ открытого `server_name` в TLS ClientHello.
- TCP-handshake проходит, TLS ClientHello отправляется, в ответ — RST или
  silent drop на основе значения SNI.
- Работает только пока SNI не зашифрован (ECH/ESNI).
- Часто комбинируется с **SNI+IP correlation** (см. п.16).

Сигнатура: TCP `success`, TLS `fail` по конкретным SNI; смена SNI (на
`fonts.googleapis.com`, `apple.com`, etc.) сразу разблокирует.

## 4. DPI (Deep Packet Inspection) — ядро ТСПУ/GFW
Объединяет несколько техник:
- HTTP-headers analysis (User-Agent, Host, Origin).
- Сигнатуры протоколов (OpenVPN HMAC, WireGuard handshake, Tor protocol,
  Shadowsocks-2022 AEAD).
- Распознавание приложений по паттернам (Telegram MTProto, Zoom, FaceTime).
- TLS fingerprinting (JA3/JA4) — клиенты с уникальными `cipher_list`
  определяются как «не-Chrome», помечаются.

Действия DPI: RST-инъекция, throttle, выборочный drop, помещение
`(src_ip, dst_ip, sni)`-кортежа в blacklist на N часов.

## 5. URL/HTTP filtering (`BlockType.HTTP_TAMPER`)
Только для plain HTTP или MITM-инспекции.
- Блок по URL/path/query/keyword.
- Замена body на блок-страницу («Доступ ограничен»).
- Category-based фильтр (adult, gambling, политика).

## 6. Active probing
Самый коварный механизм у GFW.
- Цензор сам подключается к подозрительному IP/порту и проверяет: «это
  Shadowsocks? V2Ray? OpenVPN? Tor bridge?».
- Если сервер «отвечает» характерно — добавляется в чёрный список на 1-30
  дней.
- Контрмеры: REALITY-fallback, Shadowsocks-2022 без timing-сигнатур,
  domain-fronting, ShadowTLS.

## 7. Traffic shaping / Throttling (`BlockType.THROTTLE`)
- Уровень приложения определён → Quality-of-Service режет полосу до 50-200
  Кбит/с после первых нескольких секунд.
- Выглядит как «интернет тупит», а не блокировка.
- Сигнатура зонда: handshake ок, RTT после ~5-15 секунд расширяется в 3-10
  раз; throughput < 100 Кбит/с после первого мегабайта.

## 8. Protocol blocking
- OpenVPN UDP/1194 + TCP/443 blob.
- WireGuard handshake (magic byte 0x01 + версия).
- IPSec IKE/ESP.
- Tor (DA fingerprint, OR-handshake).
Контрмеры: обфускация (xray-core, v2ray, obfs4), запуск под REALITY.

## 9. TLS fingerprinting (JA3/JA4)
- Цензор хешит `version+cipher_list+extensions+ec_curves+ec_pf` →
  получает JA3.
- Нестандартные клиенты (sing-box default, openssl-CLI, Python-requests)
  определяются как «не браузер», помечаются.
- Защита: uTLS-mimicry (Chrome 124, Firefox 128, Safari 17), смена fingerprint
  при ротации.

## 10. ESNI/ECH blocking
- Encrypted SNI / ECH-Outer ClientHello по сигнатуре extension `0xFE0D`.
- Принудительный fallback на plaintext SNI → попадает в фильтр п.3.
- РКН в 2025-2026 активно блокирует ECH у Cloudflare.

## 11. CDN / domain-fronting blocking
- Раньше: использование `Host: forbidden.com` поверх TLS-соединения с
  `cloudflare.com` обходило блок.
- Сейчас: CF/Google/Fastly закрыли domain-fronting; РКН научился
  детектировать рассогласование SNI ↔ Host.
- Контрмеры: CDN-WS over 443 (Cloudflare Workers), Vercel-edge, сложно
  блокировать без ущерба сайтам клиентов.

## 12. QUIC/HTTP3 blocking (`BlockType.QUIC_DROP`)
- 100% drop на UDP/443.
- Force downgrade: ICMP-port-unreachable → клиент уходит на TCP.
- Контрмеры: Hysteria2 на нестандартных UDP-портах (8443, 51820),
  multiplexed QUIC через WireGuard tunnel.

## 13. Port-based filtering
- Whitelist 80/443/53 — всё остальное (UDP/нестандартные TCP) блочится.
- Контрмеры: всё на 443/8443/2053/2083/2087/2096 (CF-friendly ports).

## 14. RST-injection (TCP reset attack)
- Активно используется в Китае и в РФ ТСПУ.
- Цензор inject-ит TCP RST в обе стороны соединения после flagged ClientHello
  или сигнатуры приложения.
- Распознать: handshake завершился, в ответ через 1-3 секунды — RST с
  правильным SEQ.

## 15. Certificate filtering
- Блок self-signed, expired, не-EV сертификатов на корпоративных шлюзах.
- РКН не делает это публично, но операторы (МТС-Энтерпрайз) могут.

## 16. SNI + IP correlation
- Если IP сервера ранее ассоциирован с заблокированным SNI → блок IP.
- Контрмера: ротация IP, fronting через свежий CDN-IP (Cloudflare
  rotating-IP edge).

## 17. Behavioral analysis (next-gen)
- ML-классификатор на: timing inter-packet intervals, packet size
  distribution, entropy first 16 bytes, flow duration.
- Выявляет даже идеально обфусцированный VPN.
- Контрмеры: padding (cl0p, V2Ray random padding), обманчивые «idle» патерны,
  multipath/multipath-QUIC.

## 18. Full TLS interception (MITM)
- Корпоративные сети (банки, гос. учреждения) ставят корневой сертификат, MITM
  всё HTTPS.
- В мобильных сетях — пока редко.
- Контрмера: certificate pinning у клиента; если клиент ловит подмену — переключаемся
  на полностью obfuscated transport (REALITY с JA3 imitation).

## 19. App-level blocking
- Telegram MTProto, WhatsApp HTTPS endpoints, TikTok API endpoints — по
  сигнатурам и known-IP сетей.
- Контрмеры: проксирование через VLESS/REALITY, proxy.telegram.org как
  fallback, MTProto-proxy для Telegram.

## 20. Hybrid (реальные системы)
ТСПУ-2026, GFW, NCFC — это **оркестрация**:
```
[L3] IP-blacklist  → если совпало → drop
        ↓ иначе
[L4] DNS check     → если домен в реестре → poison
        ↓ иначе
[L7] SNI lookup    → если SNI ∈ blacklist → RST
        ↓ иначе
[DPI] Protocol     → если сигнатура подозрительна → RST или AP
        ↓ иначе
[AP]  Active probe → если сервер отвечает как Shadowsocks/V2Ray → blacklist 24h
        ↓ иначе
[BA]  Behavioral   → если timing/size аномальны → throttle до 200 kbit/s
```
LLM-decision должен думать «как ТСПУ»: какой слой сработал, какой следующий
обход с минимальным риском провала.

## Маппинг каталога → `BlockType` enum
| Метод цензора | aima `BlockType` |
|---|---|
| DNS poison/NXDOMAIN/hijack | `DNS_BLOCK` |
| IP-blacklist / GeoIP / BGP blackhole | `TCP_RST` или `TCP_TIMEOUT` |
| SNI filter / ESNI fallback | `SNI_BLOCK` |
| DPI RST-injection | `TCP_RST` (или `REALITY_DETECT` если поздний) |
| URL/HTTP filtering | `HTTP_TAMPER` |
| Active probing detection | (новый: `ACTIVE_PROBED`) |
| Throttling / QoS | `THROTTLE` |
| Protocol blocking (OpenVPN/WG) | (новый: `PROTO_BLOCK`) |
| TLS fingerprinting | (новый: `TLS_FP_BLOCK`) |
| ECH blocking | (новый: `ECH_BLOCK`) |
| Domain-fronting blocking | `HTTP_TAMPER` |
| QUIC/UDP drop | `QUIC_DROP` |
| Port whitelist | `TCP_RST` или `TCP_TIMEOUT` |
| RST injection | `REALITY_DETECT` |
| Cert filter | `SNI_BLOCK` |
| SNI+IP correlation | `SNI_BLOCK` |
| Behavioral ML | `THROTTLE` или (новый: `BEHAVIORAL`) |
| Full MITM | (новый: `MITM`) |
| App-level blocking | `HTTP_TAMPER` или per-app |
| Hybrid | детектится как комбинация |

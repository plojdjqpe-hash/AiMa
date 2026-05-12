# Каталог "лечений" (recipes) — что мутировать при каждом типе блока

> Сейчас рецепты — это идентификаторы (строки). Будущий `mutation_engine.py`
> зарегистрирует обработчики, которые знают как применить рецепт через 3X-UI
> API + sub_renderer.py.

## Format
```yaml
recipe: rotate_sni_pool
applies_to: [SNI_BLOCK, TLS_FP_BLOCK]
mutation:
  - swap inbound.streamSettings.realitySettings.serverNames
    from current pool to next ranked SNI list
  - regenerate subscription URLs for all users on this inbound
risk: low          # how disruptive to existing connections
ttl: 6h            # rollback if blocked again within this window
verify_via: probe_tls(profile, sni=new_sni)
```

## Список рецептов (initial v0.1)

| recipe | applies_to | description |
|---|---|---|
| `rotate_sni_pool` | SNI_BLOCK, TLS_FP_BLOCK | сдвинуть пул SNI: cloudflare→fastly→discord→tiktok-cdn→fonts.googleapis |
| `switch_to_xhttp_path` | SNI_BLOCK, HTTP_TAMPER | XHTTP с randomized path, mimic CDN-WS |
| `fallback_cdn_ws` | SNI_BLOCK, HTTP_TAMPER, TCP_RST | переключить outbound на VLESS-WS over CF Workers |
| `activate_backup_inbound` | TCP_RST, TCP_TIMEOUT, IP_BLOCK | поднять резервный inbound на другом IP |
| `add_ipv6` | TCP_RST, IP_BLOCK | дополнительный IPv6 endpoint, многие операторы IPv6 не фильтруют |
| `switch_to_alt_port_8443_2053` | TCP_RST, TCP_TIMEOUT | сменить 443 на 8443/2053/2083/2087/2096 (CF-compatible) |
| `switch_to_warp_relay` | TCP_RST, IP_BLOCK | вторая хоп через Cloudflare WARP-relay |
| `rotate_pubkey` | REALITY_DETECT | перегенерировать REALITY x25519 keypair |
| `change_dest_sni` | REALITY_DETECT | сменить REALITY `dest` на новый сайт-донор |
| `regenerate_short_ids` | REALITY_DETECT | новые `shortIds` (новые user-keys) |
| `disable_udp_outbounds` | QUIC_DROP | временно отключить Hysteria2/TUIC/QUIC-WG |
| `force_tcp_only` | QUIC_DROP | sing-box outbound `network: tcp` |
| `switch_doh_endpoint` | DNS_BLOCK | сменить DoH резолвер: 1.1.1.1 → 9.9.9.9 → mullvad-doh |
| `force_doh_cloudflare` | DNS_BLOCK | прибить DoH к https://1.1.1.1/dns-query |
| `force_doh_quad9` | DNS_BLOCK | прибить DoH к https://9.9.9.9/dns-query |
| `enable_padding` | THROTTLE, BEHAVIORAL | random padding bytes на каждый пакет (anti-ML) |
| `switch_to_hysteria2` | THROTTLE | uplink на Hysteria2 (UDP, BBR-like congestion) |
| `multipath_outbounds` | THROTTLE | sing-box `multipath: true`, два пути одновременно |
| `mimic_chrome_ja3` | TLS_FP_BLOCK | uTLS profile = `chrome_124` |
| `mimic_safari_ja3` | TLS_FP_BLOCK | uTLS profile = `safari_17` |
| `enable_ech` | ECH_BLOCK (paradoxically helpful) | включить ECH с CF-edge ECHConfig |
| `disable_ech_use_real_sni` | ECH_BLOCK | если ECH блокируется — fallback на чистый SNI белого домена |

## Применение рецептов (logical flow)

```
incident.block_type → recipe_priority_list
→ try recipes in order, with snapshot/rollback
→ verify by re-probing the same vantage with same profile
→ if recipe worked: store in `learned_rules` per (asn, block_type, recipe)
→ if all recipes failed: ESCALATE to llm_decision.py
```

## Per-ASN learning

После N успешных применений `(asn, block_type, recipe)` мы поднимаем
этот рецепт в priority list для будущих incident-ов на том же ASN. Это
реализует тот «обучающийся» слой, который в задаче от пользователя
описан как «вне зависимости от провайдера, мобильный, домашний — система
сама подстраивается».

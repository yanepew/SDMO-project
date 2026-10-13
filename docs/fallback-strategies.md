# Fallback strategies when the ML-KEM channel fails

**Status: design only, nothing here is implemented yet.**

Failure causes to plan for: cloud overloaded or under DoS (the pure-Python KEM
makes decapsulation relatively expensive, so handshake floods are a real
amplification vector), cloud restart/key rotation, network outage, a bug or
break in the ML-KEM library or the ML-KEM algorithm itself.

The central rule: **availability fallbacks must not become security
downgrades.** An attacker who can make ML-KEM fail (e.g. by flooding) must not
thereby be able to push the system onto a weaker protocol.

## Recommended, in priority order

| # | Strategy | Protects against | Security cost | Effort |
|---|----------|------------------|---------------|--------|
| 1 | **Store-and-forward + exponential backoff with jitter + circuit breaker** (persist unsent aggregates on the gateway, bounded queue, retry later) | outage, DoS, restarts | none | low |
| 2 | **Cloud-side handshake DoS hardening**: allow-list check before KEM work (already done), per-gateway rate limit, stateless retry cookie (as in DTLS/QUIC) so the expensive decapsulation happens only for peers that proved reachability, cap on pending sessions (already done) | handshake floods | none | low–medium |
| 3 | **Session resumption with a PSK** derived from the last successful ML-KEM session (rotating ticket); skips the KEM when the cloud is busy | CPU exhaustion, frequent reconnects | low (PSK has no fresh KEM contribution, so limit lifetime/uses) | medium |
| 4 | **Hybrid key exchange** X25519 + ML-KEM-768, secrets concatenated into the HKDF | a future break of ML-KEM or a library bug | none (strictly stronger) | medium |
| 5 | **Policy-gated classical fallback** (mutual TLS 1.3, pinned certs) only when an operator enables it: time-limited, alerts the operator, logged, never automatic on a mere timeout | prolonged ML-KEM-specific failure | **downgrade risk**, loses PQ protection (harvest-now-decrypt-later) | medium |
| 6 | **Out-of-band export** (operator-triggered encrypted file transfer) | long total outage | operational | low |

## Recommendation

Implement **1 + 2 first**: they fix the realistic failure (DoS or outage) at no
security cost, and the gateway already keeps unsent readings in memory.
Add **3** to remove KEM cost from the steady state, and **4** if long-term
confidentiality of patient data justifies belt-and-braces. Treat **5** as an
emergency, human-approved switch rather than an automatic path; do **not**
silently fall back to plain HTTPS or to the legacy (unauthenticated) scheme.

Notes for implementation:
* Bound the gateway queue (disk quota, oldest-first or priority drop with
  an alert for threshold-breaching readings) so an outage cannot exhaust edge memory.
* Alerts for abnormal vitals are raised locally by the gateway and do not depend
  on the cloud, so a cloud/channel outage never suppresses nurse alerts.
* Fail closed: any authentication failure of a cloud response must discard
  the session (already done) and never retry in plaintext.

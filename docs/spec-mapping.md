# Spec Eşleme Tablosu

**Durum: v1 — 27 Temmuz 2026.** Veri toplamadan önce yazıldı.

Bu tablo makalenin totoloji savunmasıdır. Her kontrolün yer gerçeği, yazarların kanaati
değil, **yayımlanmış bir spesifikasyon cümlesidir**. `docs/decision-rules.md` R1 uyarınca
bir kontrol yalnızca MUST düzeyinde bir cümle gösterebiliyorsa başarısızlık raporlayabilir;
bu kural `models.py` içinde makine ile zorlanır.

**Doğrulama durumu:** ✅ birebir alıntı doğrulandı · ⚠️ alıntı teyit edilmeli (ilk koşudan
önce zorunlu)

---

## Modalite 1 — İmzalı doküman (A2A Agent Card, did:web)

| ID | Kontrol | Spec | Bölüm | Güç | Durum |
|---|---|---|---|---|---|
| **C01** | Kimlik dokümanı sunuluyor mu | A2A | Agent Discovery | **SHOULD** | ✅ |
| **C02** | Doküman JWS imzası taşıyor mu | A2A | §4.4.7 / §8.4 | **MAY** (yayıncı için OPTIONAL) | ✅ |
| **C03** | `kid`/`jku`/did:web anahtara çözümleniyor mu | A2A + RFC 7515 | §8.4 | **MUST** (imza varsa) | ✅ |
| **C04** | İmza gerçekten doğruluyor mu | A2A + RFC 7515 + RFC 8785 | §8.4 | **MUST** (imza varsa) | ✅ |

**C01 — konum normatif, yayınlama zorunluluğu değil.**
> *"The standard path is `https://{agent-server-domain}/.well-known/agent-card.json`"*
> — [A2A Agent Discovery](https://a2a-protocol.org/latest/topics/agent-discovery/)

Kart sunmama bir ihlal değildir → C01 başarısızlığı `UNSPECIFIED`'dır, `FAIL_*` değil.
`/.well-known/agent.json` v0.3 öncesi takma addır; bulunduğunda sürüm notuyla kaydedilir.

**C02 — yükümlülük yayıncıda değil, doğrulayıcıda.**
> *"Verifiers **SHOULD** verify at least one signature before trusting an Agent Card."*
> — [A2A Specification §8.4](https://a2a-protocol.org/latest/specification/)

`signatures` alanı **OPTIONAL**. İmzasız kartı "başarısız" saymak yazarların rubriği olurdu.
→ `DESCRIPTIVE_ONLY`. Yaygınlık olarak raporlanır (pilotta 25 kartın **1'i** imzalı), huni
kademesi olarak ceza kesmez.

**C04 — kanonikleştirme belirsizliği R6'yı tetikliyor.**
> *"the Agent Card content **MUST** be canonicalized using the JSON Canonicalization Scheme
> (JCS) as defined in RFC 8785"* — A2A §8.4. `signatures` alanı ve varsayılan değerli alanlar
> imzalanan yükten **MUST** dışlanır.

Varsayılan değerli alanların dışlanması pratikte belirsiz → R6 gereği bu sınıftaki
uyuşmazlıklar otomatik `UNSPECIFIED`, `FAIL_MISIMPLEMENTED` değil.

**⚠️ Doğrulanmış boşluk (makalenin normatif katkısı):** A2A spesifikasyonunda imzalı kartın
**tazeliği, `exp`/`nbf`'si ve anahtar iptali hakkında hiçbir normatif ifade yok.** Bu, C09 ve
C10'un neden kanaat sayıldığının kaynağıdır ve `UNSPECIFIED` kataloğunun en temiz örneğidir.

---

## Modalite 2 — OAuth metadata (MCP)

| ID | Kontrol | Spec | Güç | Durum |
|---|---|---|---|---|
| **C05** | Protected-resource metadata erişilebilir mi | MCP Authorization | **MUST** (yetkilendirme kullanılıyorsa) | ✅ |
| **C06** | AS metadata çözümleniyor ve geçerli mi | RFC 8414 | **MUST** | ✅ |
| **C07** | 401 `WWW-Authenticate: resource_metadata` taşıyor mu | MCP Authorization | ⚠️ MUST? | ⚠️ |
| **C12** | PRM `resource` değeri kaynak kimliğiyle özdeş mi | RFC 9728 §3.3 | **MUST** | ✅ |
| **C13** | İlan edilen issuer gerçekten o issuer'ı döndürüyor mu | RFC 8414 §3.3 | **MUST** | ✅ |
| **C14** | `code_challenge_methods_supported` ilan edilmiş mi | MCP Authorization | **MUST** | ✅ |

**Ön koşul — yetkilendirme opsiyoneldir.**
> *"Authorization is **OPTIONAL** for MCP implementations."*
> — [MCP Authorization](https://modelcontextprotocol.io/specification/latest/basic/authorization)

Bu yüzden C05 **koşulsuz uygulanamaz**: yalnızca 401/403 dönen, yani yetkilendirmeye opt-in
etmiş uçlarda uygulanır. Açık bir sunucuda PRM yokluğu ihlal değil, `NOT_APPLICABLE`'dır.
Pilotta 472 erişilebilir uçtan **179'u (%37,9)** bu koşulu sağlıyor → C05'in gerçek paydası
budur, 472 değil.

**C05 — yetkilendirme kullanılıyorsa zorunlu.**
> *"MCP servers **MUST** implement OAuth 2.0 Protected Resource Metadata (RFC9728). MCP
> clients **MUST** use OAuth 2.0 Protected Resource Metadata for authorization server
> discovery."*
>
> *"The Protected Resource Metadata document returned by the MCP server **MUST** include the
> `authorization_servers` field containing at least one authorization server."*

Keşif iki yoldan: `WWW-Authenticate` başlığı **veya** well-known URI; well-known iki formda
(yol-eklemeli ve kök). `config.prm_candidate_urls()` her ikisini de üretir — yalnız kök formu
denemek, doğru yapılandırılmış sunucularda **yapay başarısızlık** üretirdi.

**C12 — en güçlü eklenti (money finding adayı).**
> *"The `resource` value returned **MUST** be identical to the protected resource's resource
> identifier... If these values are not identical, the data contained in the response **MUST
> NOT** be used."* — [RFC 9728 §3.3](https://www.rfc-editor.org/rfc/rfc9728.html)

MUST düzeyinde, mekanik olarak kontrol edilebilir, ve pilotta 166 uç `authorization_servers`
ilan ediyor → gerçek `FAIL_MISIMPLEMENTED` üretme olasılığı yüksek. **Bu, projenin
go/no-go testinin merkezindeki kontroldür.**

**C13 — issuer özdeşliği.**
> RFC 8414 §3.3: döndürülen metadata'daki `issuer` değeri, metadata'nın istendiği issuer
> ile **özdeş olmalıdır**. RFC 9728 §7.6 ayrıca çapraz kontrolü tavsiye eder.

**C14 — PKCE beyanı sunucu tarafında bedava gözlenir.**
> *"If `code_challenge_methods_supported` is absent, the authorization server does not support
> PKCE and MCP clients **MUST** refuse to proceed."*

---

## Ölçülemeyen ve bu yüzden kapsam dışı bırakılanlar

| Ne | Neden pasif ölçümle görülemez |
|---|---|
| RFC 8707 resource indicators | *"MCP **clients** MUST implement Resource Indicators"* — yükümlülük istemcide. Sunucu dışarıdan gözlenemez. **C07 bu nedenle yeniden yazıldı.** |
| Token audience doğrulaması | *"MCP servers MUST validate that access tokens were issued specifically for them"* — sunucu içi davranış; doğrulamak için kimlik doğrulama denemesi gerekir, bu da etik kapsam dışıdır |
| Kart yeteneği ↔ scope tutarlılığı | Hiçbir spec bu tutarlılığı zorunlu kılmıyor → kontrol edilse yazarların rubriği olurdu. Plandan çıkarıldı, makalede gerekçesi yazılacak |

---

## Betimsel kontroller (asla başarısızlık raporlamaz)

| ID | Kontrol | Neden `DESCRIPTIVE_ONLY` |
|---|---|---|
| C02 | Kart imzalı mı | A2A'da yayıncı için OPTIONAL |
| C08 | DPoP / mTLS ilan edilmiş mi | Ne MCP ne RFC 9449 zorunlu kılıyor |
| C09 | `revocation_endpoint` ilan edilmiş mi | Hiçbir spec ajan kimliğinin iptal edilebilir olmasını istemiyor |
| C10 | Anahtar origin'i kamu CA köküne çıkıyor mu | "organisational trust root" hiçbir spec'te tanımlı değil; did:web zaten inşaen DNS+WebPKI'ye bağlı → yapay geçiş |

Bunlar makalede **yaygınlık istatistiği** ve `UNSPECIFIED` kataloğu olarak raporlanır. Huni
kademesi yapılmazlar. C09/C10'un spec karşılığının **olmaması**, bulgunun kendisidir:
ajan kimliği ekosisteminde iptal ve kurumsal bağ, kimsenin zorunlu kılmadığı özelliklerdir.

---

## Yardımcı kontroller

| ID | Kontrol | Spec | Güç |
|---|---|---|---|
| **C11** | Uç TLS'i geçerli mi | RFC 9728 + BCP 195; MCP: *"All authorization server endpoints **MUST** be served over HTTPS"* | **MUST** |
| **C15** | `alg` / anahtar gücü / `kid` çözünürlüğü | RFC 7518, BCP 195 | **MUST** (`none`, public JWKS ile `HS*`, RSA < 2048) |

---

## Yapılacak — ilk koşudan önce

- [ ] ⚠️ C07: MCP spec'inde `WWW-Authenticate` başlığının MUST mı SHOULD mu olduğunu birebir teyit et. SHOULD ise R1 gereği otomatik olarak `UNSPECIFIED`'a düşer — mekanizma zaten koruyor, ama tabloda doğru yazılmalı.
- [ ] Her `spec_url` için erişim tarihi ve varsa sürüm etiketi kaydet (R7).
- [ ] MCP revizyon beyanının uçtan nasıl okunacağını belirle (2025-11-25 vs 2025-06-18).

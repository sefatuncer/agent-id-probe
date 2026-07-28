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
| **C02** | Doküman JWS imzası taşıyor mu | A2A | §4.4.7 / §8.4 | **MAY** (yayıncı için OPTIONAL) | ⚠️ |
| **C03** | `kid`/`jku`/did:web anahtara çözümleniyor mu | A2A + RFC 7515 | §8.4 | **MUST** (imza varsa) | ⚠️ |
| **C04** | İmza gerçekten doğruluyor mu | A2A + RFC 7515 + RFC 8785 | §8.4 | **MUST** (imza varsa) | ⚠️ |

**⚠️ neden geri düştü (28 Tem 2026).** C02/C03/C04'ün ✅ işaretleri, a2a-protocol.org §8.4'ün
alıntılanan cümleleri **birebir doğrulanmadan** konulmuştu; bağımsız bir teyit turunda sayfa
§8.4'ü kesiyor ve cümleler doğrulanamadı. İşaret hak edilene kadar ⚠️ kalır.

**Bu, ölçüm açısından ucuz bir sorundur ve öyle çözülmelidir:** imzalı kart popülasyonu
pilotta **1**, tam korpusta beklenen **~10 (%95 GA [2, 58])**. Bu n ile hiçbir istatistik
ayakta durmaz. Karar: **FUNNEL_SIGNED derinliği (C03/C04/C15) dondurulur**, C01/C02 tek
paragraflık yaygınlık istatistiği olarak raporlanır, huni figürü çizilmez. Alıntı doğrulama
yükü de böylece C01'e (zaten ✅) iner.

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
| ~~C06~~ | ~~AS metadata çözümleniyor ve geçerli mi~~ | — | **SİLİNDİ 28 Tem 2026** | — |
| **C07** | 401 `WWW-Authenticate: resource_metadata` taşıyor mu | MCP Authorization | **revizyona bağlı** (aşağı bak) | ✅ |
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

**C07 — ⚠️ kapandı, ama beklenmedik bir sonuçla: normatif güç revizyona bağlı.**

Bu maddenin teyidi iki farklı cevap verdi ve **ikisi de doğru** — çünkü iki farklı MCP
revizyonundan geliyorlar:

| Revizyon | Birebir metin | C07'nin gücü |
|---|---|---|
| **2025-06-18** | *"MCP servers **MUST** use the HTTP header `WWW-Authenticate` when returning a `401 Unauthorized`"* | **MUST** → `FAIL_*` mümkün |
| **2025-11-25** | *"MCP servers **MUST** implement **one of the following** discovery mechanisms … 1. WWW-Authenticate Header … 2. Well-Known URI"* | başlık tek başına zorunlu **değil** → en fazla `UNSPECIFIED` |

Yani `WWW-Authenticate` başlığı olmayıp well-known'ı çalışan bir sunucu, güncel revizyonda
**tam uyumludur**. R7 (sürüm sabitleme) tam olarak bu durum için var: uç, beyan ettiği
revizyona göre puanlanır; beyan yoksa **en müsamahakâr yürürlükteki revizyon** uygulanır →
2025-11-25 → C07 ceza kesemez.

**Bu, R7'nin neden gerekli olduğunun en temiz örneğidir ve makaleye bu haliyle girmeli.**
C07'yi düz "MUST" diye kaydetmek, 2025-11-25'e göre doğru yapılandırılmış her sunucuya ihlal
yazardı — yani spec değişimini ekosistem arızası diye raporlardık.

**C12 — en güçlü eklenti (money finding adayı).**
> *"The `resource` value returned **MUST** be identical to the protected resource's resource
> identifier... If these values are not identical, the data contained in the response **MUST
> NOT** be used."* — [RFC 9728 §3.3](https://www.rfc-editor.org/rfc/rfc9728.html)

MUST düzeyinde, mekanik olarak kontrol edilebilir, ve pilotta (n=500) 166 uç
`authorization_servers` ilan ediyor → tam korpusta ~1.700 beklenir. **Bu, projenin karar
verici kontrolüdür.**

**⚠️ C12'nin beklenen değeri nasıl türetilir — kritik.** RFC 9728 §3.3'ün karşılaştırdığı
şey ucun ham URL'si **değil**, *"the resource identifier value into which the well-known URI
path suffix was inserted to create the URL used to retrieve the metadata"* — yani dokümanın
**geldiği** konumdan geri türetilen identifier. §3.1 ayrıca *"any terminating slash (/)
following the host component **MUST** be removed before inserting"* diyor. Bu iki cümle
birlikte türetmeyi tam olarak belirler ve kural **R9.1**'de dondurulmuştur.

Bu ayrım kozmetik değil: düzeltmeden önce enstrüman beklenen değeri ham uç URL'sinden bir kez
üretiyordu ve 8 büyük canlı MCP ucunda **%75** ihlal raporluyordu; doğru kuralla **%25**.
Aradaki fark tamamen enstrüman hatasıydı ve doğrudan makalenin manşet sayısıydı.

**C13 — issuer özdeşliği.**
> RFC 8414 §3.3, birebir: *"The `issuer` value returned **MUST** be identical to **the
> authorization server's** issuer identifier value into which the well-known URI string was
> inserted to create the URL used to retrieve the metadata."*
>
> RFC 8414 §4, birebir: *"Comparisons between the two strings **MUST** be performed as a
> Unicode code-point-to-code-point equality comparison."* — Unicode normalleştirmesi
> uygulanmaz. Bu, sondaki eğik çizginin affedilmesini **yasaklar** (R9.4).

**⚠️ C13'ün yükümlülük sahibi MCP sunucusu değil, authorization server'dır.** RFC 8414 §3.3
Auth0'ı, Okta'yı, Keycloak'ı bağlar. Dolayısıyla C13'ün analiz birimi **issuer'dır, uç
değil**: 166 uç muhtemelen 10–40 ayrı issuer ilan eder ve bir C13 ihlali "ajan ekosistemi
bozuk" değil, "şu IdP ürününde hata var" bulgusudur. R10.1 gereği C13 hem uç başına hem
**benzersiz issuer başına** raporlanır, ve makalede uç düzeyindeki hâli *"ilan edilen AS
tutarlı biçimde kendini tanıtmadı, dolayısıyla istemcinin keşif zinciri kopuyor"* olarak
yazılır — bu kaynak tarafı bir gözlemdir ve meşru biçimde uç-kapsamlıdır.

**RFC 9728 §7.6 çıpa olarak kullanılamaz.** Önceki kayıt C13'ün dayanağını "RFC 8414 §3.3 +
RFC 9728 §7.6" diye gösteriyordu. §7.6 ceza taşıyamaz, çünkü birebir metni şudur:

> *"Secure determination of appropriate authorization servers to use with a protected
> resource for all use cases is **out of scope for this specification**."*
>
> *"…lists in the protected resource metadata and authorization server metadata **should**
> be cross-checked against one another for consistency…"* — küçük harf `should`, RFC 2119
> anahtar kelimesi **değil**.

R1 uyarınca buradan en fazla `UNSPECIFIED` çıkar. §7.6 makalede **motivasyon** olarak
alıntılanır, **norm** olarak değil — ve motivasyon olarak son derece güçlüdür (aşağıya bak).

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
| **C16** | RFC 9207 `iss` desteği ilan edilmiş mi | Yükümlülük **istemcide** (BCP 240 §2.1), pasif prob istemciyi göremez |
| **C17** | İstemci kimliği önyüklenebiliyor mu (CIMD ∨ DCR) | MCP kayıt merdiveni "kullanıcıya sor"da bitiyor; hiçbiri zorunlu değil |
| **C18** | `protected_resources` yayımlanmış mı | RFC 9728 §4'te **OPTIONAL** |

Bunlar makalede **yaygınlık istatistiği** ve `UNSPECIFIED` kataloğu olarak raporlanır. Huni
kademesi yapılmazlar. C09'un spec karşılığının **olmaması** bulgunun kendisidir: ajan kimliği
ekosisteminde iptal, kimsenin zorunlu kılmadığı bir özelliktir.

> **⚠️ C06 ve C10 silindi (28 Tem 2026).** İkisi de enum'da ve bu tabloda tanımlıydı ama
> **hiçbir kod yolunda üretilmiyordu.** Yapmadığı bir ölçümü listeleyen bir makale, hakeme
> en ucuz öldürme fırsatını verir. C06 ayrıca gereksizdi: C13 zaten AS dokümanını çekip
> ayrıştırıyor, ayrıştırılamayan doküman orada başarısızlık yoluna düşüyor. C10'un ise
> çıpalanacak bir spec cümlesi yoktu — "organisational trust root" hiçbir spesifikasyonda
> tanımlı değil ve tanımlamak yazarların rubriği olurdu, ki bu itiraz bu projenin önceki üç
> çerçevesini öldürdü. C08, C09 ve C11 aynı durumdaydı ve **üretilir hâle getirildi**;
> üçünün de verisi zaten çekiliyordu. `tests/test_models.py` artık her `CheckId`'nin bir
> kod yolunda üretildiğini makineyle doğruluyor.

---

## Yardımcı kontroller

| ID | Kontrol | Spec | Güç |
|---|---|---|---|
| **C11** | Uç TLS'i geçerli mi | RFC 9728 + BCP 195; MCP: *"All authorization server endpoints **MUST** be served over HTTPS"* | **MUST** |
| **C15** | `alg` / anahtar gücü / `kid` çözünürlüğü | RFC 7518, BCP 195 | **MUST** (`none`, public JWKS ile `HS*`, RSA < 2048) |

---

## Ölçülmeyen ama ölçülmesi gereken — planda yoktu

**RFC 9728 §7.6 çapraz-kontrolünün konuşlandırılmış erişilebilirliği.** §7.6 tek azaltımı
öneriyor: kaynağın ilan ettiği issuer listesi ile AS'in ilan ettiği kaynak listesi karşılıklı
doğrulansın.

> **⚠️ Düzeltme (28 Tem 2026).** Bu paragraf önce *"RFC 8414'te böyle bir alan yoktur, yani
> azaltım imkânsızdır"* diyordu. **Yanlıştı.** RFC 9728 **§4** o alanı tanımlıyor, birebir:
>
> > *"this specification defines the authorization server metadata parameter
> > `protected_resources`, which enables the authorization server to explicitly list the
> > protected resources. … **OPTIONAL.** JSON array containing a list of resource identifiers
> > for OAuth protected resources that can be used with this authorization server."*
>
> Alan, RFC 8414'ün *"OAuth Authorization Server Metadata"* registry'sine kayıtlı. Yani
> mekanizma **vardır**; eksik olan şey konuşlandırmadır. Bu düzeltme bulguyu zayıflatmıyor,
> **güçlendiriyor**: "imkânsız" varyans göstermez ve totolojiye yakındır; *"alan tanımlı,
> kaç issuer yayımlıyor"* ise gerçek bir ampirik niceliktir ve %0 çıksa bile bu, IETF'e
> götürülebilir ölçülmüş bir sonuçtur.

**Ölçülecek nicelik:** ilan edilen issuer'ların kaçı AS metadata'sında `protected_resources`
yayımlıyor, ve yayımlayanlarda liste kaynağı gerçekten içeriyor mu (yani çapraz kontrol
*geçiyor* mu, sadece *mümkün* mü). `protected_resources` **OPTIONAL** olduğu için R1 gereği
`DESCRIPTIVE_ONLY` — yokluğu asla `FAIL_*` olamaz. Ek istek maliyeti sıfır: AS dokümanı C13
için zaten çekiliyor ve `ev.as_documents` içinde saklanıyor.

**`registration_endpoint` yaygınlığı (RFC 7591).** İlan edilen AS dinamik istemci kaydına
açıksa, saldırgan kaynağın güvendiği issuer'da kendine istemci alabilir. RFC 8414'te OPTIONAL
olduğu için R1 gereği `DESCRIPTIVE_ONLY`, ama ilan edilen güven ilişkisini betimsel bir
istatistikten güvenlik açısından anlamlı bir niceliğe çevirir. **Etik: yalnız alan varlığı
sayılır; kayıt denemesi yapılmaz** — o bir yazma işlemi olurdu.

**Ölü / devralınabilir issuer.** İlan edilen issuer'ın alan adı hâlâ kayıtlı mı (RDAP,
ücretsiz, anahtarsız)? Değilse bu bir güven çıpası devralma primitifidir. **Etik: bulunan
alan adı kaydedilmez.**

---

## Yapılacak — ilk koşudan önce

- [x] ⚠️ C07 teyidi tamamlandı → normatif güç **revizyona bağlı** çıktı, yukarıda kayıtlı.
- [ ] Her `spec_url` için erişim tarihi ve varsa sürüm etiketi kaydet (R7).
- [ ] MCP revizyon beyanının uçtan nasıl okunacağını belirle (2025-11-25 vs 2025-06-18) —
      C07'nin gücü buna bağlı olduğu için artık isteğe bağlı değil.
- [x] C06/C08/C09/C10/C11 çözüldü: C06 ve C10 **silindi**, C08/C09/C11 **üretilir hâle
      getirildi**. Makine koruması eklendi (`test_every_declared_check_is_actually_emitted_somewhere`).

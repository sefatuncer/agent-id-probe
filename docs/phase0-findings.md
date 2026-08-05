# Faz 0 — Öldürme Testi Bulguları

**Tarih:** 27 Temmuz 2026 · **Kaynak:** Reviewer B canlı pilotu (resmî MCP registry tam taraması + 500 alan adında huni pilotu) · **Maliyet:** 0 ₺

---

## 1. Korpus (öldürme testi kolu i)

### MCP — **GEÇTİ**

`registry.modelcontextprotocol.io/v0/servers` — kimlik doğrulaması yok, cursor sayfalama, ücretsiz.

| Ölçüm | Değer |
|---|---|
| Toplam kayıt (tüm sürümler) | 59.902 |
| Benzersiz sunucu | 18.747 |
| `remotes` içeren benzersiz sunucu | 9.276 (%49,5) |
| Sürüm bazında remote / yalnız-paket (stdio) | 20.986 / 38.198 (**%65 stdio**) |
| Benzersiz remote URL | 10.393 |
| Benzersiz host | 7.421 |
| **Benzersiz kayıtlı alan adı** | **5.154** |

Eşik ≥1.500 idi → **rahat geçiyor.**

Diğer ücretsiz kaynaklar (anahtarsız çalıştı): Smithery `registry.smithery.ai` 7.418 sunucu / 3.941 remote · Glama public REST 61.437 · PulseMCP 22.252 ama 403/410 döndürüyor, kırılgan.

### A2A — **KALDI**

Üç bağımsız kanıt, kamusal A2A dağıtımının yok denecek kadar az olduğunu gösteriyor:
- Kendi taraması: 43 yüksek-olasılıklı kurumsal host (Google, Salesforce, Atlassian, SAP, Okta) → **2 kart**, ikisi de imzasız
- OpenClaw Deney 055 (Nis 2026): A2A desteği *ilan eden* 50 ajan → geçerli kart **0–2**, A2A task isteğine yanıt **0** — doğrulandı: `a2aproject/A2A` issue #1755, *"Active A2A Outbound Probing"*
- ~~AgentHermes: 27 sektörde 500 işletme → sıfır `agent-card.json`~~ — **28 Tem 2026'da kaldırıldı: kaynak bulunamadı.** "500 işletme / sıfır kart" istatistiğini destekleyen bir yayın veya veri seti teyit edilemedi. Sonuç zaten yukarıdaki iki bağımsız kanıtla ayakta; doğrulanamayan üçüncü bir dayanak, doğrulanabilir olanları da şüpheli hale getirir

**Kurtarma:** MCP remote origin'lerini `/.well-known/agent-card.json` için yoklayınca 472 erişilebilir origin'de **25 geçerli kart (%5,3)** çıktı → 5.154 alana ölçeklenirse ~270. Eşiğin altında ama sıfır değil. **A2A ancak MCP korpusundan türetilerek var olabilir** — bu türetme yönteminin kendisi özgün bir metodolojik katkı. Bulunan kartlar uzun-kuyruk projeler (namewhisper.ai, brainonbnb.com), kurumsal değil → genelleme iddiası buna göre kısılmalı.

---

## 2. Canlı huni pilotu (n=500, alan adı başına 1 URL)

| Aşama | n | Oran |
|---|---|---|
| Erişilebilir | 472 | %94,4 |
| MCP `initialize` başarılı | 251 | %53,2 |
| 401/403 (auth zorunlu) | 179 | %37,9 |
| `WWW-Authenticate` başlığı | 147 | %31,1 |
| **RFC 9728 protected-resource metadata** | **173** | **%36,7** |
| `authorization_servers` ilan eden | 166 | %35,2 |
| A2A kartı bulundu | 32 | %6,8 |
| Geçerli A2A kartı | 25 | %5,3 |
| **Kriptografik olarak imzalı kart** | **1** | **%0,2** |

---

## 3. Scoop (öldürme testi kolu iii) — **KALDI**

| Çalışma | Ne yapmış | Etki |
|---|---|---|
| arXiv **2605.22333** | 7.973 canlı remote MCP sunucusu, **%40,55 auth yok**, OAuth kusur taksonomisi, 9 CVE | Huninin 1.–2. aşaması **zaten yayımlanmış**. Bizim %37,9'umuz aynı ölçümün diğer yüzü |
| arXiv **2607.11086** (MCPZoo) | 64.611 sunucu, ekosistem ölçeği | Ölçek üstünlüğü iddiası imkânsız |
| arXiv **2603.07473** | *"Give Them an Inch…: Caller Identity Confusion in MCP-Based AI Systems"* | **⚠️ 21 Tem 2026'da yazarlarınca GERİ ÇEKİLDİ.** Prior art olarak sayılamaz — aşağı bak |

---

**⚠️ Düzeltme (28 Tem 2026): 2603.07473 geri çekildi.** v2, 21 Temmuz 2026'da yazarlarınca
geri çekildi. Birebir gerekçe:

> *"Withdrawal due to some flaws in experimental methodology and unresolved ethical issues in
> data collection. We need to redesign the experiments and obtain proper ethical clearance
> before resubmission."*

İki sonucu var:

1. **Prior art olarak sayılamaz.** Bu tablo onu *"'prior work yok' iddiasını tek başına
   çürütür"* diye listeliyordu. Geri çekilmiş bir makale bunu yapamaz. Konumlandırma
   yeniden yazılmalı: kimlik karışıklığı üzerine *yayımlanmış ve ayakta duran* iş şu an
   düşündüğümüzden az. Yine de makalede **geri çekilme notuyla birlikte** anılmalı —
   sessizce düşürmek, aynı alanı çalışan hakemin gözünden kaçmaz.
2. **Bizim etik bölümümüz için canlı bir uyarı.** Geri çekilme gerekçesi tam olarak bizim
   maruz kaldığımız risk: veri toplamada çözülmemiş etik sorunlar. Aynı alanda, aynı yıl,
   aynı yöntem ailesinde bir makale bu sebeple geri çekildi. `docs/ETHICS.md` bu yüzden
   koşumun ön koşuludur, koşum sonrası bir yazım işi değil.

## 4. KARAR: Devam — ama yeniden çerçevelemeyle

Orijinal çerçeve ("ajan kimliğinin doğrulanabilirliğinin internet ölçeğinde ölçümü") **iki ucundan da kesildi**: giriş aşamaları scooplu, çıkış aşaması n=1.

**Hayatta kalan ve varyans gösteren tek bakir alan:** `authorization_servers` ilan eden 166 uçta **issuer ↔ resource ↔ audience üçlü tutarlılığı**. Buradaki spec cümleleri MUST düzeyinde ve mekanik olarak kontrol edilebilir:

> RFC 9728: *"The `resource` value returned **MUST** be identical to the protected resource's resource identifier... If these values are not identical, the data contained in the response **MUST NOT** be used."*
>
> RFC 8414 §3.3: `issuer` özdeşlik **MUST**'ı.

Önceki işler *"auth var mı"* sorusunu bitirdi. **Hiçbiri *"ilan edilen güven ilişkisi kendi içinde tutarlı ve kriptografik olarak bağlanmış mı"* sorusunu sormadı.**

**Yeni manşet:** "hiçbir şey doğrulanmıyor" değil → **"kimlik metadata'sı yaygın (%36,7), kriptografik bağ yok (%0,2), ve ilan edilen bağların tutarlılığı ölçülmemiş."**

**Konumlandırma kuralı:** Aşama 1–2 makalede **açıkça replikasyon** olarak etiketlenecek, katkı diye satılmayacak. Makalenin ağırlığı audience/issuer binding'e verilecek.

---

## 5. Alet düzeltmeleri (Reviewer A — veri toplamadan ÖNCE zorunlu)

**Yazarların rubriği olarak saldırıya açık 4 kontrol:** C02 (A2A'da `signatures` OPTIONAL), C08 (DPoP/mTLS zorunlu değil), C09 (hiçbir spec status list istemiyor), C10 ("organisational trust root" hiçbir spec'te tanımlı değil; **C10 sonradan tamamen silindi**). → Huniden çıkarılacak veya UNSPECIFIED bulgusu olarak raporlanacak.

> **Sonradan ne oldu (28 Temmuz 2026):** Bu dört kontrolün üçü betimsel oldu, **C10 ise tamamen
> silindi** — bağlanacak bir spec cümlesi yoktu ve bir tanesini kendimiz tanımlamak, bu tasarımın
> imkânsız kılmak için var olduğu şeyin ta kendisi olurdu. Bu belge pilotun tarihli kaydıdır ve
> geriye dönük düzeltilmez; enstrümanın güncel hâli için `check-catalogue.md` tek kaynaktır.

**Eklenecek kontroller:**
| ID | Kontrol | Spec çıpası |
|---|---|---|
| **C12** | PRM `resource` kimlik eşleşmesi | RFC 9728 — **MUST**, mekanik, en yüksek misimplementation olasılığı (money finding) |
| **C13** | `authorization_servers` ↔ AS `issuer` karşılığı | RFC 8414 §3.3 MUST + RFC 9728 §7.6 |
| C11 | TLS geçerliliği | RFC 9728 MUST + BCP 195; MCP "MUST be served over HTTPS" |
| C14 | PKCE beyanı (`code_challenge_methods_supported`) | MCP spec MUST |
| C15 | `alg`/anahtar gücü, `kid` çözünürlüğü | RFC 7518, BCP 195 |

**C05 ölçüm hatası:** `allowed_paths` yalnız kök formu içeriyor; spec ayrıca yol-eklemeli formu (`/.well-known/oauth-protected-resource/mcp`) **ve** `WWW-Authenticate: resource_metadata` yolunu tanımlıyor. Düzeltilmezse başarısızlık oranı yapay şişer.

**C07 ölçülemez:** RFC 8707 yükümlülüğü *istemcidedir*; pasif prob göremez. C12'ye çevrildi.

**Huni ikiye ayrılacak:** Huni-M (MCP: reachable → C05 → C12 → C13 → C06/C14 — *C06 28 Temmuz'da
silindi, C14 29 Temmuz'da betimsel olup huniden çıktı, yani bu huni bugün C13'te bitiyor*) ve
Huni-A (A2A/did:web: reachable → C01 → C02 → C03 → C04). Tek huni, OAuth-only kimlik kullanan meşru bir ucu spec'in hiç istemediği bir kademede eliyor → şelalenin büyük kısmı başarısızlık değil **kompozisyon** olurdu.

---

## 6. Şimdi yazılması gereken 8 karar kuralı (post-hoc suçlamasını yapısal olarak imkânsız kılar)

1. **Normatif güç kuralı:** Bir kontrol yalnız `spec_ref` bir **MUST/SHALL** cümlesi gösteriyorsa `FAIL_*` dönebilir. SHOULD → UNSPECIFIED. MAY/sessizlik → NOT_APPLICABLE. → `CheckResult.normative_strength` alanı eklenecek, kural makineyle denetlenecek.
2. **Öncelik:** ERROR > NOT_APPLICABLE > UNSPECIFIED > FAIL_MISIMPLEMENTED > FAIL_UNIMPLEMENTED > PASS
3. 200 + bozuk JSON = MISIMPLEMENTED; 404 = UNIMPLEMENTED. İstisnasız.
4. 403/429/WAF/Cloudflare challenge = **ERROR**, asla UNIMPLEMENTED.
5. ERROR ancak `max_retries` tükendikten sonra, ≥24 saat arayla ≥2 koşuda aynı sonuç verirse kesinleşir.
6. İki makul spec okuması farklı verdict veriyorsa → otomatik **UNSPECIFIED**.
7. **Sürüm sabitleme:** `CheckResult.spec_version`. Uç, beyan ettiği MCP revizyonuna göre puanlanır (2025-11-25 ≠ 2025-06-18).
8. n≈100 katmanlı örnekte MISIMPLEMENTED/UNSPECIFIED sınırı için iki-kodlayıcı Cohen kappa, önceden ilan edilmiş.

---

## 7. Ev IP'si — ölçüm geçerliliği riski (yeni, ciddi)

Pilotta 28/500 (%5,6) hiç yanıt vermedi; PulseMCP 403/410 döndürdü. **Bloklanma, ölçülen özellikle korele olabilir:** olgun/kurumsal uçlar WAF arkasında → örneklem sistematik olarak amatör uçlara kayar. Bulunan A2A kartlarının hepsinin uzun-kuyruk olması bu şüpheyi doğruluyor.

**Ücretsiz azaltım:** ortak yazarın **MSKÜ ağından** ikinci koşu (ULAKBİM AS'i akademik olarak tanınır) + aynı örneklemi iki ağdan koşup **blok oranı farkını raporlamak**. Bu fark başlı başına yayımlanabilir bir geçerlilik ölçümüdür ve Enis hocaya doğal, düşük maliyetli bir katkı verir.

---

## 8. Sıradaki belirleyici test (go/no-go)

### ⚠️ Eski kriter geçersiz — 28 Tem 2026'da değiştirildi, sessizce değil

Eski hâli şuydu: *"`authorization_servers` ilan eden ~166 uçta issuer ↔ resource ↔ audience
üçlü tutarlılığını ölç. Varyans %2–%90 arası → devam; %0 veya %100'e yapışık → durdur."*
Üç ayrı sebeple kullanılamaz:

1. **`audience` ölçülmüyor.** `spec-mapping.md`, token audience doğrulamasının pasif olarak
   gözlenemeyeceğini açıkça yazıyor. Dondurulmuş bir kriter, var olmayan bir ölçümü referans
   alıyordu.
2. **Nokta tahmini eşikle karşılaştırılıyordu, belirsizlik payı yok.** n=166'da k=3 → p̂=%1,8
   → "eşiğin altında, dur". Oysa %95 GA [%0,6, %5,2] ve %5'i içeriyor. Hesaplandı: gerçek
   ihlal oranı %1 ise bu kural projeyi **%19 olasılıkla yanlışlıkla öldürür**; %0,5 ise
   **%43,5**. Tam korpusta %1 oran ~17 uç demektir — makale için fazlasıyla yeterli.
3. **Yanlış kola bakıyordu.** Mevcut çerçeve ihlal oranına değil, **delegasyon dağılımına**
   dayanıyor. C12/C13 %99 PASS dönse bile "N kaynak M issuer'a delege ediyor, %X
   çapraz-işletmeci, top-1 issuer korpusun %Y'sini taşıyor" bulgusu ayakta kalır.

**Ayrıca kayda geçirilmesi gereken bir şey daha var.** `ARASTIRMA-PLANI.md` §5'in öldürme
testi *"100 uçta imzalı/doğrulanabilir oran %2–%90 arasında… her yerde %0 ise → ÖLDÜR"*
diyordu ve *"pazarlık konusu değildir"* notu taşıyordu. Pilot **%0,2** verdi — eşiğin
**altında**. Proje öldürülmedi; karar verici ölçüm imzalı-doküman kolundan OAuth koluna
kaydırıldı. Bu pivot savunulabilir — imza hunisi öldü, OAuth hunisi bakir — ama **kriterin
düştüğü hiçbir yere yazılmamıştı.** Projenin tüm kimliği R1–R8 ile post-hoc'u imkânsız
kılmak üzerine kurulu; kriter düşünce sessizce hedef değiştirmek tam da o savunmanın
yasakladığı hamledir. Kayıt buraya, olduğu gibi geçirilmiştir. Makalede de aynen anlatılır:
**imza modalitesi önceden ilan edilmiş eşiğinde düştü ve bu yüzden betimsel bir sonuca
indirildi; ölçüm ağırlığı OAuth modalitesine taşındı.**

### Yeni kriter (28 Tem 2026'da, veriden önce donduruldu)

Ara go/no-go kapısı **kaldırılmıştır.** Gerekçesi yukarıdaki (2): n=166'lık bir ara kararın
tek etkisi yanlış öldürme riski üretmek. Dar kesit koşusu **etik ve operasyonel** doğrulama
içindir (blok oranı, host hata bütçesi, oran politikası, UA erişilebilirliği) — istatistiksel
karar için değil.

Tam korpus (~1.700 `authorization_servers` ilan eden uç beklenir) koşulur ve **durdurma
kararı yalnızca şu koşulda verilir:**

> Çapraz-işletmeci delegasyon oranının **küme-robust %95 güven aralığının tamamı** [0, %2]
> aralığında kalırsa → makale bir ölçüm notuna iner, dergi hedefi düşürülür.

Nokta tahmini değil, aralık. Naif Wilson değil, küme-robust (R10.4) — çünkü kümelenme altında
naif aralığın gerçek kapsaması %95 değil, senaryoya göre %45–%82'dir.

**Ölçümün kendisi C12/C13 ihlal oranına indirgenemez.** Manşet nicelikler:
issuer yoğunlaşması (HHI, top-k payı) · çapraz-işletmeci delegasyon oranı (üç önceden ilan
edilmiş vekil altında: apex, ASN, sertifika) · tenant ayrımı olmayan çok-kiracılı issuer ·
RFC 9728 §7.6 çapraz-kontrolünün fiilen mümkün olduğu AS oranı.

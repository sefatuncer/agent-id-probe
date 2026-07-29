# Karar Kuralları

**Durum: DONDURULDU — ana ölçüm koşusundan önce. Değişiklikler aşağıdaki günlükte.**

Amaç, "sonucu sonradan seçtiniz" (post-hoc / HARKing) suçlamasını yapısal olarak imkânsız
kılmak. Kuralların çoğu `models.py` içinde makine ile zorlanır; zorlanamayan ikisi (R5, R8)
koşum protokolünde belirtilmiştir.

## Dondurmanın kapsamı — dürüst beyan

Bu kurallar **ana ölçüm koşusundan önce** donduruldu, ama **her veriden önce değil.** 27
Temmuz 2026'da n=500'lük keşif amaçlı bir pilot koşuldu (`phase0-findings.md`) ve bu pilot
enstrümanın *tasarımını* doğrudan etkiledi: C05'in aday URL kümesi düzeltildi, C11–C15
eklendi, C07 ölçülemez bulunup yeniden yazıldı, huni ikiye ayrıldı. Bu normal ve meşru bir
pilot→kalibrasyon döngüsüdür, ama "kurallar veri görülmeden yazıldı" cümlesi **yanlış
olurdu ve kaldırılmıştır.**

Bağlayıcı beyan şudur:

1. Pilot verisi **sonuç olarak raporlanmaz.** Pilottaki hiçbir sayı makalede bulgu diye
   geçmez; ana koşuda düzeltilmiş enstrümanla yeniden ölçülür. Pilot yalnızca enstrüman
   geliştirme gerekçesi olarak, açıkça "pilot" etiketiyle anlatılır.
2. Aşağıdaki kuralların **hiçbiri** ana koşunun verisi görüldükten sonra değiştirilemez.
3. Her değişiklik bu dosyanın başındaki günlüğe tarih ve commit ile yazılır. Günlüğü olmayan
   değişiklik geçersizdir.

## Değişiklik günlüğü

**Commit `a1408d1` (29 Tem 2026), aşağıdaki 2026-07-28 ve 2026-07-29 tarihli tüm satırları
kapsar.** O tarihe kadar bu kuralların hiçbiri commit edilmemişti — yani "veriden önce
donduruldu" ifadesinin arkasında bir zaman damgası yoktu, yalnız bir iddia vardı. Bu
kaydın kendisi de o commit'te.

| Tarih | Kural | Değişiklik | Gerekçe |
|---|---|---|---|
| 2026-07-27 | R1–R8 | İlk dondurma (commit `e27e5dd`) | Pilot sonrası, ana koşudan önce |
| 2026-07-28 | R8 | İnsan kodlayıcı + Cohen kappa → fikstür paketi + replay determinizmi (commit `67dfbfd`) | Kappa, rubrik puanlayan tasarımların aracıdır; bu enstrüman mekaniktir, ölçülecek öznellik yok |
| 2026-07-28 | **R9** | **Yeni** — identifier karşılaştırma politikası | 3 agent'lı review: C12'nin beklenen değeri yanlış türetiliyordu ve C12/C13 zıt katılıktaydı. Karşılaştırma politikası yazılı olmadan koşmak, manşet ihlal oranını yazılmamış bir yargı çağrısına bırakmaktı |
| 2026-07-28 | **R10** | **Yeni** — analiz birimi ve küme tanımı | Aynı review: uçlar bağımsız değil; küme tanımını veriden sonra seçmek "istediğiniz GA'yı veren kümelemeyi seçtiniz" itirazına açık |
| 2026-07-28 | R7 | Revizyon kümesi tarihle sabitlendi | "En müsamahakâr yürürlükteki revizyon" ifadesi, koşum günü çıkan bir revizyonu sessizce yutuyordu |
| 2026-07-28 | **C16–C18 + R11** | **Yeni** — üç betimsel kontrol (RFC 9207 `iss` ilanı, istemci önyükleme, RFC 9728 §4 `protected_resources`) ve manşet seçim kuralı | Üçü de **zaten çekilen** AS metadata dokümanından okunuyor, ek ağ maliyeti sıfır. Hangisinin makaleyi taşıyacağı veri görülmeden bilinemez; adayları önceden ilan edip seçimi kurala bağlamak, veriye bakıp en gösterişli sayıyı manşet yapmanın tek dürüst alternatifi |
| 2026-07-28 | **R10.2** | **Birincil analiz birimi değiştirildi**: "normalize PRM bayt şekli SHA-256" → **apex alan adı**. Eski tanım uygulanamazdı | "Host'a özgü alanlar" elle liste gerektiriyordu (kuralın kendi "yazarların rubriği olamaz" iddiasını çürütüyordu); çözünürlüğü yoktu (m≈3–8 → R10.4 imkânsız); serializer'a duyarlıydı; ve kodda hiç yoktu |
| 2026-07-28 | **R10.2b** | **Yeni** — değersiz implementasyon parmak izi (anahtar adları + JSON tipleri + `server` ailesi) | R10.2'nin iddia ettiği ama sağlayamadığı özelliği fiilen sağlar: hash'e hiçbir değer girmez |
| 2026-07-28 | **R10.1** | Birim değişince **paydanın da** değişeceği yazıldı (apex/implementasyon başına 1 uç), temsilci uç kuralı sabitlendi (en küçük `endpoint_id`) | Yalnız kümelemeyi değiştirmek nokta tahminini değiştirmiyordu; 300 listelemesi olan bir toplu yayıncı yine manşeti belirlerdi |
| 2026-07-28 | **Go/no-go** | Eski kriter **geçersiz ilan edildi**, yenisi yazıldı (`phase0-findings.md` §8) | Ölçülmeyen bir niceliğe (`audience`) dayanıyordu; nokta tahminini eşikle karşılaştırıyordu; ölü kola bakıyordu |
| 2026-07-28 | **C06, C10** | **Silindi** | İkisi de tanımlı, dokümante ve **hiçbir kod yolunda üretilmiyordu**. C06 ayrıca C13 ile gereksiz tekrardı; C10'un çıpalanacak spec cümlesi yoktu |
| 2026-07-28 | **C08, C09, C11** | **Üretilir hâle getirildi** | Aynı durumdaydılar; verileri zaten çekiliyordu. `DESCRIPTIVE_ONLY` kümesinin fiilî içeriği değişti |
| 2026-07-29 | **R7** | ⚙️ → 📋 düşürüldü; "tek yol `initialize`" gerekçesi **yanlış olduğu için düzeltildi**; 2025-03-26 varsayılanı kayda geçirildi | `spec_version` hiç set edilmiyor. `MCP-Protocol-Version` bir çıkarım kanalı sunuyor (MUST 400) ama prob'dur, ek istek gerektirir ve 401 tarafından yutulur |
| 2026-07-29 | **C16/C17/C18 paydası** | Yalnız *gözlenen* issuer sayılıyordu; artık **gözlenen ve ilan edilen** birlikte kaydediliyor | Erişilemeyen bir issuer C16'yı PASS'e itiyordu — ki C16 R11.1'in **1. manşet adayı** ve R11.3 zaten "%100'e yapışabilir" diye uyarıyordu |
| 2026-07-29 | **C18** | Boş `protected_resources` artık "yayımlıyor" **sayılmıyor**; `empty_list` ayrı raporlanıyor | Boş liste çapraz kontrolü mümkün kılmaz. **2. manşet adayını** şişiriyordu |
| 2026-07-29 | **R10.4** | **Varyans tabanı**: yayımlanan aralık basit-rastgele-örneklem varyansının altına inemez | Küme-arası tahmin edici küme içi binom varyansını saymıyordu; `n_eff` `n`'i 313 kat aşabiliyor, `n=1000`'de `%49,9 [%49,7–%50,1]` yayımlanabiliyordu. Bootstrap'e sıfır-genişlik koruması eklendi |
| 2026-07-29 | **Kapsam** | `WWW-Authenticate` ipucu yalnız `https` **ve** kaynağın kendi apex'i içinde izlenir | İpucu ölçülen host'un kontrolündeki girdidir; `startswith("http")` kontrolü loopback ve RFC 1918'e istek gönderiyor ve saldırganın issuer'ını kurbanın grafiğine yazdırıyordu |
| 2026-07-29 | **Kapsam** | `/.well-known/agent.json` **çıkarıldı** | Listede vardı, hiç istenmiyordu. Eklemek ~5.000 origin'e fazladan istek demekti; kapsam beyanının yanlış olması ise kabul edilemezdi |
| 2026-07-29 | **`AbortPolicy`** | Eşik 200 → **50** uç | 200'de dar kesit provasında hiç silahlanmıyordu — provanın amacı tam koşuyu denemek |
| 2026-07-28 | **R9.2–R9.5** | **Aynı gün düzeltildi** — `trailing_slash_only` C12'de `FAIL` iken `UNSPECIFIED`'a indirildi; `case_only` ikiye bölünüp yol/query farkı `FAIL` yapıldı; RFC 3986 §6.2.2.1/§6.2.3 ve RFC 9728 §6 çıpa olarak eklendi | İkinci review turu, R9'un ilk hâlinin **kendi test paketiyle çeliştiğini** gösterdi: aynı metadata URL'sinden gelen iki doküman zıt hüküm alıyordu. §3.1 eşlemesi kayıplı, dolayısıyla geri türetme tek değerli değil. Ayrıntı R9.4'te |

---

## R1 — Normatif güç kuralı ⚙️ *(kodla zorlanır)*

Bir kontrol yalnızca `spec_ref`'i **MUST / SHALL** düzeyinde bir cümle gösteriyorsa
`FAIL_UNIMPLEMENTED` veya `FAIL_MISIMPLEMENTED` döndürebilir.

| Spec gücü | İzin verilen en ağır sonuç |
|---|---|
| MUST / SHALL | `FAIL_*` |
| SHOULD | `UNSPECIFIED` |
| MAY / sessiz | `NOT_APPLICABLE` |

`CheckResult.model_post_init` bunu doğrular ve ihlalde `ValueError` fırlatır.

**Sonuç:** C02 (A2A `signatures` OPTIONAL), C08 (DPoP/mTLS zorunlu değil), C09 (hiçbir spec
ajan kimliğinin iptal edilebilir olmasını istemiyor), C10 ("organisational trust root" hiçbir
spec'te tanımlı değil) **tanımsal olarak başarısızlık raporlayamaz**. `DESCRIPTIVE_ONLY`
kümesindedirler; yaygınlık istatistiği olarak raporlanır, huni kademesi yapılmaz.

---

## R2 — Sonuç önceliği ⚙️

Bir kontrol için birden çok gözlem çelişirse:

```
ERROR > NOT_APPLICABLE > UNSPECIFIED > FAIL_MISIMPLEMENTED > FAIL_UNIMPLEMENTED > PASS
```

`resolve_precedence()` ile uygulanır. Gerekçe: bilemediğimiz bir şeyi asla ihlal olarak
raporlamayız.

---

## R3 — Bozuk doküman vs. eksik doküman

| Gözlem | Sonuç |
|---|---|
| HTTP 200 + spec'e uymayan/ayrıştırılamayan JSON | `FAIL_MISIMPLEMENTED` |
| HTTP 404 / 410 | `FAIL_UNIMPLEMENTED` |

İstisnasız. "Bozuk ama iyi niyetli" diye bir kategori yoktur.

---

## R4 — Erişim engeli bulgu değildir

403, 429, WAF/Cloudflare interstitial, CAPTCHA, TLS el sıkışma reddi → **`ERROR`**,
asla `FAIL_UNIMPLEMENTED`.

Bu kritik: engellenmiş yanıtları başarısızlık saymak, tam da ölçtüğümüz özellikle korele bir
yanlılık üretir (olgun/kurumsal uçlar WAF arkasındadır). Engel tespiti hevristiği
`fetcher.py` içinde ve veri toplamadan önce sabittir.

---

## R5 — ERROR'un kesinleşmesi 📋 *(koşum protokolü)*

Bir `ERROR`, ancak `max_retries` tükendikten sonra **≥24 saat arayla en az 2 ayrı koşuda**
aynı sonucu verirse kesinleşir. Tek koşuluk ERROR'lar analizde ayrı raporlanır ve
paydadan çıkarılır.

---

## R6 — Bizim belirsizliğimiz UNSPECIFIED'dır ⚙️

Bir gözlem için iki makul spec okuması farklı verdict üretiyorsa, sonuç otomatik olarak
`UNSPECIFIED`'dır — bizim tercihimiz değil.

Bilinen örnek: RFC 8785 JCS kanonikleştirmesinde varsayılan değerli alanların dışlanması,
A2A spec'inde net değil. Bu yüzden C04'te bu sınıf yanlış `FAIL_MISIMPLEMENTED` üretmeye
adaydır ve baştan `UNSPECIFIED`'a yönlendirilir.

`UNSPECIFIED` bulguları makalenin **normatif katkısıdır**: standart kurumlarına
(A2A, MCP, OpenID Foundation, IETF OAuth WG) belirsiz-madde kataloğu olarak geri verilir.

---

## R7 — Sürüm sabitleme 📋 *(koşum protokolü — ⚙️ işareti 29 Tem 2026'da düşürüldü)*

> **⚠️ Bu kuralın bir dalı mevcut tasarımda uygulanamaz ve bunu yazmak zorundayız.**
>
> R7 "her uç kendi beyan ettiği spec revizyonuna göre puanlanır" diyor ve `⚙️` ile
> "kodla zorlanır" iddia ediyordu. **`CheckResult.spec_version` hiçbir yerde set
> edilmiyor.**
>
> **⚠️ Bu notun ilk hâli "öğrenmenin tek yolu `initialize`'dır" diyordu. Bu yanlıştı ve
> doğrulanabilir biçimde yanlıştı** (düzeltildi 29 Tem 2026). MCP Streamable HTTP,
> her iki dondurulmuş revizyonda da birebir aynı cümleyi taşıyor:
>
> > *"If the server receives a request with an invalid or unsupported
> > `MCP-Protocol-Version`, it **MUST** respond with `400 Bad Request`."*
>
> Yani bir **çıkarım kanalı vardır**: farklı sürüm başlıklarıyla istek atıp 400 gelip
> gelmediğine bakılabilir. Kullanmama gerekçemiz imkânsızlık değil, şunlar:
> (a) bu bir *beyan okuma* değil **prob**'dur — spec sunucudan sürüm ilan etmesini
> istemiyor, biz çıkarıyoruz; (b) revizyon başına uç başına bir ek istek, yani üçüncü
> taraflara ~5.000 istek daha; (c) karar popülasyonu 401 dönen uçlardır ve yetkilendirme
> kontrolü sürüm kontrolünden önce çalışıyorsa 401 döner, hiçbir şey öğrenilmez — #24'ü
> kesen argümanın aynısı burada da geçerli.
>
> **Sonuç:** beyan okunmadığı için her uç, aşağıdaki dondurulmuş kümenin **en
> müsamahakâr** revizyonuna göre puanlanır. Şüphe deployment lehinedir.
>
> **Ve bunun bir bedeli var, Limitations'a yazılmıştır.** Aynı bölüm şunu da diyor:
>
> > *"if the server does **not** receive an `MCP-Protocol-Version` header … the server
> > **SHOULD** assume protocol version `2025-03-26`."*
>
> Probumuz bu başlığı göndermiyor, dolayısıyla uyumlu bir sunucu isteğimizi **2025-03-26**
> olarak işler — dondurulmuş puanlama kümesinde **olmayan** bir revizyon. Başlığı
> göndermek çözüm değil, daha kötüsü: desteklemeyen bir sunucu MUST gereği **400** döner
> ve ölçümü bozar. Bu asimetri kayda geçirilmiştir; puanlama en müsamahakâr revizyona
> göre yapıldığı için yön yine deployment lehinedir.
>
> Bunun görünür tek etkisi C07'dir: normatif gücü revizyona bağlı olduğu için
> (2025-06-18 MUST, 2025-11-25 "one of"), okunamayan beyan onu kalıcı olarak müsamahakâr
> okumaya düşürür ve C07 ceza kesemez. `spec-mapping.md` bunu zaten böyle kaydediyor.

---

### R7 (asıl metin)

Her uç, **kendi beyan ettiği spec revizyonuna** göre puanlanır (`CheckResult.spec_version`).
MCP 2025-11-25 ile 2025-06-18 farklı gereksinimlere sahiptir; revizyonu karıştırmak,
ekosistemi değil spec değişimini ölçmek demektir.

Beyan yoksa: uç, ölçüm tarihinde yürürlükte olan en son revizyona göre değil, **en
müsamahakâr yürürlükteki revizyona** göre puanlanır. Şüphe deployment lehinedir.

**Revizyon kümesi tarihle sabitlenmiştir.** "Yürürlükteki revizyon" ifadesi, koşum günü
yayımlanan bir revizyonu sessizce yutar ve dondurmayı fiilen geçersiz kılar. Bu çalışmanın
puanlama tabanı: **MCP `2025-06-18` ve `2025-11-25`; RFC 9728, RFC 8414, RFC 8707 yayımlanmış
hâlleri; A2A v0.3.** Bu kümeden sonra yayımlanan hiçbir revizyon puanlamaya girmez; ölçüm
penceresi içinde yeni revizyon çıkarsa Limitations'da adıyla anılır, kurala eklenmez.

---

## R8 — Enstrüman geçerliliği: fikstür paketi + replay determinizmi ⚙️

*Bu kural 28 Temmuz 2026'da yeniden yazıldı. Önceki hali iki bağımsız insan kodlayıcı ve
Cohen kappa istiyordu. Bu, **rubrik puanlayan** bir tasarımın geçerlilik aracıdır ve bizim
tasarımımıza uymuyor: buradaki kontroller mekaniktir (`declared == expected`), insan yargısı
içermez, dolayısıyla değerlendiriciler arası güvenilirlik ölçülecek bir nicelik yoktur.
Kappa raporlamak, olmayan bir öznelliği varmış gibi göstermek olurdu.*

Mekanik bir uygunluk enstrümanının geçerliliği üç ayakla kurulur:

1. **Conformance fikstür paketi.** Her MUST düzeyindeki kontrol için, spec metninden
   türetilmiş en az bir **bilinen-uyumlu** ve bir **bilinen-ihlal** fikstürü bulunur
   (`tests/fixtures/`). Enstrüman bunları doğru sınıflandıramıyorsa veri toplanmaz.
   Sınır vakaları (trailing slash, case, aynı host farklı yol) ayrı fikstür olarak durur.
2. **Replay determinizmi.** Aynı ham artefakt, ağa hiç dokunmadan yeniden puanlandığında
   **bit düzeyinde aynı** verdict'i üretmelidir. Tüm ham yanıtlar saklandığı için bu
   otomatik olarak test edilir (`test_replay_determinism`).
3. **R1'in makineyle zorlanması.** `CheckResult.model_post_init`, MUST çıpası olmayan bir
   kontrolün başarısızlık raporlamasını reddeder. Öznellik girebilecek tek kapı budur ve
   kapalıdır.

**Ölçüm:** fikstür paketinde %100 doğruluk + replay determinizmi. İkisinden biri sağlanmazsa
enstrüman düzeltilir ve tüm veri yeniden puanlanır (ham veri saklandığı için bu ücretsizdir).

---

---

## R9 — Identifier karşılaştırma politikası ⚙️ *(kodla zorlanır)*

C12 ve C13 makalenin karar verici ölçümüdür ve ikisi de "iki URI özdeş mi" sorusuna indirgenir.
Bu karşılaştırmanın nasıl yapıldığı, manşet ihlal oranını doğrudan belirler. Politika burada,
ana koşudan önce sabitlenmiştir.

### R9.1 — Beklenen değer, dokümanın **geldiği URL'den** türetilir

> RFC 9728 §3.3: *"The `resource` value returned **MUST** be identical to the protected
> resource's resource identifier value **into which the well-known URI path suffix was
> inserted to create the URL used to retrieve the metadata**."*
>
> RFC 9728 §3.1, **koşul cümlesi dahil** (bu koşul atlanırsa kural kök form için de
> geçerliymiş gibi okunur): *"**If the resource identifier value contains a path or query
> component**, any terminating slash (/) following the host component **MUST** be removed
> before inserting `/.well-known/` and the well-known URI path suffix between the host
> component and the path and/or query components."*

Beklenen değer, ucun ham URL'sinden **türetilemez** — dokümanın hangi aday konumdan geldiğine
bağlıdır:

| Doküman nereden geldi | Beklenen `resource` değeri |
|---|---|
| `https://h/.well-known/oauth-protected-resource/p` | `https://h/p` |
| `https://h/.well-known/oauth-protected-resource` (kök) | `https://h` |
| `WWW-Authenticate: resource_metadata=...` ipucu | **istemcinin kaynak sunucuya attığı URL** (RFC 9728 §3.3 ¶2) |

Kural **literaldir ve istisnasızdır**: beklenen değer her zaman dokümanın geldiği URL'den
türetilir. Kök forma düşülmüş ama uç URL'sinde yol varsa (ör. uç `https://h/sse`, doküman
kökten geldi, `resource: "https://h"`), bu **C12 başarısızlığı değildir** — doküman kendi
içinde tutarlıdır ve MCP kök forma düşmeyi açıkça emreder:

> MCP Authorization: *"clients … **MUST** fall back to constructing and requesting the
> well-known URIs in the order listed above"* (önce yol-ekli, sonra kök).

Bu dokümanın yol taşıyan ucu gerçekten kapsayıp kapsamadığı ayrı bir sorudur ve
`prm_scope_covers_endpoint` olarak **betimsel** kaydedilir; ceza kesmez. RFC 9728 §7.6 bu
seçimi zaten açıkça kapsam dışı bırakmıştır (*"out of scope for this specification"*), yani
buradan MUST düzeyinde bir ihlal türetmek R1'e aykırı olurdu.

**Gerekçe (neden bu kural gerekliydi):** düzeltmeden önce beklenen değer ham uç URL'sinden bir
kez üretiliyordu. 8 büyük canlı MCP ucunda ölçüldü: C12 ihlal oranı **%75** çıkıyordu, doğru
kuralla **%25**. Fark tamamen enstrüman hatasıydı.

### R9.2 — Kanonikleştirme **her iki tarafa da** uygulanır

Karşılaştırmadan önce, **her iki tarafa** yalnız RFC 3986'nın eşdeğer ilan ettiği
normalleştirmeler uygulanır:

| İşlem | Dayanak (birebir) |
|---|---|
| Fragment atılır | RFC 8707: identifier fragment içermez |
| Şema varsayılan portu atılır (`:443`/`:80`) | RFC 3986 §6.2.3 şema tabanlı normalleştirme |
| Şema ve host küçük harfe indirilir | RFC 3986 §6.2.2.1: *"the **scheme and host** are case-insensitive and therefore should be normalized to lowercase"* |
| Kök yol `/` ile boş yol eşitlenir | RFC 3986 §6.2.3: *"the following four URIs are equivalent: `http://example.com` / `http://example.com/` / …"* |

**Yol ve query küçük harfe indirilmez.** Aynı RFC 3986 §6.2.2.1 cümlesi devam ediyor: *"The
other generic syntax components are assumed to be **case-sensitive** unless specifically
defined otherwise by the scheme."* Tüm URI'yi küçültmek `/MCP` ile `/mcp`'yi affederdi; bunlar
farklı yollardır.

Tek tarafa uygulamak, uyumlu bir sunucuyu taksonominin en ağır kovasına düşürür.

### R9.2b — Katılık kuralının **iki** çıpası var, ikisi de anılır

C13 için RFC 8414 §4 alıntılanıp C12 için RFC 9728'in aynı kuralının atlanması asimetrik
olurdu ve "eşiği lehinize seçtiniz" itirazının doğal hedefi olur. İkisi de yazılıdır:

> RFC 9728 **§6 "String Operations"**: *"Unicode Normalization **MUST NOT** be applied at any
> point… Comparisons between the two strings **MUST** be performed as a Unicode
> code-point-to-code-point equality comparison."*
>
> RFC 8414 **§4**: aynı üç maddelik prosedür, birebir aynı lafız.

Yani her iki kontrolde de karşılaştırma **kod noktası eşitliğidir**; R9.2'deki
normalleştirmeler bu kuralın istisnası değil, *karşılaştırılan değerin ne olduğunun* RFC 3986
tarafından tanımlanmasıdır.

### R9.3 — Kalan farkın taksonomisi ve sonuç eşlemesi

Kanonikleştirmeden **sonra** kalan fark şöyle sınıflanır ve şu sonucu üretir:

| İlişki | C12 | C13 | Dayanak |
|---|---|---|---|
| `identical` | `PASS` | `PASS` | — |
| `trailing_slash_only` | **`UNSPECIFIED`** | `FAIL_MISIMPLEMENTED` | **R9.4 — asimetri spec'ten geliyor, seçim değil** |
| `case_path_only` | `FAIL_MISIMPLEMENTED` | `FAIL_MISIMPLEMENTED` | RFC 3986 §6.2.2.1: yol/query **case-sensitive**; `/MCP` ≠ `/mcp` |
| `scheme_only` | `FAIL_MISIMPLEMENTED` | §3.3; ayrıca MCP *"endpoints **MUST** be served over HTTPS"* |
| `port_only` | `FAIL_MISIMPLEMENTED` | §3.3 (varsayılan portlar R9.2'de zaten atıldı; buraya yalnız gerçek port farkı düşer) |
| `same_host_different_path` | `FAIL_MISIMPLEMENTED` | §3.3 |
| `related_host` | `FAIL_MISIMPLEMENTED` | §3.3 |
| `unrelated_host` | `FAIL_MISIMPLEMENTED` | §3.3 |

**Sıralama:** aynı host içinde en ağır bileşen adlandırılır — şema → port → yol. Farklı host'ta
alt/üst alan adı ilişkisi varsa `related_host`, yoksa `unrelated_host`.

`unrelated_host` **fall-through kova olamaz.** Her ayırt edilebilir fark sınıfı kendi adını
alır; makalenin retorik vuruşu (*"ilgisiz kaynak aynı issuer'ı ilan ediyor"*) bir `else`
dalından gelemez. Düzeltmeden önce `https://a.com:443/mcp` vs `https://a.com/mcp` — yani
tamamen uyumlu bir sunucu — `unrelated_host` kovasına düşüyordu.

### R9.4 — C12 ve C13 aynı taksonomiyi kullanır ama `trailing_slash_only`'de ayrışır

**Bu ayrışma bir tercih değil, ölçülebilirlik farkıdır.**

**C12'de beklenen değer gözlenmez, geri türetilir — ve türetme kayıplıdır.** RFC 9728 §3.1
sonlandırıcı slash'ı well-known ekini eklemeden **önce** attığı için `https://h/mcp` ve
`https://h/mcp/` **aynı** metadata URL'sinden sunulur. Dokümanın geldiği URL'den geri
türetilen şey bu yüzden bir *değer* değil, **iki elemanlı bir kümedir**:

- Gerçek identifier'ı `/mcp/` olan sunucu, `/mcp/` yankılayarak §3.3'e **tam uyar**.
- Gerçek identifier'ı `/mcp` olan sunucu, `/mcp/` yankılayarak §3.3'ü **ihlal eder**.

Enstrüman bu ikisini **ayırt edemez**. Ayırt edemediği bir sınıfa ceza kesmek, R6'nın
("bizim belirsizliğimiz UNSPECIFIED'dır") doğrudan ihlalidir — ve manşet ihlal oranına
karar verilemez bir kütle eklerdi. Bu, "eşiği sonuç lehine seçtiniz" itirazının en kolay
hedefiydi.

**C13'te böyle bir sorun yok.** Karşılaştırmanın sol tarafı — issuer string'i — kaynağın
kendi `authorization_servers` dizisinden **literal olarak okunur**. Geri türetme yok,
kayıp yok. RFC 8414 §3.3 gözlenen bir değere karşı özdeşlik istiyor, §4 kod noktası eşitliği
diyor: sondaki slash farkı **gerçek, mekanik olarak tespit edilebilir bir MUST ihlalidir** ve
istemcinin keşif zincirini fiilen kırar.

*(Not: kök seviyesindeki slash farkı — `https://h` ↔ `https://h/` — her iki kontrolde de
R9.2'de kanonikleştirmeyle yok edilir; RFC 3986 §6.2.3 bunları zaten eşdeğer ilan ediyor.
R9.4'ün konusu yalnız **yol taşıyan** identifier'lardaki slash farkıdır.)*

### R9.5 — Önceden ilan edilmiş duyarlılık çifti

C12 oranı **iki sayıyla** raporlanır: `trailing_slash_only` UNSPECIFIED sayılan (manşet, R9.3)
ve ihlal sayılan (katı kol) hâl. İkisi arasındaki fark makalede görünür olur; okuyucu kendi
okumasını uygulayabilir. **Manşet, UNSPECIFIED olanıdır** — çünkü katı kol, enstrümanın
ayırt edemediği bir sınıfı ihlal sayar.

`case_path_only` ve `port_only` gibi sınıflar duyarlılık çiftine girmez: bunlar
kanonikleştirmeden sonra kalan gerçek farklardır, belirsizlik değil.

---

## R10 — Analiz birimi ve küme tanımı ⚙️

Uçlar bağımsız değildir: bir avuç SDK, hosting platformu ve toplu yayıncı üzerinde koşarlar.
Küme tanımını veriden sonra seçmek, "istediğiniz güven aralığını veren kümelemeyi seçtiniz"
itirazına açıktır ve R1–R8'in tüm kazancını siler.

### R10.1 — Üç birim, üçü de her manşet oran için raporlanır

Hiçbir oran tek bir sayı olarak yayımlanmaz. Her biri **aynı tabloda** üç birimde verilir:

1. **uç başına** — her uç bir gözlem; aralık apex'e göre kümelenir
2. **apex alan adı (eTLD+1) başına** — apex başına **1 uç** · **birincil birim (R10.2)**
3. **implementasyon kümesi başına** — parmak izi başına **1 uç** (R10.2b)

**Birim değişince payda da değişir, yalnız aralık değil.** 2 ve 3'te popülasyon önce
daraltılır; aksi hâlde 300 listelemesi olan bir toplu yayıncı nokta tahminini yine
belirlerdi ve bunu yalnız güven aralığı fark ederdi. Hangi ucun apex'i temsil edeceği
**önceden sabitlenmiştir: en küçük `endpoint_id`.** Keyfi bir kuraldır, ama önceden ilan
edilmiş keyfî bir kural, sonradan seçilmiş savunulabilir bir kuraldan iyidir.

**Apex'in bilinen yanlılığı, şimdi yazılıyor.** Public suffix listesinin private bölümü
kapalı tutuluyor, yani `a.vercel.app` ve `b.vercel.app` aynı apex sayılıyor. Bir platform
kiracısının başka bir kiracının issuer'ına delege etmesi bu yüzden **aynı işletmeci** görünür
→ çapraz-işletmeci oranı **eksik** tahmin edilir. Yön muhafazakârdır (bulguyu şişirmez), ama
yazılmazsa hakem bulur.

### R10.2 — Birincil analiz birimi: apex alan adı

**Birincil birim = apex alan adı (eTLD+1), apex başına en fazla 1 uç.** Tamamen gözlenen,
deterministik, zaten toplanan ve okuyucunun bağımsız olarak denetleyebileceği tek birim
budur.

> **⚠️ Bu kural 28 Tem 2026'da, aynı gün, değiştirildi.** İlk hâli birincil kümeyi *"host'a
> özgü değerler yer tutucuyla değiştirildikten sonra PRM dokümanının bayt şeklinin
> SHA-256'sı"* diye tanımlıyordu. Dört bağımsız sebeple **uygulanamazdı** ve ikinci review
> turunda düştü:
>
> 1. *"Hangi alanlar host'a özgü"* bir insan kararıdır — yani elle yazılmış bir listedir. Kural
>    aynı cümlede *"elle yazılmış hiçbir liste gerektirmez, dolayısıyla yazarların rubriği
>    olamaz"* diyordu; kendi kendini çürütüyordu ve R10.3'ün yasağı ona da düşüyordu.
> 2. **Çözünürlük yok.** Uyumlu bir PRM dokümanı tipik olarak 2–4 anahtardır. Değerler
>    çıkarılınca binlerce uç bir avuç hash'e çöker, `m ≈ 3–8` olur ve R10.4'ün `t(m-1)`
>    tabanlı aralığı kullanılamaz genişliğe çıkar. R10.2, R10.4'ü fiilen imkânsız kılıyordu.
> 3. **Aynı anda aşırı kırılgan.** Bayt şekli *serializer*'ın özelliğidir, üreticinin değil:
>    aynı SDK, Cloudflare Workers arkasında ve doğrudan farklı baytlar üretir → tek üretici
>    birden çok kümeye bölünür. Hem az hem çok kümeleme yapıyordu.
> 4. Kodda hiç yoktu.

### R10.2b — İmplementasyon kümesi (duyarlılık kolu): değersiz parmak izi

İkincil kümeleme, **hiçbir değer içermeyen** deterministik bir parmak izinden türetilir:

```
fingerprint = SHA-256( JCS( {
  "prm_keys":  <PRM üst düzey üye adları, sıralı>,
  "prm_types": <her üyenin JSON tipi, aynı sırada>,      # "string" | "array<string>" | ...
  "as_keys":   <ilk gözlenen AS metadata üye adları, sıralı>,   # gözlenmediyse []
  "server":    <PRM yanıtının `server` başlığı, küçük harf, yoksa "">
} ) )
```

**Değer hiç girmez** → yer tutucu listesi gerekmez → "yazarların rubriği" itirazı yapısal
olarak kapanır. Bu, R10.2'nin ilk hâlinin *iddia ettiği* ama sağlayamadığı özelliktir.
Anahtar kümesi + tip, yeniden serileştirmeye dayanıklıdır ama farklı SDK'ları ayırır.
`server` başlığı tek elle-alınmış karardır; **onlu ve onsuz iki hâl birlikte raporlanır.**

**Diğer duyarlılık kolları** (hepsi ayrıca raporlanır): registry publisher namespace
(`io.github.<kullanıcı>/…`, registry tarafından DNS/OAuth ile doğrulanmış) · ASN · TLS
sertifika hash'i · ilan edilen issuer.

**Toplanamayan bir kol, kriteri taşıyamaz.** ASN ve sertifika karşılaştırması şu an kodda
yok. Toplanana kadar bunlar duyarlılık kolu olarak *raporlanır*, hiçbir karar kuralının
girdisi olamaz — go/no-go dahil. Bu, eski go/no-go kriterini geçersiz kılan hatanın
(ölçülmeyen niceliğe dayanmak) tekrarını engeller.

`serverInfo` küme değişkeni **değildir**: OAuth zorunlu kılan uçlar `initialize`'a da 401
döner, yani karar verici popülasyon için elde edilemez.

### R10.3 — Elle yazılmış platform listesi küme değişkeni olamaz

`_KNOWN_PLATFORM_SUFFIXES` yalnızca **etiketleme** içindir. Hosting sınıfı, gözlenen
sinyallerden (sertifika paylaşımı, ASN, PRM-hash) türetilir.

### R10.4 — Belirsizlik, küme sayısına göre raporlanır

Küme-robust oran güven aralığı, `m` küçük olduğu için `t(m-1)` tabanlıdır; `m < 30` ise wild
cluster bootstrap-t (Rademacher) ile de verilir. Her oranın yanında `m` (küme sayısı), DEFF ve
`n_eff` yazılır. Naif Wilson aralığı **tek başına yayımlanmaz**: kümelenme altında gerçek
kapsaması %95 değil, senaryoya göre %45–%82'dir.

---

---

## R11 — Manşet seçim kuralı ⚙️ *(veriden önce yazıldı)*

Elimizde birden çok aday manşet nicelik var ve hangisinin makaleyi taşıyacağı **veri
görülmeden bilinemez**. Veriye bakıp en gösterişli sayıyı manşet yapmak, R1–R10'un tüm
kazancını silecek klasik post-hoc hamledir. Bu yüzden seçim, aşağıdaki sıra ve ölçütle
**şimdi** kurala bağlanmıştır.

### R11.1 — Aday listesi kapalıdır

Makale şu niceliklerin **hepsini** raporlar. Listeye veri toplandıktan sonra ekleme yapılamaz:

| Sıra | Nicelik | Normatif çıpa | Neden bu sırada |
|---|---|---|---|
| **1** | **C16** — ilan edilen issuer'ların kaçı RFC 9207 `iss` desteğini ilan ediyor | RFC 9700 (BCP 240) §2.1: *"When an OAuth client can interact with more than one authorization server, a defense against mix-up attacks … is **REQUIRED**"* + RFC 9207 §3: sunucu desteğini **MUST** ilan eder | En güçlü çıpa. Zorunluluk istemcide ama **erişilebilirliği** sunucu tarafında gözlenir; ilan yoksa uyumlu istemci `false` varsaymak zorunda, yani savunma fiilen yok |
| **2** | **C18** — kaç AS `protected_resources` yayımlıyor, ve yayımlayanlarda çapraz kontrol geçiyor mu | RFC 9728 §4 (OPTIONAL) + §7.6 çapraz kontrol tavsiyesi | §7.6'nın önerdiği tek azaltımın konuşlandırılmış erişilebilirliği |
| **3** | Issuer yoğunlaşması + çapraz-işletmeci delegasyon oranı | Yok — saf topoloji | Çıpa gerektirmez, rubrik olamaz, varyans neredeyse garanti |
| **4** | **C12/C13** uygunluk oranları | RFC 9728 §3.3, RFC 8414 §3.3 (MUST) | Çıpa güçlü ama varyansı düşük olabilir ve bilinen SDK hatalarıyla kirlenmeye açık (R10 katmanlaması şart) |
| **5** | **C17** — istemci kimliği önyükleme erişilebilirliği | MCP kayıt merdiveni (SHOULD) | En zayıf çıpa; bölüm olur, manşet olmaz |

### R11.2 — Seçim ölçütü

> Manşet, **varyans testini geçen en yüksek sıralı** adaydır.
>
> **Varyans testi:** niceliğin küme-robust %95 güven aralığı (R10.4) ne `[0, %2]` içinde
> tamamen kalmalı ne de `[%98, 100]` içinde. Yani hem "hiç yok" hem "herkeste var"
> sonuçları manşet olamaz — ikisi de tek cümlelik bulgudur.
>
> Hiçbir aday geçemezse: manşet **3. sıradaki topoloji** olur (dağılım oranı değildir, bu
> yüzden varyans testine tabi değildir) ve uygunluk sayıları ikincil sonuç olarak verilir.

### R11.3 — Öngörülen risk, şimdi yazılıyor

C16'nın **varyans testinde düşmesi ciddi bir olasılıktır**: ilan edilen issuer popülasyonu
Auth0/Okta/Entra/Clerk gibi olgun IdP'lerde yoğunlaşıyorsa ve hepsi `iss` destekliyorsa oran
%100'e yapışabilir. Bu tahmin **veriden önce** kayda geçirilmiştir; gerçekleşirse kural
gereği C16 manşetten düşer ve bu düşüş makalede **öngörülmüş bir sonuç** olarak raporlanır,
sessizce gizlenmez.

Simetrik olarak: C16 %0'a yakın çıkarsa da manşet olamaz — ama o durumda bulgu *"BCP 240'ın
REQUIRED saydığı savunma, ekosistemin hiçbir yerinde erişilebilir değil"* şeklinde tek
cümlelik ama güçlü bir sonuçtur ve 3. sıradaki topolojiyle birlikte anlatılır.

### R11.5 — Her aday için birim, payda ve toplama kuralı ⚙️

R11.1 adayları sıralıyor ama **hangi birimde ve hangi paydayla** ölçüleceklerini söylemiyordu.
Bu, R11'in kapatmak için var olduğu kapının yan penceresiydi: kod C16'yı uç düzeyinde
hep-ya-hiç hesaplıyor, R11.1 metni ise issuer oranı tarif ediyor, ve ikisi keyfî ölçüde
ayrışabilir — 5 issuer ilan edip 4'ü destekleyen bir uç issuer düzeyinde %80, uç düzeyinde
%0'dır. Seçim analiz anına bırakılırsa post-hoc olur. Burada, veriden önce sabitlenmiştir.

| Aday | Birim | Payda | Uç birden çok issuer ilan ederse |
|---|---|---|---|
| **C16** | benzersiz **ilan edilen** issuer | **ilan edilen.** Erişilemeyen issuer "ilan etmiyor" sayılır — istemci ulaşamadığı bir savunmayı kullanamaz | issuer başına bir gözlem; "tüm issuer'ları destekleyen uç" oranı **ikincil** verilir |
| **C17** | benzersiz ilan edilen issuer | ilan edilen | aynı |
| **C18** | benzersiz **gözlenen** issuer | gözlenen. `cross_check_possible` **boş listeyi saymaz**; `empty_list` ayrı sayı olarak raporlanır | aynı |
| **Topoloji** | apex alan adı | — (oran değil) | — |
| **C12/C13** | R10.1'in üç birimi | R10.1 | — |

**Varyans testi (R11.2) issuer düzeyinde**, issuer'ın apex'ine göre kümelenmiş küme-robust
aralığa uygulanır.

**Alternatif payda (gözlenen ↔ ilan edilen) önceden ilan edilmiş duyarlılık çiftidir** ve
R9.5 ile birebir aynı biçimde raporlanır: iki sayı da basılır, hangisinin manşet olduğu
yukarıdaki tabloda **şimdi** seçilmiştir.

**Çapraz-işletmeci vekili: yalnız apex.** ASN ve TLS sertifikası duyarlılık kolu olarak
ilan edilmişti; ASN hiç toplanmıyor, sertifika toplanıyor ama karşılaştırılmıyor. R10.2
gereği toplanamayan kol hiçbir sonucun girdisi olamaz — dolayısıyla **vaat de edilmez.**

### R11.4 — Başlık ölçümden sonra sabitlenir

Makale başlığı bir ölçüm sonucu içeremez (*"Cannot Verify"*, *"Nobody Implements"* gibi)
manşet belirlenmeden. Başlık adayları planda tutulur, ölçüm sonrası seçilir. Bu, R11.2'nin
doğal sonucudur.

---

## R12 — Raporlama taahhüdü ⚙️ *(veriden önce)*

Alet, hiçbir belgede varış yeri olmayan nicelikler topluyor. **Toplanmış ama varış yeri ilan
edilmemiş bir alan, tanımı gereği serbest bir parametredir:** analizde işe yaramazsa sessizce
düşer, yararsa "ek bulgu" olarak çıkar. Bu, R11'in kapattığı kapının yan penceresidir ve
aynı biçimde kapatılır — liste veri toplandıktan **sonra genişletilemez.**

| Nicelik | Nerede raporlanır |
|---|---|
| C12/C13 sonuçları, üç birimde | §5 (Sonuçlar), ana tablo |
| C16 · C17 · C18 (R11.5 paydalarıyla) | §5, R11.1 sırasında |
| Issuer yoğunlaşması (HHI, top-k), delegasyon grafiği | §5, Figür 1 |
| Çapraz-işletmeci delegasyon oranı (apex vekili) | §5 |
| `shared_across_apexes` — iki+ ilgisiz apex'in aynı issuer URL'ini ilan etmesi | §5 |
| **`hint_rejected_reason` dağılımı** | **§5, kendi alt bölümü** — aşağı bak |
| `resource_relation` taksonomi dağılımı (R9.3'ün sekiz kovası) | §6 (Arıza sınıfları) |
| `as_issuer_relations` dağılımı | §6 |
| `empty_list` (C18) | §6 |
| `malformed_authorization_servers` sayısı | §6 |
| `prm_scope_covers_endpoint` | §6, betimsel |
| `excluded_robots` · `excluded_opt_out` · `excluded_crossed_origin` | §4 (Metodoloji), payda tablosu |
| `dropped_no_apex` · `dropped_not_https` · `TRUNCATED` uyarıları | §4 |
| Blok oranı, Manski sınırları | §4 ve §9 |
| `implementation_fingerprint` küme sayısı, `_no_server` kolu | §4, küme yapısı tablosu |
| `publisher_namespace` dağılımı | §4, çerçeve yapısı |
| `robots_excluded_urls` (URL listesi) | **yalnız veri setinde**, makalede sayı olarak |
| Ham artefaktlar | yalnız veri setinde |

**`hint_rejected_reason` neden kendi alt bölümünü hak ediyor:** `WWW-Authenticate`'ini kendi
apex'i dışına — ya da loopback/RFC 1918'e — işaret eden uçların sayısı, RFC 9728 §7.6'nın
**adıyla andığı saldırı yüzeyinin doğrudan gözlemidir.** Makalenin çıpasına en yakın
niceliktir ve alet onu zaten topluyor. Raporlanmaması, ölçülüp saklanan bir bulguyu
görmezden gelmek olurdu.

---

## Payda kuralları

- `robots.txt` ile dışlanan uçlar **paydadan tamamen çıkarılır**. Aksi halde etik politika
  sonucu yanlılaştırır.
- Çapraz-origin yönlendirme sonrası bulunan doküman, orijinal host'a **yazılmaz**
  (`EndpointReport.crossed_origin()`). Ayrı raporlanır.
- İki huni (`FUNNEL_OAUTH`, `FUNNEL_SIGNED`) **ayrık paydalar** üzerinde raporlanır.
  Tek huni, bir modaliteye hiç girmemiş ucu "başarısız" saymak olurdu — bu, başarısızlık
  değil kompozisyondur.

## Huni değişmezi

Her kademenin uygulanabilir kümesi, bir önceki kademenin `PASS` kümesinin **alt kümesi**
olmalıdır. (Kontrol ID sırası değil — bu, meşru bir kademe eklemeyi imkânsız kılardı.)

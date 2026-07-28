# Karar Kuralları

**Durum: DONDURULDU — 27 Temmuz 2026, veri toplamadan önce.**

Bu kurallar veri görülmeden yazıldı. Amaç, "sonucu sonradan seçtiniz" (post-hoc / HARKing)
suçlamasını yapısal olarak imkânsız kılmak. Kuralların çoğu `models.py` içinde makine ile
zorlanır; zorlanamayan ikisi (R5, R8) koşum protokolünde belirtilmiştir.

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

## R7 — Sürüm sabitleme ⚙️

Her uç, **kendi beyan ettiği spec revizyonuna** göre puanlanır (`CheckResult.spec_version`).
MCP 2025-11-25 ile 2025-06-18 farklı gereksinimlere sahiptir; revizyonu karıştırmak,
ekosistemi değil spec değişimini ölçmek demektir.

Beyan yoksa: uç, ölçüm tarihinde yürürlükte olan en son revizyona göre değil, **en
müsamahakâr yürürlükteki revizyona** göre puanlanır. Şüphe deployment lehinedir.

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
